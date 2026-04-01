# app/models/leave.py
from app.extensions import db
from datetime import datetime

class LeaveRequest(db.Model):
    __tablename__ = 'leave_requests'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_types.id'), nullable=False)
    
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    days_requested = db.Column(db.Integer, nullable=False)
    
    reason = db.Column(db.Text, nullable=False)
    
    # Status workflow: PENDING_ADMIN -> PENDING_PASTOR -> APPROVED -> ALLOWANCE_PROCESSED -> ALLOWANCE_APPROVED -> PAID
    status = db.Column(db.String(50), default='PENDING_ADMIN')
    
    # Admin (HR/Admin) who enters the request
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    admin_at = db.Column(db.DateTime)
    admin_comments = db.Column(db.Text)
    
    # Pastor approval
    pastor_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    pastor_at = db.Column(db.DateTime)
    pastor_comments = db.Column(db.Text)
    
    # Accountant processing allowance
    accountant_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    accountant_at = db.Column(db.DateTime)
    accountant_comments = db.Column(db.Text)
    
    # Treasurer approval
    treasurer_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    treasurer_at = db.Column(db.DateTime)
    treasurer_comments = db.Column(db.Text)
    
    # Payment posting
    posted_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_at = db.Column(db.DateTime)
    posted_to_ledger = db.Column(db.Boolean, default=False)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'))
    
    # Leave allowance
    allowance_processed = db.Column(db.Boolean, default=False)
    allowance_processed_at = db.Column(db.DateTime)
    allowance_amount = db.Column(db.Numeric(15, 2), default=0)
    allowance_approved = db.Column(db.Boolean, default=False)
    allowance_approved_at = db.Column(db.DateTime)
    allowance_approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'))
    
    # Rejection tracking
    rejected_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejected_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    rejection_stage = db.Column(db.String(50))  # Which stage rejected it
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relationships
    employee = db.relationship('Employee', backref='leave_requests')
    leave_type = db.relationship('LeaveType', backref='leave_requests')
    
    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': self.employee.full_name() if self.employee else None,
            'leave_type_id': self.leave_type_id,
            'leave_type': self.leave_type.name if self.leave_type else None,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'days_requested': self.days_requested,
            'reason': self.reason,
            'status': self.status,
            'allowance_processed': self.allowance_processed,
            'allowance_amount': float(self.allowance_amount) if self.allowance_amount else 0,
            'allowance_approved': self.allowance_approved,
            'posted_to_ledger': self.posted_to_ledger,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'admin_at': self.admin_at.isoformat() if self.admin_at else None,
            'pastor_at': self.pastor_at.isoformat() if self.pastor_at else None,
            'accountant_at': self.accountant_at.isoformat() if self.accountant_at else None,
            'treasurer_at': self.treasurer_at.isoformat() if self.treasurer_at else None,
        }


class LeaveType(db.Model):
    __tablename__ = 'leave_types'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    description = db.Column(db.Text)
    default_days = db.Column(db.Integer, default=0)
    is_paid = db.Column(db.Boolean, default=True)
    requires_approval = db.Column(db.Boolean, default=True)
    allowance_rate = db.Column(db.Numeric(5, 2), default=0)  # Percentage or fixed amount
    allowance_type = db.Column(db.String(20), default='percentage')  # percentage or fixed
    is_active = db.Column(db.Boolean, default=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'description': self.description,
            'default_days': self.default_days,
            'is_paid': self.is_paid,
            'requires_approval': self.requires_approval,
            'allowance_rate': float(self.allowance_rate) if self.allowance_rate else 0,
            'allowance_type': self.allowance_type,
            'is_active': self.is_active
        }


class LeaveBalance(db.Model):
    __tablename__ = 'leave_balances'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_types.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    
    total_days = db.Column(db.Integer, default=0)
    used_days = db.Column(db.Integer, default=0)
    remaining_days = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relationships
    employee = db.relationship('Employee', backref='leave_balances')
    leave_type = db.relationship('LeaveType', backref='leave_balances')
    
    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': self.employee.full_name() if self.employee else None,
            'leave_type_id': self.leave_type_id,
            'leave_type': self.leave_type.name if self.leave_type else None,
            'year': self.year,
            'total_days': self.total_days,
            'used_days': self.used_days,
            'remaining_days': self.remaining_days
        }