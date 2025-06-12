from flask_wtf import FlaskForm
from wtforms import DecimalField, StringField, EmailField, SubmitField, HiddenField
from wtforms.validators import DataRequired, NumberRange, Email, Length

class DonationForm(FlaskForm):
    amount = DecimalField(
        'Donation Amount (USD)',
        places=2,
        rounding=None,
        validators=[
            DataRequired(message="Please enter an amount you'd like to donate."),
            NumberRange(min=1, message="Donation must be at least $1.")
        ]
    )

    donor_name = StringField(
        'Name (optional)',
        validators=[
            DataRequired(message="We need your Name for Reciepts."),
            Length(max=100, message="Name cannot exceed 100 characters.")
        ]
    )

    donor_email = EmailField(
        'Email Address',
        validators=[
            DataRequired(message="We need your email to send you a donation receipt."),
            Email(message="Please enter a valid email address.")
        ]
    )

    flex_token = HiddenField('Flex Token')


    submit = SubmitField('Donate Now')




class FindDonationsForm(FlaskForm):
    email = StringField('Email Address', 
                      validators=[
                          DataRequired(message="Please enter your email address"),
                          Email(message="Please enter a valid email address")
                      ],
                      render_kw={
                          "placeholder": "your@email.com",
                          "class": "form-control"
                      })
    submit = SubmitField('Find Donations',
                       render_kw={"class": "btn btn-primary w-100"})