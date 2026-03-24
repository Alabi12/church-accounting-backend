from app.extensions import db
from datetime import datetime

class ApprovalWorkflow(db.Model):
    __tablename__ = 'approval_workflows'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    steps = db.Column(db.Integer, default=1)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Use back_populates instead of backref
    church = db.relationship('Church', back_populates='approval_workflows')
    steps_config = db.relationship('ApprovalWorkflowStep', backref='workflow', lazy='dynamic')


class ApprovalWorkflowStep(db.Model):
    __tablename__ = 'approval_workflow_steps'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey('approval_workflows.id'), nullable=False)
    step_number = db.Column(db.Integer, nullable=False)
    approver_role = db.Column(db.String(50))
    approver_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    description = db.Column(db.String(200))


class ApprovalRequest(db.Model):
    __tablename__ = 'approval_requests'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    current_step = db.Column(db.Integer, default=0)
    total_steps = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default='PENDING')
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    
    # Use back_populates
    church = db.relationship('Church', back_populates='approval_requests')
    requester = db.relationship('User', foreign_keys=[requested_by], backref='requested_approvals')
    approvals = db.relationship('Approval', back_populates='approval_request', lazy='dynamic')


class Approval(db.Model):
    __tablename__ = 'approvals'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('approval_requests.id'), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    step_number = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False)
    comments = db.Column(db.Text)
    actioned_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Use back_populates
    approval_request = db.relationship('ApprovalRequest', back_populates='approvals')
    approver = db.relationship('User', foreign_keys=[approver_id], backref='approvals')
    comments_list = db.relationship('ApprovalComment', back_populates='approval', cascade='all, delete-orphan')


class ApprovalComment(db.Model):
    __tablename__ = 'approval_comments'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    approval_id = db.Column(db.Integer, db.ForeignKey('approvals.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Use back_populates
    approval = db.relationship('Approval', back_populates='comments_list')
    user = db.relationship('User', foreign_keys=[user_id], backref='approval_comments')
