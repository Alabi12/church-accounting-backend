# app/models/payslip.py
from app.extensions import db
from datetime import datetime

class Payslip(db.Model):
    __tablename__ = 'payslips'
    
    id = db.Column(db.Integer, primary_key=True)
    payroll_item_id = db.Column(db.Integer, db.ForeignKey('payroll_items.id'), nullable=False)
    payslip_number = db.Column(db.String(50), unique=True, nullable=False)
    
    # PDF storage
    pdf_data = db.Column(db.LargeBinary)  # Store PDF as binary
    pdf_generated_at = db.Column(db.DateTime)
    
    # Email tracking
    emailed_to = db.Column(db.String(100))
    emailed_at = db.Column(db.DateTime)
    email_status = db.Column(db.String(20), default='pending')  # pending, sent, failed
    
    # View tracking
    viewed_by_employee = db.Column(db.Boolean, default=False)
    viewed_at = db.Column(db.DateTime)
    
    # Digital signature
    employee_signature = db.Column(db.Text)  # Base64 encoded signature
    signed_at = db.Column(db.DateTime)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships - FIXED: Added backref with uselist=False since one payslip per payroll item
    payroll_item = db.relationship('PayrollItem', backref=db.backref('payslip', uselist=False))
    
    def to_dict(self):
        return {
            'id': self.id,
            'payslip_number': self.payslip_number,
            'payroll_item_id': self.payroll_item_id,
            'pdf_generated_at': self.pdf_generated_at.isoformat() if self.pdf_generated_at else None,
            'emailed_to': self.emailed_to,
            'emailed_at': self.emailed_at.isoformat() if self.emailed_at else None,
            'email_status': self.email_status,
            'viewed_by_employee': self.viewed_by_employee,
            'viewed_at': self.viewed_at.isoformat() if self.viewed_at else None,
            'signed_at': self.signed_at.isoformat() if self.signed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }