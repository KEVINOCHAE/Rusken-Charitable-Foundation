from flask import Blueprint, request, jsonify, current_app, url_for
from flask_login import current_user
import requests
from app import db
from app.admin.models import Donation
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from datetime import datetime
from werkzeug.exceptions import BadRequest
import re

dpo_bp = Blueprint('dpo', __name__)

@dpo_bp.route('/initialize', methods=['POST'])
def initialize_payment():
    """
    Initialize DPO payment transaction
    ---
    [Swagger documentation would go here]
    """
    # 1. Configuration validation
    required_configs = ['DPO_API_URL', 'DPO_COMPANY_TOKEN', 'DPO_SERVICE_TYPE', 'DPO_PAYMENT_PAGE']
    if any(not current_app.config.get(key) for key in required_configs):
        current_app.logger.error("Missing DPO configuration")
        return jsonify({
            'status': False,
            'message': 'Payment system temporarily unavailable'
        }), 500

    # 2. Request validation
    try:
        data = request.get_json() or {}
        if not data:
            raise BadRequest('Empty request body')
            
        email = data.get('email', '').strip()
        raw_amount = data.get('amount')
        program_id = data.get('program_id')
        donor_name = (data.get('donor_name') or '').strip() or (
            current_user.username if current_user.is_authenticated else 'Anonymous'
        )

        # Email validation
        if not email:
            return jsonify({'status': False, 'message': 'Email is required'}), 400
        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
            return jsonify({'status': False, 'message': 'Invalid email format'}), 400

        # Amount validation
        if not raw_amount:
            return jsonify({'status': False, 'message': 'Amount is required'}), 400
        try:
            amount = Decimal(str(raw_amount)).quantize(Decimal('0.01'))
            if amount <= Decimal('0.00'):
                raise ValueError('Amount must be positive')
        except (InvalidOperation, ValueError):
            return jsonify({'status': False, 'message': 'Invalid amount format'}), 400

        # 3. Create donation record
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

        # 4. Prepare XML payload
        payload_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<API3G>
  <CompanyToken>{current_app.config["DPO_COMPANY_TOKEN"]}</CompanyToken>
  <Request>createToken</Request>
  <Transaction>
    <PaymentAmount>{format(amount, '.2f')}</PaymentAmount>
    <PaymentCurrency>KES</PaymentCurrency>
    <CompanyRef>DONATION_{donation.id}</CompanyRef>
    <CustomerEmail>{email}</CustomerEmail>
    <CustomerFirstName>{donor_name.split()[0] if donor_name else ''}</CustomerFirstName>
    <CustomerLastName>{" ".join(donor_name.split()[1:]) if donor_name else ''}</CustomerLastName>
    <RedirectURL>{url_for('donate.payment_callback', _external=True)}</RedirectURL>
    <BackURL>{url_for('donate.payment_cancel', _external=True)}</BackURL>
    <ServiceType>{current_app.config["DPO_SERVICE_TYPE"]}</ServiceType>
    <CompanyFields>
      <CompanyField>
        <Key>donation_id</Key>
        <Value>{donation.id}</Value>
      </CompanyField>
      <CompanyField>
        <Key>donor_email</Key>
        <Value>{email}</Value>
      </CompanyField>
      <CompanyField>
        <Key>program_id</Key>
        <Value>{program_id if program_id else ''}</Value>
      </CompanyField>
    </CompanyFields>
  </Transaction>
</API3G>"""

        headers = {
            "Content-Type": "application/xml",
            "Accept": "application/xml",
            "User-Agent": "FlaskDPOClient/1.0"
        }

        # 5. Send request to DPO
        try:
            resp = requests.post(
                current_app.config["DPO_API_URL"],
                data=payload_xml,
                headers=headers,
                timeout=15
            )
            current_app.logger.info(f"DPO API Response: {resp.status_code} - {resp.text[:200]}...")

            if resp.status_code != 200:
                raise ValueError(f"DPO returned status {resp.status_code}")

            # 6. Parse XML response
            try:
                root = ET.fromstring(resp.content)
                result_code = root.findtext("Result")
                result_explanation = root.findtext("ResultExplanation")
                trans_token = root.findtext("TransToken")

                if result_code != "000":
                    raise ValueError(result_explanation or "DPO initialization failed")
                if not trans_token:
                    raise ValueError("DPO did not return a transaction token")

            except ET.ParseError as e:
                raise ValueError(f"Invalid XML response from DPO: {str(e)}")

            # 7. Save successful transaction
            donation.gateway_reference = trans_token
            donation.payment_gateway = 'dpo'
            db.session.commit()

            return jsonify({
                'status': True,
                'authorization_url': f"{current_app.config['DPO_PAYMENT_PAGE']}?ID={trans_token}",
                'reference': trans_token
            }), 200

        except requests.exceptions.RequestException as e:
            raise ValueError(f"DPO connection error: {str(e)}")

    except ValueError as e:
        db.session.rollback()
        current_app.logger.warning(f"Payment validation failed: {str(e)}")
        return jsonify({
            'status': False,
            'message': str(e)
        }), 400
        
    except BadRequest as e:
        current_app.logger.warning(f"Invalid request: {str(e)}")
        return jsonify({
            'status': False,
            'message': 'Invalid request data'
        }), 400
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Payment processing failed: {str(e)}")
        return jsonify({
            'status': False,
            'message': 'An unexpected error occurred' if not current_app.debug else str(e)
        }), 500