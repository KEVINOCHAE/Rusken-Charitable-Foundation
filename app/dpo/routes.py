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

# DPO Configuration Constants
DPO_COMPANY_TOKEN = "8D3DA73D-9D7F-4E09-96D4-3D44E7A83EA3"  # Your test token
DPO_SERVICE_TYPE = "5525"  # Your test service type
DPO_API_URL = "https://secure.3gdirectpay.com/API/v6/"
DPO_PAYMENT_URL = "https://secure.3gdirectpay.com/payv2.php"
DPO_PTL = 5  # Payment time limit in hours (5 hours is standard for DPO)

def build_dpo_payload(donation, email, amount):
    """Build XML payload matching DPO's exact specification with proper escaping"""
    service_date = datetime.utcnow().strftime('%Y/%m/%d %H:%M')
    
    return f"""<?xml version="1.0" encoding="utf-8"?>
<API3G>
  <CompanyToken>{escape(DPO_COMPANY_TOKEN)}</CompanyToken>
  <Request>createToken</Request>
  <Transaction>
    <PaymentAmount>{escape(str(amount))}</PaymentAmount>
    <PaymentCurrency>KES</PaymentCurrency>
    <CompanyRef>{escape(f"DONATION_{donation.id}")}</CompanyRef>
    <RedirectURL>{escape(url_for('donate.payment_callback', _external=True))}</RedirectURL>
    <BackURL>{escape(url_for('donate.payment_cancel', _external=True))}</BackURL>
    <CompanyRefUnique>0</CompanyRefUnique>
    <PTL>{DPO_PTL}</PTL>
  </Transaction>
  <Services>
    <Service>
      <ServiceType>{escape(DPO_SERVICE_TYPE)}</ServiceType>
      <ServiceDescription>Donation Payment</ServiceDescription>
      <ServiceDate>{service_date}</ServiceDate>
    </Service>
  </Services>
</API3G>"""

@dpo_bp.route('/initialize', methods=['POST'])
@csrf.exempt
def initialize_payment():
   
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
                    DPO_API_URL,
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
                    'authorization_url': f"{DPO_PAYMENT_URL}?ID={trans_token}",
                    'reference': trans_token,
                    'expires_in_hours': DPO_PTL,
                    'expires_at': (datetime.utcnow() + timedelta(hours=DPO_PTL)).isoformat()
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