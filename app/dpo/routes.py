from flask import Blueprint, request, jsonify, current_app, url_for
from flask_login import current_user
import requests
from app import db, csrf
from app.admin.models import Donation
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import re
import time

dpo_bp = Blueprint('dpo', __name__)

def build_dpo_payload(donation, email, amount):
    """Build XML payload with proper callback and redirect URLs"""
    service_date = datetime.utcnow().strftime('%Y/%m/%d %H:%M')

    # ✅ NEW: User is redirected here after payment to verify & confirm donation
    user_redirect_url = url_for(
        'donate.dpo_redirect',  # <-- new redirect route that verifies & updates DB
        TransactionToken=donation.gateway_reference,
        _external=True
    )

    # ❌ Cancelled or user backs out
    user_back_url = url_for(
        'donate.payment_cancel',
        program_id=donation.program_id,
        _external=True
    )

    # ✅ Server-to-server notification from DPO
    callback_url = url_for(
        'donate.payment_callback',
        _external=True
    )

    return f"""<?xml version="1.0" encoding="utf-8"?>
<API3G>
  <CompanyToken>{escape(current_app.config['DPO_COMPANY_TOKEN'])}</CompanyToken>
  <Request>createToken</Request>
  <Transaction>
    <PaymentAmount>{escape(str(amount))}</PaymentAmount>
    <PaymentCurrency>KES</PaymentCurrency>
    <CompanyRef>{escape(f"DONATION_{donation.id}")}</CompanyRef>
    <RedirectURL>{escape(user_redirect_url)}</RedirectURL>
    <BackURL>{escape(user_back_url)}</BackURL>
    <CallbackURL>{escape(callback_url)}</CallbackURL>
    <CompanyRefUnique>0</CompanyRefUnique>
    <PTL>{current_app.config.get('DPO_PTL', 5)}</PTL>
  </Transaction>
  <Services>
    <Service>
      <ServiceType>{escape(current_app.config['DPO_SERVICE_TYPE'])}</ServiceType>
      <ServiceDescription>Donation Payment</ServiceDescription>
      <ServiceDate>{service_date}</ServiceDate>
    </Service>
  </Services>
</API3G>"""


@dpo_bp.route('/initialize', methods=['POST'])
@csrf.exempt
def initialize_payment():
    
    # Validate configurations
    required_configs = ['DPO_API_URL', 'DPO_COMPANY_TOKEN', 'DPO_SERVICE_TYPE', 'DPO_PAYMENT_URL']
    missing_configs = [key for key in required_configs if not current_app.config.get(key)]
    if missing_configs:
        current_app.logger.error(f"Missing DPO configurations: {missing_configs}")
        return jsonify({
            'status': False,
            'message': 'Payment system temporarily unavailable',
            'error': 'MISSING_CONFIGURATION'
        }), 500

    # Request validation
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    raw_amount = data.get('amount')
    program_id = data.get('program_id')
    donor_name = (data.get('donor_name') or '').strip() or (
        current_user.username if current_user.is_authenticated else 'Anonymous'
    )

    # Validate required fields
    if not email:
        return jsonify({'status': False, 'message': 'Email is required', 'error': 'VALIDATION_ERROR'}), 400
    if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
        return jsonify({'status': False, 'message': 'Invalid email format', 'error': 'VALIDATION_ERROR'}), 400
    if not raw_amount:
        return jsonify({'status': False, 'message': 'Amount is required', 'error': 'VALIDATION_ERROR'}), 400

    # Validate amount
    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal('0.01'))
        if amount <= Decimal('0.00'):
            raise ValueError('Amount must be positive')
        if amount > Decimal('1000000.00'):
            return jsonify({'status': False, 'message': 'Amount exceeds maximum limit', 'error': 'VALIDATION_ERROR'}), 400
    except (InvalidOperation, ValueError):
        return jsonify({'status': False, 'message': 'Invalid amount format', 'error': 'VALIDATION_ERROR'}), 400

    try:
        # Create donation record
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

        # Prepare and send DPO request with retry logic
        max_retries = 3
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                xml_payload = build_dpo_payload(donation, email, amount)
                headers = {
                    "Content-Type": "application/xml",
                    "Accept": "application/xml",
                    "User-Agent": "DPO-Client/1.0"
                }

                resp = requests.post(
                    current_app.config['DPO_API_URL'],
                    data=xml_payload,
                    headers=headers,
                    timeout=(3.05, 15)  # Connect timeout, read timeout
                )
                
                current_app.logger.debug(f"DPO API Attempt {attempt + 1}: {resp.status_code} - {resp.text[:200]}...")

                if resp.status_code != 200:
                    raise ValueError(f"DPO returned status {resp.status_code}")

                # Parse XML response
                root = ET.fromstring(resp.content)
                result_code = root.findtext("Result")
                trans_token = root.findtext("TransToken")
                result_explanation = root.findtext("ResultExplanation")

                if result_code != "000":
                    raise ValueError(result_explanation or "Payment initialization failed")
                if not trans_token:
                    raise ValueError("Missing transaction token in response")

                # Save successful transaction
                donation.gateway_reference = trans_token
                donation.payment_gateway = 'dpo'
                db.session.commit()

                return jsonify({
                    'status': True,
                    'authorization_url': f"{current_app.config['DPO_PAYMENT_URL']}?ID={trans_token}",
                    'reference': trans_token,
                    'expires_in_hours': current_app.config.get('DPO_PTL', 5),
                    'expires_at': (datetime.utcnow() + timedelta(hours=current_app.config.get('DPO_PTL', 5))).isoformat()
                }), 200

            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # Exponential backoff
                    current_app.logger.warning(f"Retry #{attempt + 1} in {wait_time}s...")
                    time.sleep(wait_time)
                continue

        raise last_exception or ValueError("Payment service unavailable after multiple attempts")

    except ValueError as e:
        db.session.rollback()
        current_app.logger.warning(f"Payment validation failed: {str(e)}")
        return jsonify({
            'status': False,
            'message': str(e),
            'error': 'VALIDATION_ERROR'
        }), 400
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Payment processing failed: {str(e)}")
        return jsonify({
            'status': False,
            'message': 'An unexpected error occurred' if not current_app.debug else str(e),
            'error': 'SERVER_ERROR'
        }), 500