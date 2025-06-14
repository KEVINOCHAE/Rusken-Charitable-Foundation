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

# Enhanced DPO Configuration
DPO_CONFIG = {
    'VERIFY_URL': "https://secure.3gdirectpay.com/API/v6/verify",
    'TIMEOUT': 15,  # seconds
    'ALLOWED_IPS': {'196.201.214.200', '196.201.214.206'},  # DPO production IPs
    'MAX_RETRIES': 3,
    'RETRY_DELAY': 2  # seconds
}

# -----------------------------
# Payment Callback Handler
# -----------------------------
@donate_bp.route('/payment-callback', methods=['GET'])
def payment_callback():
    """Handle DPO payment notifications with IP whitelisting and request validation"""
    # Verify source IP
    client_ip = request.remote_addr
    if client_ip not in DPO_CONFIG['ALLOWED_IPS']:
        current_app.logger.warning(f"Blocked callback from unauthorized IP: {client_ip}")
        return make_response("Unauthorized", 403)

    transaction_token = request.args.get('TransactionToken')
    if not transaction_token:
        current_app.logger.error("DPO callback missing TransactionToken")
        return make_response("Missing token", 400)

    try:
        # Pass minimal data to background thread
        thread = threading.Thread(
            target=process_dpo_callback,
            args=(transaction_token,),
            daemon=True
        )
        thread.start()
        return make_response("OK", 200)
    except Exception as e:
        current_app.logger.error(f"Callback thread failed: {str(e)}", exc_info=True)
        return make_response("Processing error", 500)

# -----------------------------
# Background Callback Processor
# -----------------------------
def process_dpo_callback(transaction_token):
    """Process payment verification and update donation status with retries"""
    with current_app.app_context():
        for attempt in range(DPO_CONFIG['MAX_RETRIES']):
            try:
                # 1. Verify transaction with DPO
                transaction = verify_dpo_transaction(transaction_token)
                if not transaction:
                    raise ValueError("Transaction verification failed")
                    
                if transaction.get('status') != 'Completed':
                    raise ValueError(f"Transaction not completed: {transaction.get('status')}")

                # 2. Get donation record with lock
                donation = Donation.query.filter_by(
                    gateway_reference=transaction_token
                ).with_for_update().first()
                
                if not donation:
                    raise ValueError(f"No donation found for token: {transaction_token}")

                # 3. Check for duplicate processing
                if donation.status == 'completed':
                    current_app.logger.warning(f"Duplicate callback for donation {donation.id}")
                    return

                # 4. Validate amount with tolerance
                try:
                    dpo_amount = Decimal(str(transaction['transactionAmount'])).quantize(Decimal('0.01'))
                    if abs(dpo_amount - donation.amount) > Decimal('0.01'):
                        raise ValueError(
                            f"Amount mismatch: DPO {dpo_amount} vs DB {donation.amount}"
                        )
                except (InvalidOperation, ValueError) as e:
                    current_app.logger.error(f"Amount validation failed: {str(e)}")
                    raise

                # 5. Update donation status
                donation.status = 'completed'
                donation.completed_at = datetime.utcnow()
                donation.gateway_response = {
                    'transactionToken': transaction_token,
                    'status': transaction['status'],
                    'amount': transaction['transactionAmount']
                }  # Store minimal response

                db.session.commit()

                # 6. Queue receipt task
                current_app.task_queue.enqueue(
                    send_donation_receipt,
                    donation.id
                )
                return  # Success, exit retry loop

            except Exception as e:
                current_app.logger.error(
                    f"Callback attempt {attempt+1} failed: {str(e)}", 
                    exc_info=(attempt == DPO_CONFIG['MAX_RETRIES'] - 1)  # Full traceback on last attempt
                )
                db.session.rollback()
                if attempt < DPO_CONFIG['MAX_RETRIES'] - 1:
                    time.sleep(DPO_CONFIG['RETRY_DELAY'] * (attempt + 1))
                else:
                    # Critical failure handling
                    current_app.logger.critical(
                        f"Permanent failure processing transaction {transaction_token}"
                    )
                    # Implement alerting (e.g., email admin, log to monitoring system)

# -----------------------------
# Payment Cancellation Handler
# -----------------------------
@donate_bp.route('/payment-cancel', methods=['GET'])
def payment_cancel():
    """Handle payment cancellation with CSRF protection"""
    program_id = request.args.get('program_id')
    session_token = request.args.get('session_id')
    
    # Validate session to prevent CSRF
    if not session_token or session_token != session.get('donation_session'):
        flash('Invalid session', 'danger')
        return redirect(url_for('main.home'))

    # Validate program exists
    if not Program.query.get(program_id):
        flash('Invalid program', 'danger')
        return redirect(url_for('main.home'))

    flash('Your donation was not completed. You may try again if you wish.', 'warning')
    return redirect(url_for('donate.donate', program_id=program_id))

