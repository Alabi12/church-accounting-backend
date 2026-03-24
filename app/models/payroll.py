from app.extensions import db
from datetime import datetime
from decimal import Decimal

class PayrollRun(db.Model):
    __tablename__ = 'payroll_runs'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    run_number = db.Column(db.String(50), unique=True, nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='DRAFT')
    
    gross_pay = db.Column(db.Numeric(15, 2), default=0)
    total_deductions = db.Column(db.Numeric(15, 2), default=0)
    net_pay = db.Column(db.Numeric(15, 2), default=0)
    
    submitted_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    submitted_at = db.Column(db.DateTime)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Use back_populates instead of backref
    church = db.relationship('Church', back_populates='payroll_runs')
    lines = db.relationship('PayrollLine', back_populates='payroll_run', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'run_number': self.run_number,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'payment_date': self.payment_date.isoformat() if self.payment_date else None,
            'status': self.status,
            'gross_pay': float(self.gross_pay),
            'total_deductions': float(self.total_deductions),
            'net_pay': float(self.net_pay)
        }


class PayrollLine(db.Model):
    __tablename__ = 'payroll_lines'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    
    basic_salary = db.Column(db.Numeric(15, 2), default=0)
    allowances = db.Column(db.Numeric(15, 2), default=0)
    overtime = db.Column(db.Numeric(15, 2), default=0)
    bonus = db.Column(db.Numeric(15, 2), default=0)
    
    paye_tax = db.Column(db.Numeric(15, 2), default=0)
    ssnit_employee = db.Column(db.Numeric(15, 2), default=0)
    ssnit_employer = db.Column(db.Numeric(15, 2), default=0)
    provident_fund = db.Column(db.Numeric(15, 2), default=0)
    other_deductions = db.Column(db.Numeric(15, 2), default=0)
    
    gross_earnings = db.Column(db.Numeric(15, 2), default=0)
    total_deductions = db.Column(db.Numeric(15, 2), default=0)
    net_pay = db.Column(db.Numeric(15, 2), default=0)
    
    leave_days_taken = db.Column(db.Integer, default=0)
    leave_payment = db.Column(db.Numeric(15, 2), default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Use back_populates
    payroll_run = db.relationship('PayrollRun', back_populates='lines')
    employee = db.relationship('Employee', backref='payroll_lines')
    
    def to_dict(self):
        return {
            'id': self.id,
            'payroll_run_id': self.payroll_run_id,
            'employee_id': self.employee_id,
            'basic_salary': float(self.basic_salary),
            'allowances': float(self.allowances),
            'overtime': float(self.overtime),
            'bonus': float(self.bonus),
            'paye_tax': float(self.paye_tax),
            'ssnit_employee': float(self.ssnit_employee),
            'ssnit_employer': float(self.ssnit_employer),
            'provident_fund': float(self.provident_fund),
            'other_deductions': float(self.other_deductions),
            'gross_earnings': float(self.gross_earnings),
            'total_deductions': float(self.total_deductions),
            'net_pay': float(self.net_pay)
        }
