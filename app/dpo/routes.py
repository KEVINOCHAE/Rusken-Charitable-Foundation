from flask import Blueprint, request, jsonify, current_app, url_for
from flask_login import current_user
import requests
from app import db
from datetime import datetime
from app import csrf
from decimal import Decimal
from app.admin.models import Donation, Program

dpo_bp = Blueprint('dpo', __name__)


@dpo_bp.route('/initialize', methods=['POST'])
def initialize_payment():
    data = request.get_json() or {}
    email = data.get('email')
    raw_amount = data.get('amount')
    program_id = data.get('program_id')
    donor_name = data.get('donor_name') or (
        current_user.username if current_user.is_authenticated else 'Anonymous'
    )

    if not email or not raw_amount:
        return jsonify({'status': False, 'message': 'Amount and email are required'}), 400

    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal('0.01'))
        if amount <= 0:
            raise InvalidOperation()
    except InvalidOperation:
        return jsonify({'status': False, 'message': 'Invalid amount format'}), 400

    try:
        donation = Donation(
            program_id=program_id,
            user_id=current_user.id if current_user.is_authenticated else None,
            donor_name=donor_name,
            donor_email=email,
            amount=amount,
            currency='KES',
            status='pending',
            created_at=datetime.utcnow()
        )
        db.session.add(donation)
        db.session.flush()

        metadata = {
            'donation_id': donation.id,
            'donor_email': email,
            'donor_name': donor_name,
            'user_id': current_user.get_id() if current_user.is_authenticated else None,
            'program_id': program_id,
            'general': program_id is None
        }

        payload = {
            "CompanyToken": current_app.config["DPO_COMPANY_TOKEN"],
            "Request": "createToken",
            "Transaction": {
                "PaymentAmount": str(amount),
                "PaymentCurrency": "KES",
                "CompanyRef": f"DONATION_{donation.id}",
                "CustomerEmail": email,
                "CustomerFirstName": donor_name.split()[0] if donor_name else "",
                "CustomerLastName": " ".join(donor_name.split()[1:]) if donor_name else "",
                "ServiceType": current_app.config["DPO_SERVICE_TYPE"],
                "RedirectURL": url_for('donate.payment_callback', _external=True),
                "BackURL": url_for('donate.payment_cancel', _external=True),
                "CompanyFields": [
                    {"key": k, "value": str(v)} for k, v in metadata.items()
                ]
            }
        }

        # Make DPO API call
        resp = requests.post(
            current_app.config["DPO_API_URL"],
            json=payload,
            timeout=10
        )

        current_app.logger.info(f"DPO Raw Response: {resp.status_code} - {resp.text}")

        if resp.status_code != 200:
            raise Exception(f"DPO returned status {resp.status_code}")

        if not resp.content.strip():
            raise Exception("DPO returned an empty response")

        try:
            result = resp.json()
        except ValueError:
            raise Exception(f"DPO response is not valid JSON: {resp.text}")

        if result.get("Result") != "000":
            db.session.rollback()
            current_app.logger.error(f"DPO init error: {result.get('ResultExplanation')}")
            return jsonify({
                'status': False,
                'message': result.get('ResultExplanation', 'Payment initialization failed')
            }), 400

        donation.gateway_reference = result['TransToken']
        donation.payment_gateway = 'dpo'
        db.session.commit()

        return jsonify({
            'status': True,
            'authorization_url': f"{current_app.config['DPO_PAYMENT_PAGE']}?ID={result['TransToken']}",
            'reference': result['TransToken']
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error during DPO initialization: {e}")
        return jsonify({
            'status': False,
            'message': 'An unexpected error occurred while processing your payment'
        }), 500




        