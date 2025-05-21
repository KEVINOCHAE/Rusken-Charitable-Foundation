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



@donate_bp.route('/donate', methods=['GET'])
def donate():
    program_id = request.args.get('program_id', type=int)
    if not program_id:
        flash('Invalid program selected', 'danger')
        return redirect(url_for('main.home'))

    program = Program.query.get_or_404(program_id)
    form = DonationForm()

    # Pre-fill for logged-in users
    if current_user.is_authenticated:
        form.donor_name.data  = current_user.username
        form.donor_email.data = current_user.email

    # Calculate how much remains on the program’s budget
    remaining = f"KSH {program.budget_remaining:,.2f}"

    return render_template(
        'donate/donate.html',
        program           = program,
        form              = form,
        remaining         = remaining,
        currency_symbol   = "KSH",
        paypal_client_id  = current_app.config['PAYPAL_LIVE_CLIENT_ID']
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
