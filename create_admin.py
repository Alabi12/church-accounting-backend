# create_admin.py
import os
import sys
from app import create_app
from app.extensions import db
from app.models import User, Church, Role

def create_admin():
    """Create admin user in production database"""
    app = create_app('production')
    
    with app.app_context():
        print("🔧 Setting up admin user...")
        
        # Check if church exists
        church = Church.query.first()
        if not church:
            church = Church(
                name='Default Church',
                email='church@example.com',
                phone='1234567890',
                address='123 Church Street'
            )
            db.session.add(church)
            db.session.commit()
            print("✅ Church created")
        
        # Create roles if they don't exist
        roles = ['super_admin', 'admin', 'treasurer', 'accountant', 'auditor', 'pastor', 'finance_committee', 'user']
        for role_name in roles:
            if not Role.query.filter_by(name=role_name).first():
                role = Role(name=role_name, description=f"{role_name.replace('_', ' ').title()} role")
                db.session.add(role)
        db.session.commit()
        print("✅ Roles created")
        
        # Create admin user
        admin = User.query.filter_by(email='admin@church.org').first()
        if not admin:
            admin = User(
                email='admin@church.org',
                username='admin',
                first_name='Admin',
                last_name='User',
                role='super_admin',
                church_id=church.id,
                is_active=True,
                is_verified=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✅ Admin user created")
            print("   Email: admin@church.org")
            print("   Password: admin123")
        else:
            print("ℹ️ Admin user already exists")
        
        print("🎉 Setup complete!")

if __name__ == '__main__':
    create_admin()