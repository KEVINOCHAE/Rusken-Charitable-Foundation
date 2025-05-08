from flask import Blueprint, request, jsonify, current_app, url_for
from flask_login import current_user
from paystackapi.paystack import Paystack
from paystackapi.transaction import Transaction
import requests
from app import csrf
from paystackapi.paystack import Paystack
from decimal import Decimal
from app.admin.models import Donation

paystack_bp = Blueprint('paystack', __name__)

@paystack_bp.route('/initialize', methods=['POST'])
def initialize_payment():
    data = request.get_json() or {}
    email = data.get('email')
    raw_amount = data.get('amount')
    program_id = data.get('program_id')
    donor_name = data.get('donor_name')

    # 4.1 Validate inputs
    if not email or not raw_amount:
        return jsonify({'status': False, 'message': 'Amount and email are required'}), 400
    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal('0.01'))
        if amount <= 0:
            raise InvalidOperation()
    except InvalidOperation:
        return jsonify({'status': False, 'message': 'Invalid amount format'}), 400

    # 4.2 Build metadata and callback
    metadata = {
        'program_id': program_id,
        'donor_email': email,
        'donor_name': donor_name or (current_user.username if current_user.is_authenticated else None),
        'user_id': current_user.get_id() if current_user.is_authenticated else None,
        'general': program_id is None
    }
    callback = url_for('donate.payment_callback', _external=True)

    # 4.3 Call Paystack
    headers = {
        'Authorization': f'Bearer {current_app.config["PAYSTACK_SECRET_KEY"]}',
        'Content-Type': 'application/json'
    }
    payload = {
        'email': email,
        'amount': int(amount * 100),
        'metadata': metadata,
        'callback_url': callback
    }

    try:
        resp = requests.post(
            'https://api.paystack.co/transaction/initialize',
            headers=headers, json=payload, timeout=10
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError:
        body = getattr(resp, 'text', '<no body>')
        current_app.logger.error(f"Paystack init HTTP {resp.status_code}: {body}")
        return jsonify({'status': False, 'message': 'Payment gateway error'}), 502
    except Exception:
        current_app.logger.exception("Error initializing Paystack payment")
        return jsonify({'status': False, 'message': 'Internal server error'}), 500

    result = resp.json()

    # 4.4 Validate Paystack’s own status/message
    if not result.get('status'):
        current_app.logger.error(f"Paystack returned failure: {result!r}")
        return jsonify({
            'status': False,
            'message': result.get('message', 'Initialization failed')
        }), 400

    auth_url = result.get('data', {}).get('authorization_url')
    ref     = result.get('data', {}).get('reference')
    if not auth_url or not ref:
        current_app.logger.error(f"Missing fields in Paystack payload: {result!r}")
        return jsonify({'status': False, 'message': 'Invalid payment gateway response'}), 502

    return jsonify({
        'status': True,
        'authorization_url': auth_url,
        'reference': ref
    }), 200




@paystack_bp.route('/verify/<reference>', methods=['GET'])
def verify(reference):
    paystack = current_app.extensions['paystack']
    try:
        result = paystack.transaction.verify(reference=reference)
    except requests.exceptions.HTTPError as err:
        return jsonify(status=False, message=str(err)), 502

    if result.get('status') is True and result['data']['status'] == 'success':
        # Extract data from Paystack response
        data = result['data']
        amount = Decimal(data['amount']) / 100  # Convert from kobo to naira
        donor_name = data.get('customer', {}).get('name', 'Guest')
        donor_email = data.get('customer', {}).get('email', '')
        program_id = data.get('metadata', {}).get('program_id', None)  # Optional

        # Save donation to the database
        donation = Donation(
            amount=amount,
            donor_name=donor_name,
            donor_email=donor_email,
            program_id=program_id,
            is_recurring=False,  
           
            created_at=datetime.utcnow()
        )

        db.session.add(donation)
        db.session.commit()

        current_app.logger.info(f"Payment verified for donation {donation.id} of amount {amount}")

        return jsonify(status=True, message="Payment verified", data=result), 200

    return jsonify(status=False, message="Payment verification failed"), 400




@paystack_bp.route('/initialize-general', methods=['POST'])
@csrf.exempt
def initialize_general_donation():
    data = request.get_json()
    
    # Validate required fields
    if not data or 'email' not in data or 'amount' not in data:
        return jsonify({'status': False, 'message': 'Email and amount are required'}), 400

    try:
        # Extract and validate data
        email = data['email']
        amount = Decimal(str(data['amount']))
        
        # Convert amount to kobo (Paystack uses amounts in kobo)
        amount_in_kobo = int(amount * 100)
        
        # Prepare metadata from the request
        metadata = {
            'custom_fields': []
        }
        
        # Add name if provided
        if 'name' in data:
            metadata['custom_fields'].append({
                'display_name': 'Full Name',
                'variable_name': 'full_name',
                'value': data['name']
            })
        
        # Add phone if provided
        if 'phone' in data:
            metadata['custom_fields'].append({
                'display_name': 'Phone Number',
                'variable_name': 'phone_number',
                'value': data['phone']
            })
        
        # Add receipt preference if provided
        if 'receipt_requested' in data:
            metadata['receipt_requested'] = data['receipt_requested']
        
        # Add updates preference if provided
        if 'updates_subscribed' in data:
            metadata['updates_subscribed'] = data['updates_subscribed']
        
        # Add general donation flag
        metadata['general'] = True

        # Prepare Paystack payload
        payload = {
            'email': email,
            'amount': amount_in_kobo,
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
            return jsonify({
                'status': False,
                'message': response_data.get('message', 'Payment initialization failed')
            }), 400
        
        return jsonify(response_data)
        
    except ValueError as e:
        return jsonify({'status': False, 'message': 'Invalid amount value'}), 400
    except Exception as e:
        current_app.logger.error(f"Paystack initialization error: {str(e)}")
        return jsonify({'status': False, 'message': 'An error occurred while processing your payment'}), 500