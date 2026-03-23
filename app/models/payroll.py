# app/models/payroll.py
from app.extensions import db
from datetime import datetime
from decimal import Decimal

class PayrollRun(db.Model):
    __tablename__ = 'payroll_runs'
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    run_number = db.Column(db.String(50), unique=True, nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    
    # Status workflow
    status = db.Column(db.String(20), default='DRAFT')
    
    # Amounts
    gross_pay = db.Column(db.Numeric(15, 2), default=0)
    total_deductions = db.Column(db.Numeric(15, 2), default=0)
    net_pay = db.Column(db.Numeric(15, 2), default=0)
    
    # Approval workflow
    submitted_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    submitted_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_at = db.Column(db.DateTime)
    review_comments = db.Column(db.Text)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    approval_comments = db.Column(db.Text)
    returned_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    returned_at = db.Column(db.DateTime)
    return_reason = db.Column(db.Text)
    
    # Processing
    processed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    processed_at = db.Column(db.DateTime)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'))
    
    # Attachments
    attachment_path = db.Column(db.String(500))
    attachment_filename = db.Column(db.String(255))
    attachment_uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    attachment_uploaded_at = db.Column(db.DateTime)
    attachment_verified = db.Column(db.Boolean, default=False)
    attachment_verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    attachment_verified_at = db.Column(db.DateTime)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relationships
    church = db.relationship('Church', backref='payroll_runs')
    lines = db.relationship('PayrollLine', backref='payroll_run', cascade='all, delete-orphan')


class PayrollLine(db.Model):
    __tablename__ = 'payroll_lines'
    
    id = db.Column(db.Integer, primary_key=True)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'), nullable=False)
    employee_id = db.Column(db.Integer, nullable=False)  # Remove ForeignKey for now
    # We'll add the ForeignKey after Employee model is loaded
    
    # Earnings
    basic_salary = db.Column(db.Numeric(15, 2), default=0)
    allowances = db.Column(db.Numeric(15, 2), default=0)
    overtime = db.Column(db.Numeric(15, 2), default=0)
    bonus = db.Column(db.Numeric(15, 2), default=0)
    
    # Deductions
    paye_tax = db.Column(db.Numeric(15, 2), default=0)
    ssnit_employee = db.Column(db.Numeric(15, 2), default=0)
    ssnit_employer = db.Column(db.Numeric(15, 2), default=0)
    provident_fund = db.Column(db.Numeric(15, 2), default=0)
    other_deductions = db.Column(db.Numeric(15, 2), default=0)
    
    # Totals
    gross_earnings = db.Column(db.Numeric(15, 2), default=0)
    total_deductions = db.Column(db.Numeric(15, 2), default=0)
    net_pay = db.Column(db.Numeric(15, 2), default=0)
    
    # Leave
    leave_days_taken = db.Column(db.Integer, default=0)
    leave_payment = db.Column(db.Numeric(15, 2), default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    