from app import db
from flask import current_app as app, request, url_for
import string, secrets
from sqlalchemy.orm import backref
from datetime import datetime
from sqlalchemy.orm import relationship
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from itsdangerous import BadSignature, SignatureExpired
import uuid
from enum import Enum
import re
from sqlalchemy import event
from sqlalchemy.orm import backref, validates
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method

# ---------------------------------------
# contact model
# ---------------------------------------

class ContactMessage(db.Model):
    __tablename__ = 'contact_messages'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=False, index=True)
    subject = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ContactMessage {self.subject} from {self.name}>"




class Role(db.Model):
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255), nullable=True)

    # Relationship to users
    users = db.relationship('User', back_populates='role', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Role {self.name}>'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    # Core fields
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(150), unique=True, nullable=False, index=True)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)

    # Referral system
    referral_code = db.Column(db.String(12), unique=True, nullable=False, index=True)
    invited_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # Relationships
    role = db.relationship('Role', back_populates='users')
    invited_by = db.relationship(
        'User',
        remote_side=[id],
        backref=backref('referrals', lazy='dynamic')
    )

    def __repr__(self):
        return f'<User {self.username}>'

    #
    # Password methods
    #
    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    #
    # Role check
    #
    def has_role(self, role_name: str) -> bool:
        return self.role.name == role_name

    #
    # Password reset token
    #
    def generate_reset_token(self, expires_sec: int = 3600) -> str:
        s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id}, salt='password-reset')

    @staticmethod
    def verify_reset_token(token: str):
        s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
        try:
            data = s.loads(token, salt='password-reset', max_age=3600)
            return User.query.get(data['user_id'])
        except (BadSignature, SignatureExpired):
            return None
   
    # Referral code generation
   
    @staticmethod
    def generate_referral_code(length: int = 4) -> str:
        alphabet = string.ascii_uppercase + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    @classmethod
    def create_with_referral(cls, **kwargs):
        # Generate a unique referral code
        while True:
            code = cls.generate_referral_code()
            if not cls.query.filter_by(referral_code=code).first():
                break

        return cls(**kwargs, referral_code=code)
    
    def get_referral_link(self):
        base_url = request.url_root.strip('/')
        referral_path = url_for('auth.register', ref=self.referral_code, _external=False)
        return f"{base_url}{referral_path}"




def slugify(text: str) -> str:
    
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower())
    return slug.strip('-')


class Category(db.Model):
    __tablename__ = 'categories'
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    slug = db.Column(db.String(60), unique=True, nullable=False, index=True)

    # One-to-many → Program
    programs = db.relationship(
        'Program',
        backref='category',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f"<Category {self.name}>"

    @validates('name')
    def _set_slug(self, key, value):
        self.slug = slugify(value)
        return value


class Program(db.Model):
    __tablename__ = 'programs'
    id            = db.Column(db.Integer, primary_key=True)
    title         = db.Column(db.String(200), nullable=False)
    slug          = db.Column(db.String(220), unique=True, nullable=False, index=True)
    category_id   = db.Column(db.Integer, db.ForeignKey('categories.id'))
    description   = db.Column(db.String(500))    # Introductory description
    story         = db.Column(db.Text)           # Rich HTML/text full story
    cover_image   = db.Column(db.String(200))    # e.g. 'programs/cover1.jpg'
    annual_budget = db.Column(db.Numeric(12, 2), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    author_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Relationships
    author    = db.relationship('User', backref=backref('programs', lazy='dynamic'))
    images    = db.relationship(
        'ProgramImage',
        backref='program',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    donations = db.relationship(
        'Donation',
        backref='program',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f"<Program {self.title}>"

    @validates('title')
    def _set_slug(self, key, value):
        base = slugify(value)
        slug = base
        count = 1
        # ensure uniqueness
        while Program.query.filter_by(slug=slug).first():
            count += 1
            slug = f"{base}-{count}"
        self.slug = slug
        return value

    @property
    def total_donated(self):
        return float(db.session.query(
            db.func.coalesce(db.func.sum(Donation.amount), 0)
        ).filter_by(program_id=self.id).scalar())

    @property
    def budget_remaining(self):
        return float(self.annual_budget) - self.total_donated


class ProgramImage(db.Model):
    __tablename__ = 'program_images'
    id         = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=False)
    filename   = db.Column(db.String(200), nullable=False)  # e.g. 'programs/img1.jpg'
    is_cover   = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<ProgramImage {self.filename} cover={self.is_cover}>"



class Donation(db.Model):
    __tablename__ = 'donations'
    
    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    donor_name = db.Column(db.String(100))
    donor_email = db.Column(db.String(120))
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), default='NGN')  # Default to Naira for Paystack
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending/complete/failed
    is_recurring = db.Column(db.Boolean, default=False)
    payment_gateway = db.Column(db.String(50))  # paystack/paypal/etc
    gateway_reference = db.Column(db.String(100), unique=True)  # Transaction ID
    gateway_metadata = db.Column(db.JSON)  # Raw response from gateway
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('donations', lazy='dynamic'))
   

    __table_args__ = (
        db.Index('ix_donations_created_at', 'created_at'),
        db.Index('ix_donations_gateway_ref', 'gateway_reference'),
        db.CheckConstraint('amount > 0', name='positive_amount'),
        db.CheckConstraint(
            "(user_id IS NOT NULL) OR (donor_name IS NOT NULL AND donor_email IS NOT NULL)",
            name='guest_donation_requires_name_email'
        )
    )

    def __repr__(self):
        return f"<Donation {self.id} {self.amount}{self.currency} {self.status}>"

    def to_dict(self):
        return {
            'id': self.id,
            'amount': float(self.amount),
            'currency': self.currency,
            'donor_name': self.donor_name,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'program_id': self.program_id
        }

# Validation event
@event.listens_for(Donation, 'before_insert')
@event.listens_for(Donation, 'before_update')
def validate_donation(mapper, connection, target):
    if target.amount <= 0:
        raise ValueError("Donation amount must be positive")
    if not target.user_id and (not target.donor_name or not target.donor_email):
        raise ValueError("Guest donations require name and email")


 # Add this to your Donation model
@hybrid_property
def is_authenticated_donation(self):
    return self.user_id is not None       