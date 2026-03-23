# app/models/payroll.py
from app.extensions import db
from datetime import datetime
from decimal import Decimal

class PayrollRun(db.Model):
    __tablename__ = 'payroll_runs'
    
    id = db.Column(db.Integer, primary_key=True)
    run_number = db.Column(db.String(50), unique=True, nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    
    # Status workflow: DRAFT -> SUBMITTED -> REVIEWED -> RETURNED -> APPROVED -> PROCESSED -> POSTED
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
    
    # Attachments (for proof of payment)
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
    creator = db.relationship('User', foreign_keys=[submitted_by], backref='submitted_payrolls')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='reviewed_payrolls')
    approver = db.relationship('User', foreign_keys=[approved_by], backref='approved_payrolls')
    returner = db.relationship('User', foreign_keys=[returned_by], backref='returned_payrolls')
    processor = db.relationship('User', foreign_keys=[processed_by], backref='processed_payrolls')
    journal_entry = db.relationship('JournalEntry', backref='payroll_run')
    
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
            'net_pay': float(self.net_pay),
            'submitted_by': self.submitted_by,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_comments': self.review_comments,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'approval_comments': self.approval_comments,
            'returned_by': self.returned_by,
            'returned_at': self.returned_at.isoformat() if self.returned_at else None,
            'return_reason': self.return_reason,
            'has_attachment': bool(self.attachment_path),
            'attachment_verified': self.attachment_verified,
            'journal_entry_id': self.journal_entry_id
        }
    
    def can_submit(self):
        return self.status == 'DRAFT'
    
    def can_review(self):
        return self.status == 'SUBMITTED'
    
    def can_approve(self):
        return self.status == 'REVIEWED'
    
    def can_process(self):
        return self.status == 'APPROVED'
    
    def can_return(self):
        return self.status in ['SUBMITTED', 'REVIEWED']


class PayrollLine(db.Model):
    __tablename__ = 'payroll_lines'
    
    id = db.Column(db.Integer, primary_key=True)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    
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
    
    # Leave deductions
    leave_days_taken = db.Column(db.Integer, default=0)
    leave_payment = db.Column(db.Numeric(15, 2), default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    payroll_run = db.relationship('PayrollRun', backref='lines')
    employee = db.relationship('Employee', backref='payroll_lines')
    
    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': self.employee.full_name if self.employee else '',
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
            'net_pay': float(self.net_pay),
            'leave_days_taken': self.leave_days_taken,
            'leave_payment': float(self.leave_payment)
        }