import os
from dotenv import load_dotenv
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))

# Load environment variables from .env file
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    SECRET_KEY                  = os.getenv('SECRET_KEY', 's3kr3t_k3y')
    SQLALCHEMY_DATABASE_URI     = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_SECURE       = True
    SESSION_COOKIE_HTTPONLY     = True
    PERMANENT_SESSION_LIFETIME  = timedelta(seconds=3600)

    MAIL_SERVER                 = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT                   = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS                = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USE_SSL                = os.getenv('MAIL_USE_SSL', 'False') == 'True'
    MAIL_USERNAME               = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD               = os.getenv('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER         = os.getenv('MAIL_DEFAULT_SENDER', MAIL_USERNAME)
    SECURITY_PASSWORD_SALT      = os.getenv('SECURITY_PASSWORD_SALT')
    REMEMBER_COOKIE_DURATION    = timedelta(days=14)
    
    UPLOAD_FOLDER               = os.path.join(basedir, 'static', 'programs')
    ALLOWED_EXTENSIONS          = {'png', 'jpg', 'jpeg', 'gif'}
    MAX_CONTENT_LENGTH          = 4 * 1024 * 1024  # 4 MB

    PAYSTACK_PUBLIC_KEY = os.getenv('PAYSTACK_PUBLIC_KEY')
    PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY')


        # For development/testing
    PAYPAL_CLIENT_ID=os.getenv('PAYPAL_CLIENT_ID')
    PAYPAL_SECRET=os.getenv('PAYPAL_SECRET')
    ENV = os.getenv('ENV', 'sandbox')

    # When you go live, swap these for your live App’s credentials
    # PAYPAL_CLIENT_ID="Adolh4w218TBosFO0Fc9vxPWpMTErBBnXkBVIIG2gZ-BvtFj7BQFddygJdQmVoZ76dL4XgD7fwgK_2lu"
    # PAYPAL_SECRET="EPY2KbnTkCj_bYNsxp8r1qDFD2QXPdkzVJO_8aD_DMAuhysB9yiZvmchi5A9XNJ-z_wSyscbUjW0Bn90"