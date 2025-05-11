from flask import (
    Blueprint, render_template, request, flash, redirect, url_for, current_app, abort, jsonify, make_response, send_file 
)

from io import BytesIO
from app.utils.receipts import generate_receipt_pdf
from decimal import Decimal, ROUND_HALF_UP
from app import db
from flask_login import current_user, login_required
from decimal import Decimal, InvalidOperation
from sqlalchemy import func
from datetime import datetime
import requests
from app.utils.emails import send_donation_access_email
from app.utils.tokens import generate_email_token, verify_email_token
import logging
from paystackapi.transaction import Transaction
from app.admin.models import Program,Donation, User
from .forms import DonationForm, FindDonationsForm
# Blueprint
donate_bp = Blueprint('donate', __name__)
logger = logging.getLogger(__name__)

# Custom Exceptions
class PaymentVerificationError(Exception):
    pass

class PaymentInitializationError(Exception):
    pass



@donate_bp.route('/payment-callback')
def payment_callback():
    reference = request.args.get('reference')
    if not reference:
        flash('Invalid transaction reference', 'danger')
        return redirect(url_for('main.home'))

    try:
        # 1. Verify transaction FIRST with Paystack
        transaction = verify_paystack_transaction(reference)
        
        # 2. Find or create donation record
        donation = Donation.query.filter_by(gateway_reference=reference).first()
        is_new_donation = False

        if not donation:
            # Create new record from verified transaction data
            donation = Donation(
                program_id=transaction['metadata'].get('program_id'),
                user_id=transaction['metadata'].get('user_id'),
                donor_name=transaction['metadata'].get('donor_name', 'Anonymous')[:100],
                donor_email=transaction['email'],
                amount=transaction['amount'],
                currency=transaction['currency'],
                status='pending',  # Start as pending
                gateway_reference=reference,
                payment_gateway='paystack',
                gateway_metadata=transaction['metadata'],
                created_at=datetime.utcnow()
            )
            db.session.add(donation)
            is_new_donation = True
        else:
            # Idempotency check for existing donations
            if donation.status == 'completed':
                logger.info(f"Duplicate callback for completed donation: {donation.id}")
                return _handle_redirect(donation)

        # 3. Validate critical fields against potential tampering
        if not is_new_donation:
            if donation.amount != transaction['amount']:
                logger.error(f"Amount mismatch: DB={donation.amount}, Paystack={transaction['amount']}")
                raise PaymentVerificationError("Amount tampering detected")

        # 4. Mark as completed only after successful verification
        donation.status = 'completed'
        donation.updated_at = datetime.utcnow()

        # 5. Final commit of all changes
        db.session.commit()

        # 6. Redirect user (email logic removed)
        return _handle_redirect(donation)

    except PaymentVerificationError as e:
        logger.error(f"Payment verification failed: {str(e)}")
        flash('Payment verification failed. Please contact support.', 'danger')
        if 'donation' in locals():
            db.session.rollback()
    except Exception as e:
        logger.error(f"Callback processing error: {str(e)}", exc_info=True)
        flash('An error occurred processing your payment', 'danger')
        db.session.rollback()
    
    return redirect(url_for('main.home'))

def _handle_redirect(donation):
    if current_user.is_authenticated:
        return redirect(url_for('donate.confirmation', donation_id=donation.id))
    return render_template('donate/guest_confirmation.html', donation=donation)



def verify_paystack_transaction(reference):
    """
    Verify a Paystack transaction and return sanitized data.
    Throws PaymentVerificationError on failure.
    """
    try:
        # 1. API Request with timeout
        headers = {'Authorization': f'Bearer {current_app.config["PAYSTACK_SECRET_KEY"]}'}
        resp = requests.get(
            f'https://api.paystack.co/transaction/verify/{reference}',
            headers=headers,
            timeout=10  # Add timeout to prevent hanging
        )
        resp.raise_for_status()

        # 2. Validate response structure
        response_data = resp.json()
        if not response_data.get('status'):
            raise PaymentVerificationError("Paystack API returned false status")

        data = response_data.get('data')
        if not data:
            raise PaymentVerificationError("Missing transaction data in response")

        # 3. Check transaction success status
        if data.get('status') != 'success':
            gateway_response = data.get('gateway_response', 'No gateway message')
            raise PaymentVerificationError(f"Transaction failed: {gateway_response}")

        # 4. Validate required fields
        required_fields = ['amount', 'currency', 'customer']
        for field in required_fields:
            if field not in data:
                raise PaymentVerificationError(f"Missing required field: {field}")

        # 5. Safely extract customer email
        customer_email = data['customer'].get('email', '')
        if not customer_email:
            raise PaymentVerificationError("Missing customer email")

        # 6. Currency-safe amount conversion
        amount = Decimal(data['amount']) / 100  # Convert from cents/kobo
        amount = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # 7. Validate currency against app config
        allowed_currencies = current_app.config.get('ALLOWED_CURRENCIES', ['KES'])
        if data['currency'] not in allowed_currencies:
            raise PaymentVerificationError(f"Invalid currency: {data['currency']}")

        return {
            'reference': reference,
            'amount': amount,
            'currency': data['currency'],
            'email': customer_email,
            'metadata': data.get('metadata', {})
        }

    except requests.exceptions.RequestException as e:
        error_msg = f"Paystack API connection failed: {str(e)}"
        current_app.logger.error(error_msg)
        raise PaymentVerificationError("Could not connect to payment gateway")
    except ValueError as e:  # Includes JSONDecodeError
        error_msg = f"Invalid Paystack response: {str(e)}"
        current_app.logger.error(error_msg)
        raise PaymentVerificationError("Invalid payment gateway response")
    except Exception as e:
        error_msg = f"Unexpected verification error: {str(e)}"
        current_app.logger.error(error_msg)
        raise PaymentVerificationError("Payment verification failed")




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


