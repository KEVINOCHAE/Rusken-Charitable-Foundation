from flask import (
    Blueprint, render_template, request, flash, redirect, url_for, current_app, abort, jsonify
)
from flask_login import current_user, login_required
from decimal import Decimal, InvalidOperation
from sqlalchemy import func
from datetime import datetime
import requests
import logging
from paystackapi.transaction import Transaction
from app.admin.models import Program
from .forms import DonationForm
# Blueprint
donate_bp = Blueprint('donate', __name__)
logger = logging.getLogger(__name__)

# Custom Exceptions
class PaymentVerificationError(Exception):
    pass

class PaymentInitializationError(Exception):
    pass

# Initialize payment
@donate_bp.route('/initialize-payment', methods=['POST'])
def initialize_payment():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request data'}), 400

    amount = data.get('amount')
    email = data.get('email')
    program_id = data.get('program_id')  # Optional
    donor_name = data.get('donor_name')
    callback_url = data.get('callback_url')

    # Basic validation
    if not all([amount, email]):
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        # Validate amount
        amount_decimal = Decimal(str(amount)).quantize(Decimal('0.01'))
        if amount_decimal <= 0:
            return jsonify({'error': 'Amount must be positive'}), 400

        # Create donation record
        donation = Donation(
            program_id=program_id,
            user_id=current_user.id if current_user.is_authenticated else "",
            donor_name=donor_name,
            donor_email=email,
            amount=amount_decimal,
            currency='NGN',  # Default for Paystack
            status='pending',
            created_at=datetime.utcnow()
        )
        db.session.add(donation)
        db.session.flush()  # Get ID without committing

        # Prepare Paystack metadata
        metadata = {
            'donation_id': donation.id,
            'donor_email': email,
            'donor_name': donor_name or (current_user.username if current_user.is_authenticated else 'Anonymous'),
        }
        if program_id:
            metadata['program_id'] = program_id
        if current_user.is_authenticated:
            metadata['user_id'] = current_user.id

        # Initialize Paystack payment
        paystack_data = {
            'email': email,
            'amount': int(amount_decimal * 100),  # Convert to kobo
            'metadata': metadata,
        }
        if callback_url:
            paystack_data['callback_url'] = callback_url

        response = Transaction.initialize(**paystack_data)
        if not response['status']:
            raise PaymentInitializationError(response.get('message', 'Payment initialization failed'))

        # Update donation with transaction reference
        donation.gateway_reference = response['data']['reference']
        donation.payment_gateway = 'paystack'
        db.session.commit()

        return jsonify({
            'authorization_url': response['data']['authorization_url'],
            'reference': response['data']['reference']
        })

    except InvalidOperation:
        db.session.rollback()
        return jsonify({'error': 'Invalid amount format'}), 400
    except PaymentInitializationError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        logger.error(f"Payment initialization error: {str(e)}", exc_info=True)
        return jsonify({'error': 'An error occurred processing your payment'}), 500

# Unified callback handler
@donate_bp.route('/payment-callback')
def payment_callback():
    reference = request.args.get('reference')
    if not reference:
        flash('Invalid transaction reference', 'danger')
        return redirect(url_for('main.home'))

    try:
        # Verify transaction
        transaction = verify_paystack_transaction(reference)
        
        # Check if this is an existing donation
        donation = Donation.query.filter_by(gateway_reference=reference).first()
        
        if not donation:
            # Create new general donation record
            donation = Donation(
                program_id=transaction['metadata'].get('program_id'),
                user_id=transaction['metadata'].get('user_id'),
                donor_name=transaction['metadata'].get('donor_name'),
                donor_email=transaction['email'],
                amount=transaction['amount'],
                currency=transaction['currency'],
                status='completed',
                gateway_reference=reference,
                payment_gateway='paystack',
                gateway_metadata=transaction['metadata'],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.session.add(donation)
        
        # Update existing donation
        donation.status = 'completed'
        donation.gateway_metadata = transaction['metadata']
        donation.updated_at = datetime.utcnow()
        
        # Update program funding if applicable
        if donation.program_id and donation.status == 'completed':
            donation.program.current_funding += donation.amount
            send_program_notification(donation.program, donation)
        
        db.session.commit()
        
        # Send confirmation
        send_donation_confirmation(donation)
        
        if current_user.is_authenticated:
            return redirect(url_for('donate.confirmation', donation_id=donation.id))
        return render_template('donate/guest_confirmation.html', donation=donation)

    except PaymentVerificationError as e:
        logger.error(f"Payment verification failed: {str(e)}", exc_info=True)
        flash('Payment verification failed. Please contact support.', 'danger')
    except Exception as e:
        logger.error(f"Callback processing error: {str(e)}", exc_info=True)
        flash('An error occurred processing your payment', 'danger')
    
    return redirect(url_for('main.home'))

# Enhanced verification
def verify_paystack_transaction(reference):
    try:
        response = Transaction.verify(reference=reference)
        if not response['status'] or response['data']['status'] != 'success':
            raise PaymentVerificationError("Payment not successful")

        data = response['data']
        return {
            'reference': data['reference'],
            'amount': Decimal(data['amount']) / 100,
            'currency': data['currency'],
            'email': data['customer']['email'],
            'metadata': data.get('metadata', {}),
            'status': data['status']
        }
    except Exception as e:
        logger.error(f"Paystack verification error: {str(e)}")
        raise PaymentVerificationError("Could not verify payment")

# Helper functions
def send_donation_confirmation(donation):
    #  email sending logic here
    pass

def send_program_notification(program, donation):
    #  program-specific notifications
    pass


@donate_bp.route('/donate', methods=['GET'])
def donate():
    program_id = request.args.get('program_id', type=int)
    if not program_id:
        flash('Invalid program selected', 'danger')
        return redirect(url_for('main.home'))

    program = Program.query.get_or_404(program_id)
    form = DonationForm()
    
    if current_user.is_authenticated:
        form.donor_name.data = current_user.username
        form.donor_email.data = current_user.email

    return render_template('donate/donate.html',
        program=program,
        form=form,
        paystack_public_key=current_app.config['PAYSTACK_PUBLIC_KEY'])



