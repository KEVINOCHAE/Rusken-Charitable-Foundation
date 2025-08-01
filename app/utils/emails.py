# app/utils/emails.py
from flask import url_for, current_app
from app import mail
from flask_mail import Message
from app.utils.tokens import generate_email_token
def send_donation_access_email(email):
    token = generate_email_token(email)
    access_url = url_for('donate.find_donations', _external=True, token=token)
    
    msg = Message(
        "Access Your Donation History - Rusken Foundation",
        recipients=[email],
        sender=current_app.config['MAIL_DEFAULT_SENDER']
    )
    
    msg.html = f"""
    <html>
      <body>
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
          <h2 style="color: #2e7d32;">Your Donation History Access</h2>
          <p>Hello,</p>
          <p>You requested access to your donation history. Click the button below to view your donations:</p>
          
          <a href="{access_url}" 
             style="display: inline-block; padding: 10px 20px; background-color: #2e7d32; 
                    color: white; text-decoration: none; border-radius: 5px; margin: 15px 0;">
            View My Donations
          </a>
          
          <p>This link will expire in 1 hour. If you didn't request this, please ignore this email.</p>
          
          <p>Thank you for your support!</p>
          <p><strong>The Rusken Foundation Team</strong></p>
          
          <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
          <p style="font-size: 12px; color: #777;">
            Can't click the button? Copy and paste this link into your browser:<br>
            {access_url}
          </p>
        </div>
      </body>
    </html>
    """
    
    mail.send(msg)