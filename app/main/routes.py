from flask import Blueprint, render_template, redirect, url_for, flash, request, session, request, current_app
from flask import jsonify
from app.admin.models import  ContactMessage,Program,Category, User, Donation
from app.auth.forms import ChangePasswordForm, UpdateProfileForm
from sqlalchemy import func
from app.main.forms import  ContactForm
from werkzeug.exceptions import abort
from sqlalchemy.exc import SQLAlchemyError
from functools import wraps
from app import db, mail, csrf
from sqlalchemy.orm import joinedload
from flask_login import login_required, login_user, logout_user, current_user
from datetime import datetime
from app.utils.receipts import generate_receipt_pdf
import re

# Create a blueprint for main routes
main_bp = Blueprint('main', __name__)


def login_required_with_message(view):
    """Custom decorator that requires user login with a flash message."""
    @wraps(view)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this feature.', 'warning')
            return redirect(url_for('auth.login')) 
        return view(*args, **kwargs)
    return decorated_view


# ---------------------------------------
# Home Route
# ---------------------------------------


@main_bp.route('/')
def home():
    # Fetch 4 most recent or featured programs (adjust filter as needed)
    featured_programs = (
        Program.query
        .order_by(Program.created_at.desc())
        .limit(6)
        .all()
    )
    return render_template('main/home.html', featured_programs=featured_programs)

@main_bp.route('/dashboard')
@login_required
def dashboard():
    user = current_user

    # Referral link and stats
    referral_link = user.get_referral_link()
    referral_count = User.query.filter_by(invited_by_id=user.id).count()

    # Fetch only completed donations
    donations = Donation.query.filter_by(user_id=user.id, status='completed')\
        .order_by(Donation.created_at.desc()).all()

    # Calculate total donated (only completed)
    total_donated = db.session.query(func.sum(Donation.amount))\
        .filter_by(user_id=user.id, status='completed').scalar() or 0.00

    return render_template(
        'main/dashboard.html',
        user=user,
        referral_count=referral_count,
        referral_link=referral_link,
        donations=donations,
        total_donated=total_donated,
        current_year=datetime.now().year
    )

@main_bp.route('/about', methods=['GET', 'POST'])
def about():
    return render_template('main/about.html', current_year=datetime.now().year)

@main_bp.route('/donate-details', methods=['GET', 'POST'])
def donate_details():
    return render_template('main/donate_details.html', current_year=datetime.now().year)

@main_bp.route('/terms-of-service', methods=['GET', 'POST'])
def terms_of_service():
    return render_template('main/terms.html', current_year=datetime.now().year)



@main_bp.route('/donation-history-fragment')
@login_required
def donation_history_fragment():
    donations = Donation.query.filter_by(user_id=current_user.id).order_by(Donation.created_at.desc()).all()
    return render_template('partials/_donation_history_table.html', donations=donations)

@main_bp.route('/profile-fragment')
@login_required
def profile_fragment():
    user = current_user
    referral_link = user.get_referral_link()
    return render_template('partials/_profile_fragment.html', user=user, referral_link=referral_link)


@main_bp.route('/change-password-fragment')
def change_password_fragment():
    form = ChangePasswordForm()
    return render_template('partials/_change_password_fragment.html', form=form)


@main_bp.route('/support-fragment')
def support_fragment():
    support_data = {
        "phone": "+254 757 734 064",
        "email": "ruskencf2024@gmail.com",
        "hours": "9AM - 5PM EAT, Mon-Fri",
        "response_time": "Typically within 24 hours",
        "contact_page": url_for('main.contact')  
    }
    return render_template('partials/support_fragment.html', **support_data)

@main_bp.route('/edit-profile-fragment')
@login_required
def edit_profile_fragment():
    form = UpdateProfileForm(obj=current_user) 
    referral_link = current_user.get_referral_link()
    return render_template('partials/edit_profile_fragment.html', form=form, user=current_user, referral_link=referral_link)


@main_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    form = ContactForm()
    if form.validate_on_submit():
        # Save contact message to the database
        contact_message = ContactMessage(
            name=form.name.data,
            email=form.email.data,
            subject=form.subject.data,
            message=form.message.data
        )
        db.session.add(contact_message)
        db.session.commit()
        
        # Flash message for success
        flash('Your message has been sent. We will get back to you shortly.', 'success')
        return redirect(url_for('main.contact'))
    
    return render_template('main/contact.html', title='Contact Us', form=form, current_year=datetime.now().year)

@main_bp.route('/privacy-policy')
def privacy_policy():
    return render_template('main/privacy_policies.html', current_year=datetime.now().year)



@main_bp.route('/categories')
def list_categories():
    categories = Category.query.order_by(Category.name.asc()).all()
    category_list = [{'id': c.id, 'name': c.name, 'slug': c.slug} for c in categories]
    return jsonify(category_list)

@main_bp.route('/programs/category/<string:category_slug>')
def programs_by_category(category_slug):
    # 1. Look up the category or 404
    category = Category.query.filter_by(slug=category_slug).first_or_404()

    # 2. Paginate the programs in this category
    page = request.args.get('page', 1, type=int)
    per_page = 9
    programs = (
        Program.query
               .options(
                   joinedload(Program.category),
                   joinedload(Program.author)
               )
               .filter_by(category_id=category.id)
               .order_by(Program.created_at.desc())
               .paginate(page=page, per_page=per_page)
    )

    # 3. Render with both `programs` and `category` in context
    return render_template(
        'programs/our_programs.html',
        programs=programs,
        category=category
    )


@main_bp.route('/programs')
def all_programs():
    page     = request.args.get('page', 1, type=int)
    per_page = 6

    # Only eager‑load the non‑dynamic relationships
    programs = Program.query.options(
        joinedload(Program.category),
        joinedload(Program.author)
    ) \
    .order_by(Program.created_at.desc()) \
    .paginate(page=page, per_page=per_page)
  
    # Renders 'templates/programs/all_programs.html'
    return render_template('programs/our_programs.html', programs=programs)

@main_bp.route('/programs/<slug>')
def program_detail(slug):
    program = Program.query.filter_by(slug=slug).first_or_404()

    total_donated     = sum(d.amount for d in program.donations)
    remaining_budget  = program.annual_budget - total_donated

    return render_template(
      'programs/program_detail.html',
      program=program,
      total_donated=total_donated,
      remaining_budget=remaining_budget
    )

