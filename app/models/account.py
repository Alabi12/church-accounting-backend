# app/models/account.py
from app.extensions import db
from datetime import datetime

class Account(db.Model):
    __tablename__ = 'accounts'
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    
    # Account identification
    account_code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    display_name = db.Column(db.String(100))  # For reports
    
    # Classification based on your Chart of Accounts
    account_type = db.Column(db.String(20), nullable=False)  # REVENUE, EXPENSE, ASSET, LIABILITY, EQUITY
    category = db.Column(db.String(50))  # From your COA (e.g., 'Tithes', 'Staff Cost', 'Cash')
    sub_category = db.Column(db.String(50))  # More detailed grouping
    
    # Hierarchy
    parent_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    level = db.Column(db.Integer, default=1)  # 1=Main category, 2=Sub-category, 3=Detail
    
    # Financial data
    opening_balance = db.Column(db.Numeric(15, 2), default=0)
    current_balance = db.Column(db.Numeric(15, 2), default=0)
    normal_balance = db.Column(db.String(6), default='debit')  # 'debit' or 'credit'
    
    # Metadata
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    is_contra = db.Column(db.Boolean, default=False)  # For contra accounts (e.g., Accumulated Depreciation)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relationships
    parent = db.relationship('Account', remote_side=[id], backref=db.backref('children', lazy='dynamic'))
    church = db.relationship('Church', back_populates='accounts')
    
    def to_dict(self, include_children=False):
        result = {
            'id': self.id,
            'account_code': self.account_code,
            'name': self.name,
            'display_name': self.display_name or self.name,
            'account_type': self.account_type,
            'category': self.category,
            'sub_category': self.sub_category,
            'parent_account_id': self.parent_account_id,
            'level': self.level,
            'opening_balance': float(self.opening_balance),
            'current_balance': float(self.current_balance),
            'normal_balance': self.normal_balance,
            'description': self.description,
            'is_active': self.is_active,
            'is_contra': self.is_contra,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        
        if include_children:
            result['children'] = [child.to_dict() for child in self.children.all()]
        
        return result
    
    @classmethod
    def get_by_type(cls, church_id, account_type):
        """Get all accounts of a specific type"""
        return cls.query.filter_by(
            church_id=church_id,
            account_type=account_type,
            is_active=True
        ).order_by(cls.account_code).all()
    
    @classmethod
    def get_cash_accounts(cls, church_id):
        """Get all cash accounts"""
        return cls.query.filter_by(
            church_id=church_id,
            account_type='ASSET',
            is_active=True
        ).filter(
            db.or_(
                cls.category == 'Cash',
                cls.name.ilike('%cash%'),
                cls.name.ilike('%petty%')
            )
        ).all()
    
    @classmethod
    def get_bank_accounts(cls, church_id):
        """Get all bank accounts"""
        return cls.query.filter_by(
            church_id=church_id,
            account_type='ASSET',
            is_active=True
        ).filter(
            db.or_(
                cls.category == 'Bank',
                cls.name.ilike('%bank%'),
                cls.name.ilike('%checking%'),
                cls.name.ilike('%savings%')
            )
        ).all()
    
    @staticmethod
    def get_cash_accounts(church_id):
        """Get all cash accounts for a church"""
        return Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'ASSET',
            db.or_(
                Account.account_code.like('1010%'),
                Account.name.ilike('%cash%'),
                Account.name.ilike('%petty%')
            ),
            Account.is_active == True
        ).all()
    
    @staticmethod
    def get_bank_accounts(church_id):
        """Get all bank accounts for a church"""
        return Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'ASSET',
            db.or_(
                Account.account_code.like('1020%'),
                Account.name.ilike('%bank%')
            ),
            Account.is_active == True
        ).all()# If there's a church relationship with backref, change it to:
# church = db.relationship('Church', back_populates='accounts')
