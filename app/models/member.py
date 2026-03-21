# app/models/member.py
from app.extensions import db
from datetime import datetime

class Member(db.Model):
    __tablename__ = 'members'
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    address = db.Column(db.String(500))
    date_of_birth = db.Column(db.Date)
    occupation = db.Column(db.String(100))
    marital_status = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships - simplified
    church = db.relationship('Church', back_populates='members')
    # Remove the transactions relationship from here - we'll handle it in Transaction model
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
    
    def to_dict(self):
        return {
            'id': self.id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.get_full_name(),
            'email': self.email,
            'phone': self.phone,
            'address': self.address,
            'date_of_birth': self.date_of_birth.isoformat() if self.date_of_birth else None,
            'occupation': self.occupation,
            'marital_status': self.marital_status,
            'is_active': self.is_active,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }