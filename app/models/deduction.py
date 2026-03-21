# app/models/deduction.py
from app.extensions import db
from datetime import datetime

class DeductionType(db.Model):
    __tablename__ = 'deduction_types'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    calculation_type = db.Column(db.String(20), nullable=False)  # percentage, fixed
    rate = db.Column(db.Numeric(5, 2), default=0)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    is_statutory = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    church = db.relationship('Church', backref='deduction_types')
    account = db.relationship('Account', backref='deduction_types')
    employee_deductions = db.relationship('EmployeeDeduction', back_populates='deduction_type')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'calculation_type': self.calculation_type,
            'rate': float(self.rate) if self.rate else 0,
            'account_id': self.account_id,
            'is_statutory': self.is_statutory,
            'is_active': self.is_active
        }


class EmployeeDeduction(db.Model):
    __tablename__ = 'employee_deductions'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    deduction_type_id = db.Column(db.Integer, db.ForeignKey('deduction_types.id'), nullable=False)
    
    amount = db.Column(db.Numeric(10, 2))
    rate = db.Column(db.Numeric(5, 2))
    is_active = db.Column(db.Boolean, default=True)
    
    effective_from = db.Column(db.Date)
    effective_to = db.Column(db.Date)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    employee = db.relationship('Employee', back_populates='employee_deductions')
    deduction_type = db.relationship('DeductionType', back_populates='employee_deductions')
    
    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'deduction_type_id': self.deduction_type_id,
            'deduction_name': self.deduction_type.name if self.deduction_type else None,
            'amount': float(self.amount) if self.amount else None,
            'rate': float(self.rate) if self.rate else None,
            'is_active': self.is_active
        }