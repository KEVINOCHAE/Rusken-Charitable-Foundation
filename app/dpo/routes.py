from flask import Blueprint, request, jsonify, current_app, url_for
from flask_login import current_user
import requests
from app import db
from app import csrf
from app.admin.models import Donation, Program
import re
import time
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from flask import jsonify, request, current_app, url_for
from werkzeug.exceptions import BadRequest


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

    # 1. Validate required fields
    if not email or not raw_amount:
        return jsonify({'status': False, 'message': 'Amount and email are required'}), 400

    # 2. Validate amount
    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal('0.01'))
        if amount <= 0:
            raise InvalidOperation()
    except InvalidOperation:
        return jsonify({'status': False, 'message': 'Invalid amount format'}), 400

    try:
        # 3. Create pending donation
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
    <PaymentAmount>{amount}</PaymentAmount>
    <PaymentCurrency>KES</PaymentCurrency>
    <CompanyRef>DONATION_{donation.id}</CompanyRef>
    <CustomerEmail>{email}</CustomerEmail>
    <CustomerFirstName>{donor_name.split()[0]}</CustomerFirstName>
    <CustomerLastName>{" ".join(donor_name.split()[1:])}</CustomerLastName>
    <RedirectURL>{url_for('donate.payment_callback', _external=True)}</RedirectURL>
    <BackURL>{url_for('donate.payment_cancel', _external=True)}</BackURL>
    <ServiceType>{current_app.config["DPO_SERVICE_TYPE"]}</ServiceType>
  </Transaction>
</API3G>"""

        headers = {
            "Content-Type": "application/xml",
            "User-Agent": "FlaskDPOClient/1.0"
        }

        # 5. Send request to DPO
        resp = requests.post(current_app.config["DPO_API_URL"], data=payload_xml, headers=headers, timeout=15)
        current_app.logger.info(f"DPO Raw Response: {resp.status_code} - {resp.text}")

        if resp.status_code != 200:
            raise Exception(f"DPO returned status {resp.status_code}")

        # 6. Parse XML response
        tree = ET.fromstring(resp.content)
        result_code = tree.findtext("Result")
        result_explanation = tree.findtext("ResultExplanation")

        if result_code != "000":
            db.session.rollback()
            current_app.logger.error(f"DPO init failed: {result_explanation}")
            return jsonify({
                'status': False,
                'message': result_explanation or "DPO initialization failed"
            }), 400

        trans_token = tree.findtext("TransToken")
        if not trans_token:
            raise Exception("DPO did not return a transaction token")

        # 7. Save token and commit
        donation.gateway_reference = trans_token
        donation.payment_gateway = 'dpo'
        db.session.commit()

        # 8. Return payment URL
        return jsonify({
            'status': True,
            'authorization_url': f"{current_app.config['DPO_PAYMENT_PAGE']}?ID={trans_token}",
            'reference': trans_token
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error during DPO initialization: {e}")
        return jsonify({
            'status': False,
            'message': 'An error occurred while initializing your payment'
        }), 500