from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from app.admin.models import User, Role
from wtforms import PasswordField
from wtforms.validators import EqualTo, Length
from wtforms import BooleanField

class LoginForm(FlaskForm):
    email = StringField(
        'Email', 
        validators=[DataRequired(), Email(), Length(max=150)],
        render_kw={"placeholder": "Enter your email"}
    )
    password = PasswordField(
        'Password', 
        validators=[DataRequired()],
        render_kw={"placeholder": "Enter your password"}
    )
    remember = BooleanField('Remember Me')  # ← new field
    submit = SubmitField('Login')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user is None:
            raise ValidationError(
                'No account found with this email. Please try again.'
            )


# Admin Form for creating or updating users
class AdminUserForm(FlaskForm):
    username = StringField('Username', 
                           validators=[DataRequired(), Length(min=3, max=150)],
                           render_kw={"placeholder": "Enter username"})
    email = StringField('Email', 
                        validators=[DataRequired(), Email(), Length(max=150)],
                        render_kw={"placeholder": "Enter email address"})
    password = PasswordField('Password', 
                             validators=[DataRequired(), Length(min=6)],
                             render_kw={"placeholder": "Enter password"})
    confirm_password = PasswordField('Confirm Password',
                                     validators=[DataRequired(), EqualTo('password')],
                                     render_kw={"placeholder": "Confirm password"})
    role = SelectField('Role', 
                       choices=[], 
                       validators=[DataRequired()],
                       render_kw={"placeholder": "Select role"})
    submit = SubmitField('Save User')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('This username is already taken. Please choose a different one.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('This email is already registered. Please choose a different one.')

    def set_role_choices(self):
        """Dynamically set role choices for the form."""
        self.role.choices = [(role.id, role.name) for role in Role.query.all()]


# User Registration Form
class RegisterForm(FlaskForm):
    username = StringField('Username',
                           validators=[DataRequired(), Length(min=3, max=150)],
                           render_kw={"placeholder": "Enter username"})
    email = StringField('Email',
                        validators=[DataRequired(), Email(), Length(max=150)],
                        render_kw={"placeholder": "Enter email address"})
    password = PasswordField('Password',
                             validators=[DataRequired(), Length(min=6)],
                             render_kw={"placeholder": "Enter password"})
    confirm_password = PasswordField('Confirm Password',
                                     validators=[DataRequired(), EqualTo('password')],
                                     render_kw={"placeholder": "Confirm password"})
    referral_code = StringField('Referral Code (Optional)',
                                render_kw={"placeholder": "Enter referral code (if any)"})
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('This username is already taken. Please choose a different one.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('This email is already registered. Please choose a different one.')
      

class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Send Reset Link')    



class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[EqualTo('password')])
    submit = SubmitField('Reset Password')


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[
        DataRequired()
    ])
    
    new_password = PasswordField('New Password', validators=[
        DataRequired(),
        Length(min=5, message="Password must be at least 5 characters.")
    ])

    confirm_password = PasswordField('Confirm New Password', validators=[
        DataRequired(),
        EqualTo('new_password', message='Passwords must match.')
    ])

    submit = SubmitField('Update Password')




class UpdateProfileForm(FlaskForm):
    full_name = StringField(
        "Full Name",
        validators=[
            DataRequired(message="Full name is required."),
            Length(min=2, max=100, message="Name must be between 2 and 100 characters.")
        ]
    )
    submit = SubmitField("Save Changes")
