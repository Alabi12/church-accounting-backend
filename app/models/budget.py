# app/models/budget.py
from app.extensions import db
from datetime import datetime

class Budget(db.Model):
    __tablename__ = 'budgets'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    department = db.Column(db.String(100))
    fiscal_year = db.Column(db.Integer, nullable=False)
    period = db.Column(db.String(20), default='annual')
    
    # Link to Chart of Accounts
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    account_code = db.Column(db.String(20))
    
    # Budget amounts
    amount = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    actual_amount = db.Column(db.Numeric(15, 2), default=0)
    variance = db.Column(db.Numeric(15, 2), default=0)
    variance_percentage = db.Column(db.Numeric(5, 2), default=0)
    
    # Budget type
    budget_type = db.Column(db.String(20), default='EXPENSE')
    
    priority = db.Column(db.String(20), default='MEDIUM')
    justification = db.Column(db.Text)
    status = db.Column(db.String(20), default='DRAFT')
    
    # Date range
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    
    # Monthly breakdown
    january = db.Column(db.Numeric(15, 2), default=0)
    february = db.Column(db.Numeric(15, 2), default=0)
    march = db.Column(db.Numeric(15, 2), default=0)
    april = db.Column(db.Numeric(15, 2), default=0)
    may = db.Column(db.Numeric(15, 2), default=0)
    june = db.Column(db.Numeric(15, 2), default=0)
    july = db.Column(db.Numeric(15, 2), default=0)
    august = db.Column(db.Numeric(15, 2), default=0)
    september = db.Column(db.Numeric(15, 2), default=0)
    october = db.Column(db.Numeric(15, 2), default=0)
    november = db.Column(db.Numeric(15, 2), default=0)
    december = db.Column(db.Numeric(15, 2), default=0)
    
    # Foreign keys
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    submitted_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejected_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    submitted_at = db.Column(db.DateTime)
    approved_at = db.Column(db.DateTime)
    rejected_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    
    # Relationships
    church = db.relationship('Church', back_populates='budgets')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_budgets')
    submitter = db.relationship('User', foreign_keys=[submitted_by], backref='submitted_budgets')
    approver = db.relationship('User', foreign_keys=[approved_by], backref='approved_budgets')
    rejecter = db.relationship('User', foreign_keys=[rejected_by], backref='rejected_budgets')
    account = db.relationship('Account', backref='budgets')
    
    def get_monthly_amount(self, month):
        month_map = {
            1: self.january, 2: self.february, 3: self.march,
            4: self.april, 5: self.may, 6: self.june,
            7: self.july, 8: self.august, 9: self.september,
            10: self.october, 11: self.november, 12: self.december
        }
        return float(month_map.get(month, 0))
    
    def calculate_variance(self, actual):
        self.actual_amount = actual
        self.variance = actual - self.amount
        if self.amount > 0:
            self.variance_percentage = (self.variance / self.amount) * 100
        return self.variance
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'department': self.department,
            'fiscal_year': self.fiscal_year,
            'period': self.period,
            'account_id': self.account_id,
            'account_code': self.account_code,
            'budget_type': self.budget_type,
            'amount': float(self.amount),
            'actual_amount': float(self.actual_amount) if self.actual_amount else 0,
            'variance': float(self.variance) if self.variance else 0,
            'variance_percentage': float(self.variance_percentage) if self.variance_percentage else 0,
            'priority': self.priority,
            'justification': self.justification,
            'status': self.status,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'monthly': {
                'january': float(self.january),
                'february': float(self.february),
                'march': float(self.march),
                'april': float(self.april),
                'may': float(self.may),
                'june': float(self.june),
                'july': float(self.july),
                'august': float(self.august),
                'september': float(self.september),
                'october': float(self.october),
                'november': float(self.november),
                'december': float(self.december)
            },
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'rejected_at': self.rejected_at.isoformat() if self.rejected_at else None,
            'rejection_reason': self.rejection_reason,
            'created_by': self.created_by,
            'submitted_by': self.submitted_by,
            'approved_by': self.approved_by,
            'rejected_by': self.rejected_by
        }


# Optional classes if needed
class BudgetCategory(db.Model):
    __tablename__ = 'budget_categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    parent_id = db.Column(db.Integer, db.ForeignKey('budget_categories.id'))
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'parent_id': self.parent_id
        }


class BudgetComment(db.Model):
    __tablename__ = 'budget_comments'
    
    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'budget_id': self.budget_id,
            'user_id': self.user_id,
            'comment': self.comment,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class BudgetAttachment(db.Model):
    __tablename__ = 'budget_attachments'
    
    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)
    mime_type = db.Column(db.String(100))
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'budget_id': self.budget_id,
            'filename': self.filename,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'mime_type': self.mime_type,
            'uploaded_by': self.uploaded_by,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }