from flask import Blueprint, request, jsonify, current_app, url_for
from flask_login import current_user
from paystackapi.paystack import Paystack
from paystackapi.transaction import Transaction
import requests
from app import db
from datetime import datetime
from app import csrf
from paystackapi.paystack import Paystack
from decimal import Decimal
from app.admin.models import Donation

paystack_bp = Blueprint('paystack', __name__)


@paystack_bp.route('/initialize', methods=['POST'])
def initialize_payment():
    data = request.get_json() or {}
    email       = data.get('email')
    raw_amount  = data.get('amount')
    program_id  = data.get('program_id')
    donor_name  = data.get('donor_name') or (
                     current_user.username if current_user.is_authenticated else 'Anonymous'
                 )

    # 1. Validate required fields
    if not email or not raw_amount:
        return jsonify({'status': False, 'message': 'Amount and email are required'}), 400

    # 2. Validate amount format
    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal('0.01'))
        if amount <= 0:
            raise InvalidOperation()
    except InvalidOperation:
        return jsonify({'status': False, 'message': 'Invalid amount format'}), 400

    try:
        # 3. Create pending Donation record
        donation = Donation(
            program_id   = program_id,
            user_id      = current_user.id if current_user.is_authenticated else None,
            donor_name   = donor_name,
            donor_email  = email,
            amount       = amount,
            currency     = 'KES',
            status       = 'pending',
            created_at   = datetime.utcnow()
        )
        db.session.add(donation)
        db.session.flush()  # so donation.id is available

        # 4. Build Paystack metadata & callback
        metadata = {
            'donation_id': donation.id,
            'donor_email': email,
            'donor_name' : donor_name,
            'user_id'    : current_user.get_id() if current_user.is_authenticated else None,
            'program_id' : program_id,
            'general'    : program_id is None
        }
        callback_url = url_for('donate.payment_callback', _external=True)

        # 5. Initialize Paystack payload (KES → cents)
        payload = {
            'email'        : email,
            'amount'       : int(amount * 100),  # KES×100 → cents
            'currency'     : 'KES',
            'metadata'     : metadata,
            'callback_url' : callback_url
        }
        headers = {
            'Authorization': f'Bearer {current_app.config["PAYSTACK_SECRET_KEY"]}',
            'Content-Type' : 'application/json'
        }

        # 6. Call Paystack to initialize
        resp   = requests.post(
            'https://api.paystack.co/transaction/initialize',
            headers=headers,
            json=payload,
            timeout=10
        )
        resp.raise_for_status()
        result = resp.json()

        # 7. Handle initialization failure
        if not result.get('status'):
            db.session.rollback()
            current_app.logger.error(f"Paystack init error: {result}")
            return jsonify({
                'status': False,
                'message': result.get('message', 'Payment initialization failed')
            }), 400

        # 8. Save the reference and commit
        donation.gateway_reference = result['data']['reference']
        donation.payment_gateway  = 'paystack'
        db.session.commit()

        # 9. Return authorization URL for frontend redirect
        return jsonify({
            'status'           : True,
            'authorization_url': result['data']['authorization_url'],
            'reference'        : result['data']['reference']
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error during Paystack initialization: {e}")
        return jsonify({
            'status' : False,
            'message': 'An unexpected error occurred while processing your payment'
        }), 500



"""
@paystack_bp.route('/initialize-general', methods=['POST'])
@csrf.exempt
def initialize_general_donation():
    data = request.get_json()
    
    # Validate required fields
    if not data or 'email' not in data or 'amount' not in data:
        return jsonify({'status': False, 'message': 'Email and amount are required'}), 400

    try:
        # Extract and validate data
        email = data['email'].strip().lower()
        amount = Decimal(str(data['amount']))
        
        if amount <= 0:
            return jsonify({'status': False, 'message': 'Amount must be greater than zero'}), 400
        
        # Prepare metadata from the request
        metadata = {
            'custom_fields': []
        }
        
        # Add name if provided
        if 'name' in data:
            metadata['custom_fields'].append({
                'display_name': 'Full Name',
                'variable_name': 'full_name',
                'value': data['name'].strip()
            })
        
        # Add phone if provided
        if 'phone' in data:
            metadata['custom_fields'].append({
                'display_name': 'Phone Number',
                'variable_name': 'phone_number',
                'value': data['phone'].strip()
            })
        
        # Optional flags
        if 'receipt_requested' in data:
            metadata['receipt_requested'] = data['receipt_requested']
        if 'updates_subscribed' in data:
            metadata['updates_subscribed'] = data['updates_subscribed']
        
        # Add general donation flag
        metadata['general'] = True

        # Prepare Paystack payload
        payload = {
            'email': email,
            'amount': int(amount * 100),  # Use KES directly, converted to cents
            'currency': 'KES',  # Explicitly using Kenyan Shillings
            'metadata': metadata,
            'callback_url': url_for('donate.payment_callback', _external=True)
        }

        headers = {
            'Authorization': f'Bearer {current_app.config["PAYSTACK_SECRET_KEY"]}',
            'Content-Type': 'application/json'
        }

        # Initialize Paystack transaction
        response = requests.post(
            'https://api.paystack.co/transaction/initialize',
            headers=headers,
            json=payload,
            timeout=10
        )

        response_data = response.json()

        if not response.ok:
            current_app.logger.error(f"Paystack init failed: {response.text}")
            return jsonify({
                'status': False,
                'message': response_data.get('message', 'Payment initialization failed')
            }), 400

        return jsonify(response_data)

    except (ValueError, decimal.InvalidOperation):
        return jsonify({'status': False, 'message': 'Invalid amount value'}), 400
    except Exception as e:
        current_app.logger.error(f"Paystack initialization error: {str(e)}")
        return jsonify({'status': False, 'message': 'An error occurred while processing your payment'}), 500
"""