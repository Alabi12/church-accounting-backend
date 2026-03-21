# app/models/payroll.py
from app.extensions import db
from datetime import datetime

class PayrollRun(db.Model):
    __tablename__ = 'payroll_runs'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    run_number = db.Column(db.String(20), unique=True, nullable=False)
    
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    
    total_gross = db.Column(db.Numeric(12, 2), default=0)
    total_deductions = db.Column(db.Numeric(12, 2), default=0)
    total_tax = db.Column(db.Numeric(12, 2), default=0)
    total_net = db.Column(db.Numeric(12, 2), default=0)
    
    status = db.Column(db.String(20), default='draft')
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'))
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    processed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    processed_at = db.Column(db.DateTime)
    
    # Relationships
    church = db.relationship('Church', backref='payroll_runs')
    creator = db.relationship('User', foreign_keys=[created_by])
    approver = db.relationship('User', foreign_keys=[approved_by])
    processor = db.relationship('User', foreign_keys=[processed_by])
    journal_entry = db.relationship('JournalEntry', backref='payroll_run')
    items = db.relationship('PayrollItem', back_populates='payroll_run', lazy='dynamic')
    
    def to_dict(self):
        return {
            'id': self.id,
            'run_number': self.run_number,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'payment_date': self.payment_date.isoformat() if self.payment_date else None,
            'total_gross': float(self.total_gross),
            'total_deductions': float(self.total_deductions),
            'total_tax': float(self.total_tax),
            'total_net': float(self.total_net),
            'status': self.status,
            'employee_count': self.items.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class PayrollItem(db.Model):
    __tablename__ = 'payroll_items'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    
    regular_pay = db.Column(db.Numeric(10, 2), default=0)
    overtime_pay = db.Column(db.Numeric(10, 2), default=0)
    bonus_pay = db.Column(db.Numeric(10, 2), default=0)
    allowance_pay = db.Column(db.Numeric(10, 2), default=0)
    gross_pay = db.Column(db.Numeric(10, 2), default=0)
    
    tax_amount = db.Column(db.Numeric(10, 2), default=0)
    pension_amount = db.Column(db.Numeric(10, 2), default=0)
    health_insurance = db.Column(db.Numeric(10, 2), default=0)
    other_deductions = db.Column(db.Numeric(10, 2), default=0)
    total_deductions = db.Column(db.Numeric(10, 2), default=0)
    
    net_pay = db.Column(db.Numeric(10, 2), default=0)
    
    hours_regular = db.Column(db.Numeric(5, 2), default=0)
    hours_overtime = db.Column(db.Numeric(5, 2), default=0)
    
    # Relationships - Fixed to use back_populates
    payroll_run = db.relationship('PayrollRun', back_populates='items')
    employee = db.relationship('Employee', back_populates='payroll_items')
    
    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': self.employee.full_name() if self.employee else None,
            'regular_pay': float(self.regular_pay),
            'overtime_pay': float(self.overtime_pay),
            'gross_pay': float(self.gross_pay),
            'tax_amount': float(self.tax_amount),
            'pension_amount': float(self.pension_amount),
            'total_deductions': float(self.total_deductions),
            'net_pay': float(self.net_pay),
            'hours_regular': float(self.hours_regular),
            'hours_overtime': float(self.hours_overtime)
        }