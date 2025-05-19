import base64, json
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import datetime
import requests

from flask import (
    Blueprint, request, jsonify,
    current_app, flash, redirect,
    url_for, render_template
)
from flask_login import current_user
from app import db
from app.admin.models import Donation
from paypalcheckoutsdk.core import PayPalHttpClient, SandboxEnvironment
from paypalcheckoutsdk.orders import OrdersCreateRequest

paypal_bp = Blueprint('paypal', __name__, url_prefix='/paypal')

class PaymentError(Exception): pass


def _paypal_api_base():
   
    return "api-m.paypal.com"

def _get_access_token():
    cid    = current_app.config['PAYPAL_CLIENT_ID']
    secret = current_app.config['PAYPAL_SECRET']
    creds  = base64.b64encode(f"{cid}:{secret}".encode()).decode()

    # Build the correct URL: https://api-m.paypal.com/v1/oauth2/token
    url = f"https://{_paypal_api_base()}/v1/oauth2/token"
    resp = requests.post(
        url,
        headers={
            'Authorization': f'Basic {creds}',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        data={'grant_type':'client_credentials'},
        timeout=10
    )

    if resp.status_code != 200:
        raise PaymentError(f"PayPal auth failed: {resp.status_code} {resp.text}")

    return resp.json()['access_token']


@paypal_bp.route('/initialize', methods=['POST'])
def initialize():
    data       = request.get_json() or {}
    email      = data.get('email')
    raw_amount = data.get('amount')
    program_id = data.get('program_id')
    donor_name = data.get('donor_name') or (
        current_user.username if current_user.is_authenticated else 'Anonymous'
    )

    # 1. Validate
    if not email or not raw_amount:
        return jsonify(status=False, message="Email & amount required"), 400
    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal('0.01'))
        if amount <= 0: raise InvalidOperation()
    except:
        return jsonify(status=False, message="Invalid amount"), 400

    # 2. Create pending Donation
    donation = Donation(
        program_id       = program_id,
        user_id          = current_user.id if current_user.is_authenticated else None,
        donor_name       = donor_name,
        donor_email      = email,
        amount           = amount,
        currency         = 'USD',   # PayPal orders in USD
        status           = 'pending',
        created_at       = datetime.utcnow(),
        payment_gateway  = 'paypal'
    )
    db.session.add(donation)
    db.session.flush()

    # 3. Build PayPal order payload
    callback_url = url_for('paypal.callback', _external=True)
    cancel_url   = url_for('main.home', _external=True)
    purchase_unit = {
        "reference_id": f"donation_{donation.id}",
        "amount": {
            "currency_code": "USD",
            "value": str(amount)
        },
        # Store program_id/general flag in custom_id
        "custom_id": json.dumps({
            "donation_id": donation.id,
            "program_id": program_id,
            "general": program_id is None
        })
    }
    order_payload = {
        "intent": "CAPTURE",
        "purchase_units": [purchase_unit],
        "application_context": {
            "return_url": callback_url,
            "cancel_url": cancel_url
        }
    }

    try:
        # 4. Create PayPal order
        token = _get_access_token()
        resp = requests.post(
            f"https://{_paypal_api_base()}/v2/checkout/orders",
            json=order_payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            timeout=10
        )
        resp.raise_for_status()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"PayPal order creation failed: {e}")
        return jsonify(status=False, message="Could not initialize PayPal payment"), 500

    order = resp.json()
    # 5. Save PayPal order ID as reference, commit
    donation.gateway_reference = order['id']
    db.session.commit()

    # 6. Extract approval link
    for link in order.get('links', []):
        if link.get('rel') == 'approve':
            return jsonify(status=True, authorization_url=link['href'])

    return jsonify(status=False, message="Approval URL not found"), 500


@paypal_bp.route('/callback')
def callback():
    order_id = request.args.get('token')  # PayPal uses `token` param
    if not order_id:
        flash("Missing PayPal token", "danger")
        return redirect(url_for('main.home'))

    try:
        # 1. Capture the order
        token = _get_access_token()
        cap = requests.post(
            f"https://{_paypal_api_base()}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            timeout=10
        )
        cap.raise_for_status()
        data = cap.json()

        # 2. Ensure COMPLETED
        if data.get("status") != "COMPLETED":
            raise PaymentError(f"Order {order_id} status {data.get('status')}")

        # 3. Extract capture details
        pu = data["purchase_units"][0]
        capture = pu["payments"]["captures"][0]
        amt = Decimal(capture["amount"]["value"]).quantize(Decimal("0.01"), ROUND_HALF_UP)
        currency = capture["amount"]["currency_code"]
        payer_email = data["payer"]["email_address"]

        # 4. Get metadata
        custom = pu.get("custom_id") or "{}"
        metadata = json.loads(custom)

        # 5. Lookup or create Donation
        donation = Donation.query.filter_by(gateway_reference=order_id).first()
        is_new = False
        if not donation:
            donation = Donation(
                program_id       = metadata.get("program_id"),
                user_id          = metadata.get("user_id"),
                donor_name       = metadata.get("donor_name", "Anonymous")[:100],
                donor_email      = payer_email,
                amount           = amt,
                currency         = currency,
                status           = 'pending',
                gateway_reference= order_id,
                payment_gateway  = 'paypal',
                gateway_metadata = metadata,
                created_at       = datetime.utcnow()
            )
            db.session.add(donation)
            is_new = True
        elif donation.status == 'completed':
            return _redirect_after(donation)

        # 6. Tamper check
        if not is_new and donation.amount != amt:
            raise PaymentError("Amount mismatch")

        # 7. Mark complete
        donation.status     = 'completed'
        donation.updated_at = datetime.utcnow()
        db.session.commit()

        return _redirect_after(donation)

    except PaymentError as e:
        logger.error(f"PayPal callback error: {e}")
        flash("Payment verification failed", "danger")
        db.session.rollback()
    except Exception as e:
        logger.exception(f"Unexpected error in PayPal callback: {e}")
        flash("An error occurred", "danger")
        db.session.rollback()

    return redirect(url_for('main.home'))


def _redirect_after(donation):
    from flask_login import current_user
    if current_user.is_authenticated:
        return redirect(url_for('donate.confirmation', donation_id=donation.id))
    return render_template('donate/guest_confirmation.html', donation=donation)
