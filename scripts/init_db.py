#!/usr/bin/env python
# scripts/init_db.py
import sys
import os
from pathlib import Path

# Add the parent directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import create_app
from app.extensions import db
from app.models import Church, User, Account, Role, PermissionModel
from datetime import datetime
from werkzeug.security import generate_password_hash

app = create_app()

def init_db():
    with app.app_context():
        print("Initializing database with default data...")
        
        # Create default church if not exists
        church = Church.query.first()
        if not church:
            church = Church(
                name="Default Church",
                legal_name="Default Church Organization",
                email="church@example.com",
                phone="1234567890",
                address="123 Church Street",
                city="City",
                state="State",
                country="Country",
                pastor_name="Pastor John Doe",
                denomination="Christian"
            )
            db.session.add(church)
            db.session.commit()
            print("✓ Default church created")
        else:
            print("✓ Church already exists")
        
        # Create default admin user if not exists
        admin = User.query.filter_by(email="admin@church.org").first()
        if not admin:
            admin = User(
                email="admin@church.org",
                username="admin",
                first_name="Admin",
                last_name="User",
                role="super_admin",
                church_id=church.id,
                is_active=True,
                is_verified=True
            )
            admin.set_password("admin123")
            db.session.add(admin)
            db.session.commit()
            print("✓ Default admin user created")
        else:
            print("✓ Admin user already exists")
        
        # Create default roles if not exist
        roles = ['super_admin', 'admin', 'treasurer', 'accountant', 'auditor', 'pastor', 'finance_committee', 'user']
        for role_name in roles:
            role = Role.query.filter_by(name=role_name).first()
            if not role:
                role = Role(name=role_name, description=f"{role_name.replace('_', ' ').title()} role")
                db.session.add(role)
                print(f"✓ Created role: {role_name}")
        
        # Create default accounts
        accounts = [
            {"code": "1010", "name": "Petty Cash", "type": "ASSET", "category": "cash", "opening_balance": 5000.00},
            {"code": "1020", "name": "Main Bank Account", "type": "ASSET", "category": "bank", "opening_balance": 50000.00},
            {"code": "1030", "name": "Savings Account", "type": "ASSET", "category": "bank", "opening_balance": 100000.00},
            {"code": "2010", "name": "Accounts Payable", "type": "LIABILITY", "category": "payable", "opening_balance": 0},
            {"code": "3010", "name": "Retained Earnings", "type": "EQUITY", "category": "equity", "opening_balance": 0},
            {"code": "4010", "name": "Tithes & Offerings", "type": "INCOME", "category": "income"},
            {"code": "4020", "name": "Donations", "type": "INCOME", "category": "income"},
            {"code": "4030", "name": "Special Offerings", "type": "INCOME", "category": "income"},
            {"code": "5010", "name": "Salaries & Wages", "type": "EXPENSE", "category": "expense"},
            {"code": "5020", "name": "Utilities", "type": "EXPENSE", "category": "expense"},
            {"code": "5030", "name": "Office Supplies", "type": "EXPENSE", "category": "expense"},
            {"code": "5040", "name": "Ministry Programs", "type": "EXPENSE", "category": "expense"},
            {"code": "5050", "name": "Maintenance", "type": "EXPENSE", "category": "expense"},
        ]
        
        accounts_created = 0
        for acc_data in accounts:
            account = Account.query.filter_by(
                account_code=acc_data["code"], 
                church_id=church.id
            ).first()
            
            if not account:
                account = Account(
                    church_id=church.id,
                    account_code=acc_data["code"],
                    name=acc_data["name"],
                    type=acc_data["type"],
                    category=acc_data.get("category"),
                    opening_balance=acc_data.get("opening_balance", 0),
                    current_balance=acc_data.get("opening_balance", 0),
                    is_active=True
                )
                db.session.add(account)
                accounts_created += 1
        
        db.session.commit()
        if accounts_created > 0:
            print(f"✓ Created {accounts_created} default accounts")
        else:
            print("✓ Accounts already exist")
        
        print("✅ Database initialization complete!")
        print("\nYou can now log in with:")
        print("  Email: admin@church.org")
        print("  Password: admin123")

if __name__ == "__main__":
    init_db()