from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask import jsonify
from app.admin.models import  ContactMessage,Program,Category
from app.main.forms import  ContactForm
from werkzeug.exceptions import abort
from sqlalchemy.exc import SQLAlchemyError
from functools import wraps
from app import db, mail, csrf
from flask import current_app
from sqlalchemy.orm import joinedload
from flask_login import login_required, login_user, logout_user, current_user
from datetime import datetime
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
    # Fetch user details
    user = User.query.filter_by(id=current_user.id).first()

    # Fetch referral stats
    referral_count = User.query.filter_by(invited_by_id=user.id).count()

    
    return render_template('dashboard.html', user=user, referral_count=referral_count , current_year=datetime.now().year)


@main_bp.route('/about', methods=['GET', 'POST'])
def about():
    return render_template('main/about.html', current_year=datetime.now().year)

@main_bp.route('/donate-details', methods=['GET', 'POST'])
def donate_details():
    return render_template('main/donate_details.html', current_year=datetime.now().year)

@main_bp.route('/terms-of-service', methods=['GET', 'POST'])
def terms_of_service():
    return render_template('main/terms.html', current_year=datetime.now().year)

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