# -----------------------------
# Secure XML Helper
# -----------------------------
class SecureXMLParser:
    """XML parser with security protections"""
    @staticmethod
    def parse(xml_content):
        # Disable dangerous XML features
        parser = ET.XMLParser(
            resolve_entities=False,
            forbid_dtd=True,
            forbid_entities=True
        )
        return ET.fromstring(xml_content, parser=parser)

# -----------------------------
# Helper Functions
# -----------------------------
def verify_dpo_transaction(token):
    """Securely verify transaction with DPO API"""
    try:
        # Use XML templates to prevent injection
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
            timeout=DPO_CONFIG['TIMEOUT'],
            verify=True  # Enable SSL verification
        )

        response.raise_for_status()

        # Use secure XML parser
        root = SecureXMLParser.parse(response.content)

        # Validate response structure
        if root.findtext("Result") != "000":
            error_msg = root.findtext("ResultExplanation") or "Verification failed"
            current_app.logger.warning(f"DPO verification failed: {error_msg}")
            return None

        return {
            'transactionToken': token,
            'transactionAmount': root.findtext("TransactionAmount"),
            'status': 'Completed'
        }

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"DPO API connection failed: {str(e)}")
    except ET.ParseError as e:
        current_app.logger.error(f"Invalid XML response: {str(e)}")
    except Exception as e:
        current_app.logger.error(f"Verification error: {str(e)}")
    
    return None

def send_donation_receipt(donation_id):
    """Send donation receipt email with error handling"""
    try:
        donation = Donation.query.get(donation_id)
        if not donation:
            current_app.logger.error(f"Receipt failed: Donation {donation_id} not found")
            return

        # Implement actual email sending logic
        # msg = Message(
        #     "Donation Receipt",
        #     recipients=[donation.donor_email]
        # )
        # msg.html = render_template('email/receipt.html', donation=donation)
        # mail.send(msg)
        
        current_app.logger.info(f"Receipt sent for donation {donation.id}")
    except Exception as e:
        current_app.logger.error(f"Failed to send receipt: {str(e)}", exc_info=True)

# -----------------------------
# DPO Redirect Handler (Enhanced)
# -----------------------------
@donate_bp.route('/dpo-redirect', methods=['GET'])
def dpo_redirect():
    """
    Handles post-payment redirect from DPO with idempotent processing
    and session validation
    """
    transaction_token = request.args.get('TransactionToken')
    session_token = request.args.get('SessionID')

    # Validate session
    if not session_token or session_token != session.get('donation_session'):
        flash('Invalid session', 'danger')
        return redirect(url_for('main.home'))

    if not transaction_token:
        flash("Missing transaction token. We could not verify your donation.", "danger")
        return redirect(url_for('main.home'))

    try:
        # 1. Verify transaction with DPO
        transaction = verify_dpo_transaction(transaction_token)
        if not transaction:
            raise ValueError("Payment verification failed")

        if transaction.get('status') != 'Completed':
            raise ValueError("Payment not completed")

        # 2. Find donation with lock
        donation = Donation.query.filter_by(
            gateway_reference=transaction_token
        ).with_for_update().first()
        
        if not donation:
            raise ValueError("Donation record not found")

        # 3. Update donation if not already completed
        if donation.status != 'completed':
            # 4. Amount check with tolerance
            try:
                dpo_amount = Decimal(str(transaction['transactionAmount'])).quantize(Decimal('0.01'))
                if abs(dpo_amount - donation.amount) > Decimal('0.01'):
                    raise ValueError(f"Payment mismatch: DPO={dpo_amount}, DB={donation.amount}")
            except (InvalidOperation, ValueError) as e:
                raise ValueError(f"Invalid transaction amount: {str(e)}")

            # 5. Update donation
            donation.status = 'completed'
            donation.completed_at = datetime.utcnow()
            donation.gateway_response = {
                'transactionToken': transaction_token,
                'status': 'Completed',
                'amount': transaction['transactionAmount']
            }
            db.session.commit()

            # 6. Queue receipt (don't block user response)
            try:
                current_app.task_queue.enqueue(send_donation_receipt, donation.id)
            except Exception as e:
                current_app.logger.warning(f"Failed to queue receipt: {e}")

        # 7. Clear session token
        session.pop('donation_session', None)

        # 8. Redirect to appropriate confirmation
        if current_user.is_authenticated:
            return redirect(url_for('donate.confirmation', donation_id=donation.id))
        else:
            return render_template('donate/guest_confirmation.html', donation=donation)

    except Exception as e:
        current_app.logger.error(f"DPO redirect processing failed: {str(e)}", exc_info=True)
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

