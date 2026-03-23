# app/models/leave.py
from app.extensions import db
from datetime import datetime

class LeaveRequest(db.Model):
    __tablename__ = 'leave_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_types.id'), nullable=False)
    
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    days_requested = db.Column(db.Integer, nullable=False)
    
    reason = db.Column(db.Text, nullable=False)
    
    # Approval workflow
    # Status: PENDING -> REVIEWED -> RECOMMENDED -> APPROVED -> REJECTED -> RETURNED
    status = db.Column(db.String(20), default='PENDING')
    
    # Admin Review
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_at = db.Column(db.DateTime)
    review_comments = db.Column(db.Text)
    
    # Admin Recommendation
    recommended_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    recommended_at = db.Column(db.DateTime)
    recommendation = db.Column(db.String(20))  # RECOMMEND or NOT_RECOMMEND
    recommendation_comments = db.Column(db.Text)
    
    # Pastor Approval
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    approval_comments = db.Column(db.Text)
    
    # Rejection/Return
    rejected_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejected_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    
    returned_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    returned_at = db.Column(db.DateTime)
    return_reason = db.Column(db.Text)
    
    # Allowance Processing
    allowance_processed = db.Column(db.Boolean, default=False)
    allowance_processed_at = db.Column(db.DateTime)
    allowance_amount = db.Column(db.Numeric(15, 2), default=0)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relationships
    employee = db.relationship('Employee', backref='leave_requests')
    leave_type = db.relationship('LeaveType', backref='leave_requests')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])
    recommender = db.relationship('User', foreign_keys=[recommended_by])
    approver = db.relationship('User', foreign_keys=[approved_by])
    payroll_run = db.relationship('PayrollRun', backref='leave_requests')
    
    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': self.employee.full_name if self.employee else '',
            'leave_type': self.leave_type.name if self.leave_type else '',
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'days_requested': self.days_requested,
            'reason': self.reason,
            'status': self.status,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_comments': self.review_comments,
            'recommended_by': self.recommended_by,
            'recommended_at': self.recommended_at.isoformat() if self.recommended_at else None,
            'recommendation': self.recommendation,
            'recommendation_comments': self.recommendation_comments,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'approval_comments': self.approval_comments,
            'rejection_reason': self.rejection_reason,
            'return_reason': self.return_reason,
            'allowance_processed': self.allowance_processed,
            'allowance_amount': float(self.allowance_amount) if self.allowance_amount else 0,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def can_review(self):
        return self.status == 'PENDING'
    
    def can_recommend(self):
        return self.status == 'REVIEWED'
    
    def can_approve(self):
        return self.status == 'RECOMMENDED'
    
    def can_process_allowance(self):
        return self.status == 'APPROVED' and not self.allowance_processed


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
            'leave_type': self.leave_type.name if self.leave_type else '',
            'year': self.year,
            'total_days': self.total_days,
            'used_days': self.used_days,
            'remaining_days': self.remaining_days
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
            'is_active': self.is_active
        }