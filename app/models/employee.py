# app/models/employee.py
from app.extensions import db
from datetime import datetime
from decimal import Decimal

class Employee(db.Model):
    __tablename__ = 'employees'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    
    # Personal Information
    employee_number = db.Column(db.String(50), unique=True, nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    middle_name = db.Column(db.String(100))
    email = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    
    # Employment Details
    position = db.Column(db.String(100))
    department = db.Column(db.String(100))
    employment_type = db.Column(db.String(50))
    hire_date = db.Column(db.Date)
    termination_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)
    
    # Payroll Details
    basic_salary = db.Column(db.Numeric(15, 2), default=0)
    allowances = db.Column(db.Numeric(15, 2), default=0)
    hourly_rate = db.Column(db.Numeric(10, 2), default=0)
    
    # Tax Details
    ssnit_number = db.Column(db.String(50))
    tax_id = db.Column(db.String(50))
    
    # Bank Details
    bank_name = db.Column(db.String(100))
    bank_account_number = db.Column(db.String(50))
    bank_branch = db.Column(db.String(100))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relationships - use string references
    user = db.relationship('User', backref='employee')
    church = db.relationship('Church', backref='employees')
    
    @property
    def full_name(self):
        if self.middle_name:
            return f"{self.first_name} {self.middle_name} {self.last_name}"
        return f"{self.first_name} {self.last_name}"
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'employee_number': self.employee_number,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'middle_name': self.middle_name,
            'full_name': self.full_name,
            'email': self.email,
            'phone': self.phone,
            'position': self.position,
            'department': self.department,
            'employment_type': self.employment_type,
            'hire_date': self.hire_date.isoformat() if self.hire_date else None,
            'termination_date': self.termination_date.isoformat() if self.termination_date else None,
            'is_active': self.is_active,
            'basic_salary': float(self.basic_salary),
            'allowances': float(self.allowances),
            'hourly_rate': float(self.hourly_rate),
            'ssnit_number': self.ssnit_number,
            'tax_id': self.tax_id,
            'bank_name': self.bank_name,
            'bank_account_number': self.bank_account_number,
            'bank_branch': self.bank_branch,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }