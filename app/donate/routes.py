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
import threading
import requests
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape


# Blueprint
donate_bp = Blueprint('donate', __name__)
logger = logging.getLogger(__name__)

# DPO Configuration
DPO_CONFIG = {
    
    'VERIFY_URL': "https://secure.3gdirectpay.com/API/v6/verify",
    'TIMEOUT': 15  # seconds
}

# -----------------------------
# Payment Callback Handler
# -----------------------------
@donate_bp.route('/payment-callback', methods=['GET'])
def payment_callback():
    """Handle DPO payment notifications"""
    transaction_token = request.args.get('TransactionToken')
    response = make_response("OK", 200)

    if not transaction_token:
        current_app.logger.error("DPO callback missing TransactionToken")
        return response

    try:
        # Start background processing with proper app context
        app = current_app._get_current_object()
        thread = threading.Thread(
            target=process_dpo_callback,
            args=(app, transaction_token),
            daemon=True
        )
        thread.start()
    except Exception as e:
        current_app.logger.error(f"Failed to start callback processing: {str(e)}", exc_info=True)

    return response

# -----------------------------
# Background Callback Processor
# -----------------------------
def process_dpo_callback(app, transaction_token):
    """Process payment verification and update donation status"""
    with app.app_context():
        try:
            # 1. Verify transaction with DPO
            transaction = verify_dpo_transaction(transaction_token)
            if not transaction or transaction.get('status') != 'Completed':
                raise ValueError("Transaction verification failed")

            # 2. Get donation record
            donation = Donation.query.filter_by(gateway_reference=transaction_token).first()
            if not donation:
                raise ValueError(f"No donation found for token: {transaction_token}")

            # 3. Check for duplicate processing
            if donation.status == 'completed':
                current_app.logger.info(f"Duplicate callback for donation {donation.id}")
                return

            # 4. Validate amount
            try:
                dpo_amount = Decimal(str(transaction['transactionAmount'])).quantize(Decimal('0.01'))
                if dpo_amount != donation.amount:
                    raise ValueError(f"Amount mismatch: DPO {dpo_amount} vs DB {donation.amount}")
            except (InvalidOperation, ValueError) as e:
                raise ValueError(f"Invalid transaction amount: {str(e)}")

            # 5. Update donation status
            donation.status = 'completed'
            donation.completed_at = datetime.utcnow()
            donation.gateway_response = transaction
            db.session.commit()

            # 6. Send receipt asynchronously
            try:
                threading.Thread(
                    target=send_donation_receipt,
                    args=(app, donation),
                    daemon=True
                ).start()
            except Exception as e:
                current_app.logger.error(f"Failed to queue receipt: {str(e)}")

        except Exception as e:
            current_app.logger.error(f"Callback processing failed: {str(e)}", exc_info=True)
            db.session.rollback()
            raise


# -----------------------------
# Payment Cancellation Handler
# -----------------------------
@donate_bp.route('/payment-cancel', methods=['GET'])
def payment_cancel():
    """Handle payment cancellation"""
    program_id = request.args.get('program_id')
    flash('Your donation was not completed. You may try again if you wish.', 'warning')
    return redirect(url_for('donate.donate', program_id=program_id))

# -----------------------------
# Helper Functions
# -----------------------------
def verify_dpo_transaction(token):
    """Verify transaction with DPO API"""
    try:
        payload = f"""<?xml version="1.0" encoding="utf-8"?>
<API3G>
  <CompanyToken>{escape(current_app.config['DPO_COMPANY_TOKEN'])}</CompanyToken>
  <Request>verifyToken</Request>
  <TransactionToken>{escape(token)}</TransactionToken>
</API3G>"""

        response = requests.post(
            DPO_CONFIG['VERIFY_URL'],
            data=payload,
            headers={'Content-Type': 'application/xml'},
            timeout=DPO_CONFIG['TIMEOUT']
        )

        if response.status_code != 200:
            raise ValueError(f"DPO API returned {response.status_code}")

        root = ET.fromstring(response.content)
        if root.findtext("Result") != "000":
            raise ValueError(root.findtext("ResultExplanation") or "Verification failed")

        return {
            'transactionToken': token,
            'transactionAmount': root.findtext("TransactionAmount"),
            'status': 'Completed',
            'raw_response': response.text
        }

    except Exception as e:
        current_app.logger.error(f"Transaction verification failed: {str(e)}", exc_info=True)
        return None

