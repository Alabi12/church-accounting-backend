from app import create_app
from app.models import User, UserRole
from app.extensions import db

app = create_app()

with app.app_context():
    # Find admin user
    admin = User.query.filter_by(email='admin@church.org').first()
    
    if admin:
        # Reset password
        admin.set_password('admin123')
        db.session.commit()
        print("✅ Admin password reset to: admin123")
    else:
        # Create admin if doesn't exist
        admin = User(
            email='admin@church.org',
            username='admin',
            first_name='Admin',
            last_name='User',
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_verified=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin user created with password: admin123")