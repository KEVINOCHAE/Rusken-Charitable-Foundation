from flask import Blueprint, request, jsonify, current_app, url_for
from flask_login import current_user
import requests
from app import db
from datetime import datetime
from app import csrf
from decimal import Decimal
from app.admin.models import Donation, Program
from werkzeug.exceptions import BadRequest
import re

dpo_bp = Blueprint('dpo', __name__)


@dpo_bp.route('/initialize', methods=['POST'])
def initialize_payment():
    # 0. Validate configuration first
    required_configs = ['DPO_API_URL', 'DPO_COMPANY_TOKEN', 'DPO_SERVICE_TYPE', 'DPO_PAYMENT_PAGE']
    if any(not current_app.config.get(key) for key in required_configs):
        current_app.logger.error("Missing DPO configuration")
        return jsonify({
            'status': False,
            'message': 'Payment system temporarily unavailable'
        }), 500

    # 1. Parse and validate request
    try:
        data = request.get_json() or {}
        if not data:
            raise BadRequest('Invalid JSON payload')
            
        email = data.get('email', '').strip()
        raw_amount = data.get('amount')
        program_id = data.get('program_id')
        donor_name = (data.get('donor_name') or '').strip() or (
            current_user.username if current_user.is_authenticated else 'Anonymous'
        )

        # Validate required fields
        if not email:
            return jsonify({'status': False, 'message': 'Email is required'}), 400
            
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({'status': False, 'message': 'Invalid email format'}), 400
            
        if not raw_amount:
            return jsonify({'status': False, 'message': 'Amount is required'}), 400

        # Validate amount
        try:
            amount = Decimal(str(raw_amount)).quantize(Decimal('0.01'))
            if amount <= 0:
                raise InvalidOperation()
        except InvalidOperation:
            return jsonify({'status': False, 'message': 'Amount must be a positive number'}), 400

        # 2. Create donation record
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

        # 3. Prepare DPO request
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

        # 4. Call DPO API with comprehensive error handling
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        current_app.logger.info(f"Initializing DPO payment for donation {donation.id}")
        
        try:
            # Test mode bypass
            if current_app.config.get('DPO_TEST_MODE'):
                donation.gateway_reference = f"TEST_{donation.id}"
                donation.payment_gateway = 'dpo_test'
                db.session.commit()
                
                return jsonify({
                    'status': True,
                    'authorization_url': url_for('donate.test_payment', _external=True),
                    'reference': donation.gateway_reference
                }), 200

            resp = requests.post(
                current_app.config["DPO_API_URL"],
                json=payload,
                headers=headers,
                timeout=15  # Slightly longer timeout
            )
            
            # Log raw response for debugging
            current_app.logger.debug(f"DPO API Response: {resp.status_code} - {resp.text}")
            
            try:
                resp.raise_for_status()  # Raises HTTPError for bad responses
                result = resp.json()
            except ValueError as json_err:
                current_app.logger.error(f"Invalid JSON from DPO: {resp.text}")
                raise ValueError("DPO returned invalid response format") from json_err
                
            # Validate response structure
            if not isinstance(result, dict) or 'TransToken' not in result:
                current_app.logger.error(f"Malformed DPO response: {result}")
                raise ValueError("Invalid response structure from DPO")
                
            # Check DPO result code
            if result.get("Result") != "000":
                error_msg = result.get("ResultExplanation", "Payment initialization failed")
                current_app.logger.error(f"DPO Error: {error_msg}")
                raise ValueError(error_msg)

            # 5. Save successful transaction
            donation.gateway_reference = result['TransToken']
            donation.payment_gateway = 'dpo'
            db.session.commit()

            return jsonify({
                'status': True,
                'authorization_url': f"{current_app.config['DPO_PAYMENT_PAGE']}?ID={result['TransToken']}",
                'reference': result['TransToken']
            }), 200

        except requests.exceptions.RequestException as req_err:
            current_app.logger.error(f"DPO Connection Error: {str(req_err)}")
            raise ValueError("Payment service unavailable. Please try again later.") from req_err

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
        current_app.logger.exception("Payment processing failed")
        return jsonify({
            'status': False,
            'message': 'An unexpected error occurred' if not current_app.debug else str(e)
        }), 500



        