def send_donation_receipt(app, donation):
    """Send donation receipt email"""
    with app.app_context():
        try:
            # Implement actual email sending logic here
            # Example using Flask-Mail:
            # msg = Message("Donation Receipt",
            #              recipients=[donation.donor_email])
            # msg.body = f"Thank you for your donation of {donation.amount}"
            # mail.send(msg)
            
            current_app.logger.info(f"Receipt sent for donation {donation.id}")
        except Exception as e:
            current_app.logger.error(f"Failed to send receipt: {str(e)}", exc_info=True)


@donate_bp.route('/dpo-redirect', methods=['GET'])
def dpo_redirect():
    """
    Called by DPO after user completes payment.
    Verifies the transaction, updates the donation, then redirects to confirmation.
    """
    transaction_token = request.args.get('TransactionToken')

    if not transaction_token:
        flash("Missing transaction token. We could not verify your donation.", "danger")
        return redirect(url_for('main.home'))

    try:
        # 1. Verify transaction with DPO
        transaction = verify_dpo_transaction(transaction_token)
        if not transaction or transaction.get('status') != 'Completed':
            raise ValueError("Payment not completed")

        # 2. Find donation in DB
        donation = Donation.query.filter_by(gateway_reference=transaction_token).first()
        if not donation:
            raise ValueError("Donation record not found")

        # 3. Prevent duplicate updates
        if donation.status != 'completed':
            # 4. Amount check
            try:
                dpo_amount = Decimal(str(transaction['transactionAmount'])).quantize(Decimal('0.01'))
                if dpo_amount != donation.amount:
                    raise ValueError(f"Payment mismatch: DPO={dpo_amount}, DB={donation.amount}")
            except (InvalidOperation, ValueError) as e:
                raise ValueError(f"Invalid transaction amount: {str(e)}")

            # 5. Update donation
            donation.status = 'completed'
            donation.completed_at = datetime.utcnow()
            donation.gateway_response = transaction
            db.session.commit()

            # 6. Send receipt (background)
            try:
                threading.Thread(
                    target=send_donation_receipt,
                    args=(current_app._get_current_object(), donation),
                    daemon=True
                ).start()
            except Exception as e:
                current_app.logger.warning(f"Failed to queue receipt: {e}")

        # 7. Redirect to appropriate confirmation
        from flask_login import current_user
        if current_user.is_authenticated:
            return redirect(url_for('donate.confirmation', donation_id=donation.id))
        else:
            return render_template('donate/guest_confirmation.html', donation=donation)

    except Exception as e:
        current_app.logger.error(f"DPO redirect verification failed: {str(e)}", exc_info=True)
        flash("There was a problem verifying your donation. Please contact support.", "danger")
        return redirect(url_for('main.home'))


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
        currency_symbol=current_app.config.get("CURRENCY_SYMBOL", "KES")  # Optional
    )



@donate_bp.route('/confirmation/<int:donation_id>')
def confirmation(donation_id):
    try:
        donation = Donation.query.get_or_404(donation_id)

        # If donation is linked to a user, ensure only they can view it
        if donation.user_id and (
            not current_user.is_authenticated or current_user.id != donation.user_id
        ):
            flash("Please log in to view this donation.", "warning")
            return redirect(url_for("auth.login", next=request.url))

        # Shared data for both guest and authenticated confirmation
        confirmation_data = {
            'donation': donation,
            'receipt_url': url_for('donate.download_receipt', donation_id=donation.id)
        }

        if current_user.is_authenticated:
            confirmation_data.update({
                'user_donations': Donation.query.filter_by(
                    user_id=current_user.id
                ).order_by(Donation.created_at.desc()).limit(5).all(),
                'impact_stats': {
                    'total_donated': db.session.query(
                        func.sum(Donation.amount)
                    ).filter_by(user_id=current_user.id).scalar() or 0,
                    'donation_count': Donation.query.filter_by(
                        user_id=current_user.id
                    ).count()
                }
            })

        # Include program if available
        if donation.program_id:
            program = Program.query.get(donation.program_id)
            if program:
                confirmation_data['program'] = program
                confirmation_data['program_url'] = url_for('main.program_detail', slug=program.slug)

        # Render appropriate template
        if current_user.is_authenticated and donation.user_id == current_user.id:
            return render_template("donate/authenticated_confirmation.html", **confirmation_data)
        else:
            return render_template("donate/guest_confirmation.html", **confirmation_data)

    except Exception as e:
        current_app.logger.error(f"Confirmation error: {str(e)}")
        flash("Error loading donation details", "danger")
        return redirect(url_for("main.home"))



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

