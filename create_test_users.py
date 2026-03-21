# create_test_users.py - Fixed version

from app import create_app
from app.models import User, UserRole
from app.extensions import db

app = create_app()

with app.app_context():
    # Test users with different roles
    test_users = [
        {
            'email': 'pastor@church.org',
            'username': 'pastor',
            'password': 'Pastor@123',
            'first_name': 'John',
            'last_name': 'Pastor',
            'role': UserRole.PASTOR  # This is a string, not an enum
        },
        {
            'email': 'treasurer@church.org',
            'username': 'treasurer',
            'password': 'Treasurer@123',
            'first_name': 'Mike',
            'last_name': 'Treasurer',
            'role': UserRole.TREASURER
        },
        {
            'email': 'accountant@church.org',
            'username': 'accountant',
            'password': 'Accountant@123',
            'first_name': 'Sarah',
            'last_name': 'Accountant',
            'role': UserRole.ACCOUNTANT
        },
        {
            'email': 'auditor@church.org',
            'username': 'auditor',
            'password': 'Auditor@123',
            'first_name': 'David',
            'last_name': 'Auditor',
            'role': UserRole.AUDITOR
        },
        {
            'email': 'finance@church.org',
            'username': 'finance',
            'password': 'Finance@123',
            'first_name': 'Lisa',
            'last_name': 'Finance',
            'role': UserRole.FINANCE_COMMITTEE
        },
        {
            'email': 'user@church.org',
            'username': 'regularuser',
            'password': 'User@123',
            'first_name': 'Tom',
            'last_name': 'User',
            'role': UserRole.USER
        }
    ]
    
    created_count = 0
    for user_data in test_users:
        # Check if user already exists
        existing_user = User.query.filter_by(email=user_data['email']).first()
        if existing_user:
            print(f"⚠️ User {user_data['email']} already exists")
            continue
        
        # Create new user
        user = User(
            email=user_data['email'],
            username=user_data['username'],
            first_name=user_data['first_name'],
            last_name=user_data['last_name'],
            role=user_data['role'],  # This is already a string
            is_active=True,
            is_verified=True
        )
        user.set_password(user_data['password'])
        
        db.session.add(user)
        # Use the role directly - it's already a string
        print(f"✅ Created {user_data['role']}: {user_data['email']}")
        created_count += 1
    
    db.session.commit()
    print(f"\n🎉 {created_count} test users created successfully!")
    print("\nLogin credentials:")
    print("-" * 50)
    print("Super Admin: admin@church.org / admin123")
    print("Pastor: pastor@church.org / Pastor@123")
    print("Treasurer: treasurer@church.org / Treasurer@123")
    print("Accountant: accountant@church.org / Accountant@123")
    print("Auditor: auditor@church.org / Auditor@123")
    print("Finance Committee: finance@church.org / Finance@123")
    print("Regular User: user@church.org / User@123")