from flask import Blueprint, request, jsonify, current_app, url_for
from flask_login import current_user
import requests
from app import db
from app.admin.models import Donation
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import re
import time

dpo_bp = Blueprint('dpo', __name__)

def build_dpo_payload(company_token, donation, donor_name, email, amount, service_type):
    """Build properly escaped XML payload for DPO API with all required fields"""
    first_name = donor_name.split()[0] if donor_name else ""
    last_name = " ".join(donor_name.split()[1:]) if donor_name and len(donor_name.split()) > 1 else ""
    
    return f"""<?xml version="1.0" encoding="utf-8"?>
<API3G>
  <CompanyToken>{escape(company_token)}</CompanyToken>
  <Request>createToken</Request>
  <Transaction>
    <PaymentAmount>{escape(str(amount))}</PaymentAmount>
    <PaymentCurrency>KES</PaymentCurrency>
    <CompanyRef>{escape(f"DONATION_{donation.id}")}</CompanyRef>
    <CustomerEmail>{escape(email)}</CustomerEmail>
    <CustomerFirstName>{escape(first_name)}</CustomerFirstName>
    <CustomerLastName>{escape(last_name)}</CustomerLastName>
    <RedirectURL>{escape(url_for('donate.payment_callback', _external=True))}</RedirectURL>
    <BackURL>{escape(url_for('donate.payment_cancel', _external=True))}</BackURL>
    <ServiceType>{escape(service_type)}</ServiceType>
    <CompanyFields>
      <CompanyField>
        <Key>donation_id</Key>
        <Value>{donation.id}</Value>
      </CompanyField>
      <CompanyField>
        <Key>donor_email</Key>
        <Value>{email}</Value>
      </CompanyField>
    </CompanyFields>
    <Services>
      <Service>
        <ServiceType>{escape(service_type)}</ServiceType>
        <ServiceDescription>Donation Payment</ServiceDescription>
        <ServiceDate>{datetime.utcnow().strftime('%Y/%m/%d')}</ServiceDate>
      </Service>
    </Services>
  </Transaction>
</API3G>"""

@dpo_bp.route('/initialize', methods=['POST'])
def initialize_payment():
    """
    Initialize DPO payment transaction with all required fields
    """
    # Configuration validation
    required_configs = ['DPO_API_URL', 'DPO_COMPANY_TOKEN', 'DPO_SERVICE_TYPE', 'DPO_PAYMENT_PAGE']
    if any(not current_app.config.get(key) for key in required_configs):
        current_app.logger.error("Missing DPO configuration")
        return jsonify({
            'status': False,
            'message': 'Payment system temporarily unavailable'
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
        return jsonify({'status': False, 'message': 'Email is required'}), 400
    if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
        return jsonify({'status': False, 'message': 'Invalid email format'}), 400
    if not raw_amount:
        return jsonify({'status': False, 'message': 'Amount is required'}), 400

    # Validate amount
    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal('0.01'))
        if amount <= Decimal('0.00'):
            raise ValueError('Amount must be positive')
        if amount > Decimal('1000000.00'):
            return jsonify({'status': False, 'message': 'Amount exceeds maximum limit'}), 400
    except (InvalidOperation, ValueError):
        return jsonify({'status': False, 'message': 'Invalid amount format'}), 400

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
                xml_payload = build_dpo_payload(
                    current_app.config["DPO_COMPANY_TOKEN"],
                    donation,
                    donor_name,
                    email,
                    amount,
                    current_app.config["DPO_SERVICE_TYPE"]
                )

                headers = {
                    "Content-Type": "application/xml",
                    "Accept": "application/xml",
                    "User-Agent": "FlaskDPOClient/1.0"
                }

                resp = requests.post(
                    current_app.config["DPO_API_URL"],
                    data=xml_payload,
                    headers=headers,
                    timeout=(3.05, 15)
                )
                
                current_app.logger.debug(f"DPO API Attempt {attempt + 1}: {resp.status_code} - {resp.text[:200]}...")

                if resp.status_code != 200:
                    raise ValueError(f"DPO returned status {resp.status_code}")

                # Parse XML response
                try:
                    root = ET.fromstring(resp.content)
                    result_code = root.findtext("Result")
                    result_explanation = root.findtext("ResultExplanation")
                    trans_token = root.findtext("TransToken")

                    if result_code != "000":
                        raise ValueError(result_explanation or "DPO initialization failed")
                    if not trans_token:
                        raise ValueError("Missing transaction token in response")

                    # Save successful transaction
                    donation.gateway_reference = trans_token
                    donation.payment_gateway = 'dpo'
                    db.session.commit()

                    return jsonify({
                        'status': True,
                        'authorization_url': f"{current_app.config['DPO_PAYMENT_PAGE']}?ID={trans_token}",
                        'reference': trans_token,
                        'expires_at': (datetime.utcnow() + timedelta(minutes=30)).isoformat()
                    }), 200

                except ET.ParseError as e:
                    raise ValueError(f"Invalid XML response: {str(e)}")

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