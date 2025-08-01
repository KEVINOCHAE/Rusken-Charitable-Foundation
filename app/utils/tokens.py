# app/utils/tokens.py
from itsdangerous import URLSafeTimedSerializer
from datetime import datetime, timedelta
from flask import current_app

def generate_email_token(email):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(email, salt='donation-access')

def verify_email_token(token, max_age=3600):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = serializer.loads(
            token,
            salt='donation-access',
            max_age=max_age
        )
    except:
        return False
    return email