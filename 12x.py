#!/usr/bin/env python
"""
Script to create default roles and seed an initial admin user with a referral code.
Usage: python create_admin.py
"""

import getpass
from app import create_app, db
from app.admin.models import User, Role

# Initialize the Flask app
app = create_app()

def create_roles_and_admin():
    with app.app_context():
        # 1. Create tables
        db.create_all()

        # 2. Ensure roles exist
        user_role = Role.query.filter_by(name='User').first()
        if not user_role:
            user_role = Role(name='User', description='Default user role')
            db.session.add(user_role)
            print("• ‘User’ role created.")
        else:
            print("• ‘User’ role already exists.")

        admin_role = Role.query.filter_by(name='Admin').first()
        if not admin_role:
            admin_role = Role(name='Admin', description='Administrator role with full access')
            db.session.add(admin_role)
            print("• ‘Admin’ role created.")
        else:
            print("• ‘Admin’ role already exists.")

        # Commit role changes
        db.session.commit()

        # 3. Prompt for admin credentials
        print("\nEnter credentials for the initial admin user:")
        username = input("  • Username: ").strip()
        email = input("  • Email: ").strip()
        password = getpass.getpass("  • Password: ")

        # 4. Check if admin user already exists
        existing = User.query.filter_by(username=username).first()
        if existing:
            print(f"⚠️ Admin user '{username}' already exists. No action taken.")
            return

        # 5. Create the admin user (with referral code)
        admin_user = User.create_with_referral(
            username=username,
            email=email,
            role_id=admin_role.id,
            invited_by_id=None
        )
        admin_user.set_password(password)

        db.session.add(admin_user)
        db.session.commit()

        print(f"✅ Admin user '{username}' created.")
        print(f"   • Referral code: {admin_user.referral_code}")

if __name__ == '__main__':
    create_roles_and_admin()
