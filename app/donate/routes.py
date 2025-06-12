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



@donate_bp.route('/payment-callback', methods=['GET'])
def payment_callback():
    transaction_token = request.args.get('TransactionToken')
    
    # Immediately return 200 OK to acknowledge receipt
    response = make_response("OK", 200)
    
    if not transaction_token:
        current_app.logger.error("DPO callback missing TransactionToken")
        return response  # Still return 200 to prevent DPO retries

    # Process the transaction asynchronously
    try:
        # Use a task queue or thread for production
        from threading import Thread
        Thread(target=process_dpo_callback, args=(transaction_token,)).start()
    except Exception as e:
        current_app.logger.error(f"Failed to process callback: {str(e)}")

    return response


def process_dpo_callback(transaction_token):
    """Process the DPO callback in the background"""
    with current_app.app_context():
        try:
            # 1. Verify transaction with DPO
            transaction = verify_dpo_transaction(transaction_token)
            
            # 2. Lookup donation
            donation = Donation.query.filter_by(gateway_reference=transaction_token).first()
            if not donation:
                current_app.logger.error(f"No donation for token: {transaction_token}")
                return

            # 3. Check if already processed
            if donation.status == 'completed':
                current_app.logger.info(f"Duplicate callback for donation {donation.id}")
                return

            # 4. Validate amount
            dpo_amount = Decimal(str(transaction['transactionAmount'])).quantize(Decimal('0.01'))
            if dpo_amount != donation.amount:
                current_app.logger.error(f"Amount mismatch for donation {donation.id}")
                raise PaymentVerificationError("Amount verification failed")

            # 5. Update donation
            donation.status = 'completed'
            donation.completed_at = datetime.utcnow()
            donation.gateway_response = transaction
            db.session.commit()

            # 6. Send receipt
            try:
                send_donation_receipt(donation)
            except Exception as e:
                current_app.logger.error(f"Receipt failed for {donation.id}: {str(e)}")

            # Store in session for the redirect handler
            from flask import session
            session[f'donation_{donation.id}_processed'] = True

        except Exception as e:
            current_app.logger.error(f"Callback processing failed: {str(e)}")
            db.session.rollback()


@donate_bp.route('/payment-complete', methods=['GET'])
def payment_complete():
    """Handle user redirect after processing"""
    donation_id = request.args.get('donation_id')
    
    if not donation_id:
        flash('Invalid completion request', 'danger')
        return redirect(url_for('main.home'))

    # Check if processing is done
    from flask import session
    if session.get(f'donation_{donation_id}_processed'):
        session.pop(f'donation_{donation_id}_processed', None)
        flash('Thank you for your donation!', 'success')
        return redirect(url_for('donate.thank_you'))
    
    # If not processed yet, show waiting page with auto-refresh
    return """
    <html>
    <head>
        <meta http-equiv="refresh" content="3">
        <title>Processing Your Donation</title>
    </head>
    <body>
        <h1>Processing your donation...</h1>
        <p>This page will refresh automatically. Please wait.</p>
    </body>
    </html>
    """

@donate_bp.route('/payment-cancel', methods=['GET'])
def payment_cancel():
    flash('Your donation was cancelled. You can try again anytime.', 'warning')
    return redirect(url_for('donate.donate', program_id=request.args.get('program_id')))
    

@donate_bp.route('/donate', methods=['GET'])
def donate():
    program_id = request.args.get('program_id', type=int)
    if not program_id:
        flash('Invalid program selected', 'danger')
        return redirect(url_for('main.home'))

    program = Program.query.get_or_404(program_id)
    form = DonationForm()
    
    # Pre-fill donor info if logged in
    if current_user.is_authenticated:
        form.donor_name.data = current_user.username
        form.donor_email.data = current_user.email

    return render_template(
        'donate/donate.html',
        program=program,
        form=form,
        currency_symbol=current_app.config.get("CURRENCY_SYMBOL", "$")  # Optional
    )




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
