# app/models/church.py
from app.extensions import db
from datetime import datetime

class Church(db.Model):
    __tablename__ = 'churches'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    legal_name = db.Column(db.String(200))
    address = db.Column(db.String(500))
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    postal_code = db.Column(db.String(20))
    country = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    website = db.Column(db.String(200))
    tax_id = db.Column(db.String(50))
    founded_date = db.Column(db.Date)
    pastor_name = db.Column(db.String(200))
    denomination = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relationships
    users = db.relationship('User', back_populates='church', lazy=True)
    accounts = db.relationship('Account', back_populates='church', lazy='dynamic')
    transactions = db.relationship('Transaction', back_populates='church', lazy=True)
    members = db.relationship('Member', back_populates='church', lazy=True)
    budgets = db.relationship('Budget', back_populates='church', lazy=True)
    settings = db.relationship('Setting', back_populates='church', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'legal_name': self.legal_name,
            'address': self.address,
            'city': self.city,
            'phone': self.phone,
            'email': self.email,
            'website': self.website,
            'pastor_name': self.pastor_name,
            'denomination': self.denomination,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }