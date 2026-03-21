# app/models/role.py
from app.extensions import db
from datetime import datetime

class Role(db.Model):
    __tablename__ = 'roles'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user_assignments = db.relationship('UserRole', back_populates='role', cascade='all, delete-orphan')
    permissions = db.relationship('PermissionModel', back_populates='role', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class PermissionModel(db.Model):
    __tablename__ = 'permissions'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    category = db.Column(db.String(50))
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    role = db.relationship('Role', back_populates='permissions')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class UserRole(db.Model):
    __tablename__ = 'user_roles'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', back_populates='user_roles')
    role = db.relationship('Role', back_populates='user_assignments')
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'role_id': self.role_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }