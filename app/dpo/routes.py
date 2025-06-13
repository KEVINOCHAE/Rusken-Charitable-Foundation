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
    """
    Initialize DPO payment transaction
    ---
    [Swagger documentation remains the same]
    """
    # 1. Configuration validation
    required_configs = {
        'DPO_API_URL': str,
        'DPO_COMPANY_TOKEN': str,
        'DPO_SERVICE_TYPE': str,
        'DPO_PAYMENT_PAGE': str
    }
    
    missing_configs = [key for key, _ in required_configs.items() 
                      if not current_app.config.get(key)]
    if missing_configs:
        current_app.logger.error(f"Missing DPO configurations: {missing_configs}")
        return jsonify({
            'status': False,
            'message': 'Payment system temporarily unavailable',
            'error': 'MISSING_CONFIGURATION'
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

        # Validate required fields
        if not email:
            raise ValueError('Email is required')
        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
            raise ValueError('Invalid email format')
            
        if not raw_amount:
            raise ValueError('Amount is required')
        try:
            amount = Decimal(str(raw_amount)).quantize(Decimal('0.01'))
            if amount <= Decimal('0.00'):
                raise ValueError('Amount must be positive')
            if amount > Decimal('1000000.00'):
                raise ValueError('Amount exceeds maximum limit')
        except (InvalidOperation, ValueError) as e:
            raise ValueError('Invalid amount format') from e

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

        # 4. Prepare DPO request payload
        payload = {
            "CompanyToken": current_app.config["DPO_COMPANY_TOKEN"],
            "Request": "createToken",
            "Transaction": {
                "PaymentAmount": format(amount, '.2f'),
                "PaymentCurrency": "KES",
                "CompanyRef": f"DONATION_{donation.id}",
                "CustomerEmail": email,
                "CustomerFirstName": donor_name.split()[0] if donor_name else "",
                "CustomerLastName": " ".join(donor_name.split()[1:]) if donor_name else "",
                "ServiceType": current_app.config["DPO_SERVICE_TYPE"],
                "RedirectURL": url_for('donate.payment_callback', _external=True),
                "BackURL": url_for('donate.payment_cancel', _external=True),
               
                "CompanyFields": [
                    {"key": "donation_id", "value": str(donation.id)},
                    {"key": "donor_email", "value": email},
                    {"key": "program_id", "value": str(program_id) if program_id else ""}
                ]
            }
        }

        # 5. Call DPO API with enhanced response handling
        max_retries = 3
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                if current_app.config.get('DPO_TEST_MODE'):
                    current_app.logger.info("DPO TEST MODE: Bypassing actual payment")
                    donation.gateway_reference = f"TEST_{donation.id}"
                    donation.payment_gateway = 'dpo_test'
                    db.session.commit()
                    return jsonify({
                        'status': True,
                        'authorization_url': url_for('donate.test_payment', _external=True),
                        'reference': donation.gateway_reference
                    }), 200

                session = requests.Session()
                if current_app.config.get('DPO_DIRECT_CONNECT'):
                    session.trust_env = False

                resp = session.post(
                    current_app.config["DPO_API_URL"],
                    json=payload,
                    headers={
                        'Content-Type': 'application/json',
                        'Accept': 'application/json, application/xml',
                        'User-Agent': 'DPO-API-Client/1.0'
                    },
                    timeout=(3.05, 15)
                )

                current_app.logger.debug(f"DPO API Response [{resp.status_code}]: {resp.text[:200]}...")

                # Handle response format
                content_type = resp.headers.get('Content-Type', '').lower()
                if resp.status_code == 403 and 'cloudfront' in resp.text.lower():
                    raise ValueError("Payment service blocked by security rules")

                resp.raise_for_status()

                # Parse XML or JSON response
                if 'xml' in content_type:
                    try:
                        root = ET.fromstring(resp.text)
                        result = {
                            'Result': root.find('Result').text if root.find('Result') is not None else None,
                            'ResultExplanation': root.find('ResultExplanation').text if root.find('ResultExplanation') is not None else None,
                            'TransToken': root.find('TransToken').text if root.find('TransToken') is not None else None
                        }
                    except ET.ParseError as xml_err:
                        raise ValueError(f"Invalid XML response: {str(xml_err)}")
                else:
                    try:
                        result = resp.json()
                    except ValueError as json_err:
                        raise ValueError(f"Invalid JSON response: {str(json_err)}")

                # Validate DPO response
                if not isinstance(result, dict):
                    raise ValueError("Invalid API response format")

                if result.get('Result') != "000":
                    error_msg = result.get('ResultExplanation', 'Payment failed with unknown error')
                    error_code = result.get('Result', 'UNKNOWN')
                    raise ValueError(f"[{error_code}] {error_msg}")

                if not result.get('TransToken'):
                    raise ValueError("Missing transaction token in API response")

                # Save successful transaction
                donation.gateway_reference = result['TransToken']
                donation.payment_gateway = 'dpo'
                db.session.commit()

                return jsonify({
                    'status': True,
                    'authorization_url': f"{current_app.config['DPO_PAYMENT_PAGE']}?ID={result['TransToken']}",
                    'reference': result['TransToken'],
                    'expires_at': (datetime.utcnow() + timedelta(minutes=30)).isoformat()
                }), 200

            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
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
        
    except BadRequest as e:
        current_app.logger.warning(f"Invalid request: {str(e)}")
        return jsonify({
            'status': False,
            'message': 'Invalid request data',
            'error': 'BAD_REQUEST'
        }), 400
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Payment processing failed: {str(e)}")
        return jsonify({
            'status': False,
            'message': str(e) if current_app.debug else 'Payment processing failed',
            'error': 'SERVER_ERROR'
        }), 500
        