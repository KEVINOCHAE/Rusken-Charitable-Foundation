from flask import (
    Blueprint, render_template, request, flash, redirect, url_for, current_app, abort, jsonify
)
from app import db
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

        # Update program funding: no direct column update, just handle it dynamically using total_donated
        if donation.program_id and donation.status == 'completed':
            # Send program notification (can now use donation.program.total_donated dynamically)
            send_program_notification(donation.program, donation)
        
        db.session.commit()
        
        # Send confirmation
        send_donation_confirmation(donation)
        
        # Redirect to confirmation page for authenticated users
        if current_user.is_authenticated:
            return redirect(url_for('donate.confirmation', donation_id=donation.id))
        
        # Return a guest confirmation page if the user is not authenticated
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

        logger.info(f"Full Paystack Response: {response}")  # 🔍 Add this line

        if not response['status']:
            raise PaymentVerificationError("Payment not successful")

        data = response['data']

        if data['status'] != 'success':
            logger.error(f"Transaction not successful. Status: {data['status']}, Gateway message: {data.get('gateway_response')}")
            raise PaymentVerificationError("Payment not successful")

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
    #  program-specific notifications here
    # You can use program.total_donated and program.budget_remaining for dynamic updates
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