@donate_bp.route('/confirmation/<int:donation_id>')
@login_required
def confirmation(donation_id):
    try:
        # 1. Verify donation belongs to current user
        donation = Donation.query.filter_by(
            id=donation_id,
            user_id=current_user.id
        ).first_or_404()

        # 2. Prepare confirmation data
        confirmation_data = {
            'donation': donation,
            'receipt_url': url_for('donate.download_receipt', donation_id=donation.id),
            'user_donations': Donation.query.filter_by(
                user_id=current_user.id
            ).order_by(Donation.created_at.desc()).limit(5).all(),
            'impact_stats': {
                'total_donated': db.session.query(
                    func.sum(Donation.amount)
                ).filter_by(
                    user_id=current_user.id
                ).scalar() or 0,
                'donation_count': Donation.query.filter_by(
                    user_id=current_user.id
                ).count()
            }
        }

        # 3. Add program details if applicable
        if donation.program_id:
            program = Program.query.get(donation.program_id)
            if program:
                confirmation_data['program'] = program
                confirmation_data['program_url'] = url_for('main.program_detail', slug=program.slug)

        return render_template(
            'donate/authenticated_confirmation.html',
            **confirmation_data
        )

    except Exception as e:
        current_app.logger.error(f"Confirmation error: {str(e)}")
        flash('Error loading donation details', 'danger')
        return redirect(url_for('main.home'))


@donate_bp.route('/receipt/<int:donation_id>')
def download_receipt(donation_id):
    try:
        donation = Donation.query.get_or_404(donation_id)
        
        # For authenticated users
        if current_user.is_authenticated:
            if donation.user_id != current_user.id:
                abort(403)  # Forbidden
            return _generate_receipt_response(donation)
        
        # For unauthenticated users - check token
        token = request.args.get('token')
        if token:
            email = verify_email_token(token)
            if email and email.lower() == donation.donor_email.lower():
                return _generate_receipt_response(donation)
        
        # If neither authenticated nor valid token
        flash('Please verify your email to download receipts', 'warning')
        return redirect(url_for('donate.find_donations'))
        
    except Exception as e:
        current_app.logger.error(f"Receipt download error: {str(e)}")
        flash('Error generating receipt', 'danger')
        return redirect(url_for('main.home'))

def _generate_receipt_response(donation):
    pdf = generate_receipt_pdf(donation)
    return send_file(
        pdf,
        mimetype='application/pdf',
        download_name=f"rusken_receipt_{donation.gateway_reference}.pdf",
        as_attachment=True
    )



@donate_bp.route('/find-donations', methods=['GET', 'POST'])
def find_donations():
    # First check for token in URL (for email verification)
    token = request.args.get('token')
    if token:
        email = verify_email_token(token)
        if not email:
            flash('Invalid or expired verification link', 'danger')
            return redirect(url_for('donate.find_donations'))
        
        # Get only completed donations for verified email
        donations = Donation.query.filter(
            func.lower(Donation.donor_email) == email,
            Donation.status.ilike('completed')  # Case-insensitive filter
        ).order_by(Donation.created_at.desc()).all()

        return render_template('donate/donation_history.html',
                            donations=donations,
                            email=email)

    # Handle form submission for new requests
    form = FindDonationsForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        
        # Check if completed donations exist
        donations_exist = Donation.query.filter(
            func.lower(Donation.donor_email) == email,
            Donation.status.ilike('completed')  # Add status filter here
        ).count() > 0
        
        if donations_exist:
            send_donation_access_email(email)
            flash('We\'ve sent a verification link to your email', 'success')
        else:
            flash('No completed donations found with that email', 'warning')
        
        return redirect(url_for('donate.find_donations'))
    
    return render_template('donate/find_donations.html', form=form)
