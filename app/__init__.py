from flask import Flask, send_from_directory, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail
import logging


# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
mail = Mail()

def create_app(config_class=None):
    app = Flask(__name__)
    app.config.from_object(config_class or 'config.Config')

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)



    logging.basicConfig(
        level=logging.INFO, 
        format="%(asctime)s [%(levelname)s] - %(message)s",
        handlers=[
            logging.StreamHandler(),  # Logs to the console
            logging.FileHandler("app.log")  # Logs to a file named app.log
        ]
    )


    # Setup login view and messages
    login_manager.login_view = 'auth.login'  # Redirect to login route
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'warning'

    # Blueprints
    from app.auth.routes import auth_bp 
    from app.main.routes import main_bp
    from app.admin.routes import admin_bp
    from app.programs.routes import program_bp
    from app.donate.routes import donate_bp
    from app.dpo.routes import dpo_bp
    
    
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(program_bp, url_prefix='/program')
    app.register_blueprint(donate_bp, url_prefix='/donate')
    app.register_blueprint(dpo_bp, url_prefix='/dpo')

    # User loader for login management
    from app.admin.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))


    @app.route('/media/programs/<filename>')
    def serve_program_image(filename):
        return send_from_directory('/data/programs', filename)
    

    # Sitemap route
    @app.route('/sitemap.xml')
    def sitemap():
        return send_from_directory(app.static_folder, 'sitemap.xml')


     # In your template filters file
    @app.template_filter('currency')
    def currency_format(value):
        return "KES{:,.2f}".format(float(value))

    @app.template_filter('datetime_format')
    def datetime_format(value, format='medium'):
        if format == 'short':
            return value.strftime('%b %d, %Y')
        return value.strftime('%B %d, %Y at %I:%M %p')   


    def program_image_url(img):
        if img:
            filename = img.filename.split('/')[-1]
            return url_for('serve_program_image', filename=filename)
        else:
            return url_for('static', filename='programs/placeholder.jpg')

    app.jinja_env.filters['program_image_url'] = program_image_url
    
     
    return app
