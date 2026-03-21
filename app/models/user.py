# app/models/user.py
from app.extensions import db
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    password_hash = db.Column(db.String(200))
    role = db.Column(db.String(50), default='user')
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    last_login = db.Column(db.DateTime)
    last_login_ip = db.Column(db.String(45))
    login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relationships
    church = db.relationship('Church', back_populates='users')
    user_roles = db.relationship('UserRole', back_populates='user', cascade='all, delete-orphan')
    
    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip()
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def increment_login_attempts(self):
        self.login_attempts += 1
        if self.login_attempts >= 5:
            self.locked_until = datetime.utcnow() + timedelta(minutes=15)
        db.session.commit()
    
    def reset_login_attempts(self):
        """Reset login attempts counter and unlock account"""
        self.login_attempts = 0
        self.locked_until = None
        db.session.commit()
    
    def update_last_login(self, ip_address=None):
        """Update last login timestamp and IP"""
        self.last_login = datetime.utcnow()
        self.last_login_ip = ip_address
        self.reset_login_attempts()
        db.session.commit()
    
    def is_locked(self):
        """Check if account is locked"""
        if self.locked_until and self.locked_until > datetime.utcnow():
            return True
        return False
    
    def get_permissions(self):
        permissions = {
            'super_admin': ['*'],
            'admin': ['view_all', 'edit_all'],
            'treasurer': ['view_finances', 'approve_expenses', 'view_budgets'],
            'accountant': ['create_transactions', 'view_reports'],
            'auditor': ['view_audit_logs', 'view_all'],
            'pastor': ['view_ministry_reports', 'view_members'],
            'finance_committee': ['view_budgets', 'approve_budgets'],
            'user': ['view_own']
        }
        return permissions.get(self.role, [])
    
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'username': self.username,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.full_name,
            'role': self.role,
            'church_id': self.church_id,
            'is_active': self.is_active,
            'is_verified': self.is_verified,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'login_attempts': self.login_attempts,
            'is_locked': self.is_locked(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }