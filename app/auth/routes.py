from flask import render_template, redirect, url_for, flash, request,Blueprint 
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.admin.models import User, Role
from .forms import LoginForm, AdminUserForm,RegisterForm, ForgotPasswordForm, ResetPasswordForm
from app.email.send_mail import send_email
from werkzeug.security import generate_password_hash
from functools import wraps
from datetime import datetime

auth_bp = Blueprint('auth', __name__)

# Custom decorator for role-based access
def roles_required(*roles):
    def wrapper(func):
        @wraps(func)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('main.login'))
            if current_user.role.name not in roles:
                flash('You do not have the required permissions to access this page.', 'danger')
                return redirect(url_for('main.home'))
            return func(*args, **kwargs)
        return decorated_view
    return wrapper

# Home route
@auth_bp.route('/')
def home():
    return render_template('home.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()

    if form.validate_on_submit():
        # Get default role
        default_role = Role.query.filter_by(name='User').first()
        if not default_role:
            flash('Default role missing. Please contact the admin.', 'danger')
            return redirect(url_for('auth.register'))

        # Check if referral code was provided and validate
        invited_by = None
        referral_code_input = form.referral_code.data.strip().upper() if form.referral_code.data else None
        if referral_code_input:
            invited_by = User.query.filter_by(referral_code=referral_code_input).first()
            if not invited_by:
                flash('Invalid referral code.', 'danger')
                return render_template('auth/register.html', form=form)

        # Create the user with the referral code assigned
        user = User.create_with_referral(
            username=form.username.data,
            email=form.email.data,
            password_hash=generate_password_hash(form.password.data),
            role_id=default_role.id,
            invited_by_id=invited_by.id if invited_by else None
        )

        # Add the user to the session and commit
        db.session.add(user)
        db.session.commit()

        # Send welcome email
        send_email(
            subject="Welcome to Rusken",
            recipients=[user.email],
            template="emails/welcome.html",
            user=user,
            site_name="Rusken Charity",
            homepage_url="https://www.ruskencf2024.org/",
            contact_url="https://www.ruskencf2024.org/contact",
            logo_url="https://www.ruskencf2024.org/static/images/Rusken-Charity-Foundation.png",
            year=datetime.utcnow().year
        )

        flash(f'Account created! Your referral code is {user.referral_code}', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', form=form)


# Login route
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            # ← pass form.remember.data here
            login_user(user, remember=form.remember.data)
            flash('Logged in successfully!', 'success')
            
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('main.home'))
        else:
            flash('Invalid email or password', 'danger')
    
    return render_template('auth/login.html', form=form)

# Logout route
@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('main.home'))

# Admin: Add a new user route (only admins can access)
@auth_bp.route('/admin/add_user', methods=['GET', 'POST'])
@login_required
@roles_required('Admin')  # Only accessible by Admins
def add_user():
    form = AdminUserForm()
    form.set_role_choices()  # Populate roles dynamically
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        new_user = User(username=form.username.data, email=form.email.data, password_hash=hashed_password, role_id=form.role.data)
        db.session.add(new_user)
        db.session.commit()
        flash('New user added successfully!', 'success')
        return redirect(url_for('main.admin_dashboard'))
    
    return render_template('admin/add_user.html', form=form)

# Admin: View all users (Admin only)
@auth_bp.route('/admin/users')
@login_required
@roles_required('Admin')
def view_users():
    users = User.query.all()
    return render_template('admin/view_users.html', users=users)

# Admin dashboard (admin only)
@auth_bp.route('/admin')
@login_required
@roles_required('Admin')
def admin_dashboard():
    return render_template('admin/dashboard.html')


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = user.generate_reset_token()
            reset_link = url_for('auth.reset_password', token=token, _external=True)

            # Send reset email
            send_email(
                subject="Reset Your Password - Rusken Charity",
                recipients=[user.email],
                template="emails/reset_password.html",
                user=user,
                reset_link=reset_link
            )
        flash('If that email exists, You will receive a reset link.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot_password.html', form=form)

@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.verify_reset_token(token)
    if not user:
        flash('The reset link is invalid or expired.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash('Your password has been updated. You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    # Pass the token into the template context
    return render_template(
        'auth/reset_password.html',
        form=form,
        token=token
    )


