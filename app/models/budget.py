# app/models/budget.py
from app.extensions import db
from datetime import datetime

class Budget(db.Model):
    __tablename__ = 'budgets'
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'))
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    department = db.Column(db.String(100))
    fiscal_year = db.Column(db.String(10))
    amount = db.Column(db.Numeric(10, 2))
    approved_amount = db.Column(db.Numeric(10, 2))
    previous_amount = db.Column(db.Numeric(10, 2))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='DRAFT')
    priority = db.Column(db.String(20), default='MEDIUM')
    justification = db.Column(db.Text)
    submitted_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    submitted_date = db.Column(db.DateTime)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_date = db.Column(db.DateTime)
    rejected_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejected_date = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)



    # Relationships
    church = db.relationship('Church', back_populates='budgets')
    submitter = db.relationship('User', foreign_keys=[submitted_by], backref='submitted_budgets')
    approver = db.relationship('User', foreign_keys=[approved_by], backref='approved_budgets')
    rejecter = db.relationship('User', foreign_keys=[rejected_by], backref='rejected_budgets')
    comments = db.relationship('BudgetComment', backref='budget', lazy='dynamic', cascade='all, delete-orphan')
    
    def to_dict(self):
        """Convert budget to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'church_id': self.church_id,
            'name': self.name,
            'description': self.description,
            'department': self.department,
            'fiscal_year': self.fiscal_year,
            'amount': float(self.amount) if self.amount else 0,
            'approved_amount': float(self.approved_amount) if self.approved_amount else 0,
            'status': self.status,
            'priority': self.priority,
            'justification': self.justification,
            'submitted_by': self.submitted_by,
            'submitted_date': self.submitted_date.isoformat() if self.submitted_date else None,
            'approved_by': self.approved_by,
            'approved_date': self.approved_date.isoformat() if self.approved_date else None,
            'rejected_by': self.rejected_by,
            'rejected_date': self.rejected_date.isoformat() if self.rejected_date else None,
            'rejection_reason': self.rejection_reason,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
class BudgetCategory(db.Model):
    __tablename__ = 'budget_categories'
    
    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    requested_amount = db.Column(db.Numeric(15, 2), default=0)
    approved_amount = db.Column(db.Numeric(15, 2), default=0)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'requested': float(self.requested_amount),
            'approved': float(self.approved_amount) if self.approved_amount else 0
        }

class BudgetComment(db.Model):
    __tablename__ = 'budget_comments'
    
    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class BudgetAttachment(db.Model):
    __tablename__ = 'budget_attachments'
    
    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)