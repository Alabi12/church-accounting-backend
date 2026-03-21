# app/models/transaction.py
from app.extensions import db
from datetime import datetime

class Transaction(db.Model):
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    transaction_number = db.Column(db.String(50), unique=True)
    transaction_date = db.Column(db.DateTime, nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # INCOME, EXPENSE
    category = db.Column(db.String(100))
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'))
    description = db.Column(db.Text)
    payment_method = db.Column(db.String(50))
    reference_number = db.Column(db.String(100))
    status = db.Column(db.String(20), default='PENDING')
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_date = db.Column(db.DateTime)
    rejected_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejected_date = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships - simplified and with unique backref names
    church = db.relationship('Church', back_populates='transactions')
    account = db.relationship('Account', back_populates='transactions')
    member = db.relationship('Member', backref='member_transactions')  # Changed backref name
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_transactions')
    approver = db.relationship('User', foreign_keys=[approved_by], backref='approved_transactions')
    rejecter = db.relationship('User', foreign_keys=[rejected_by], backref='rejected_transactions')
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    account = db.relationship('Account', backref='transactions')

    reconciled = db.Column(db.Boolean, default=False)
    reconciliation_date = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'transaction_number': self.transaction_number,
            'date': self.transaction_date.isoformat().split('T')[0] if self.transaction_date else None,
            'transaction_type': self.transaction_type,
            'category': self.category,
            'amount': float(self.amount),
            'account_id': self.account_id,
            'account_name': self.account.name if self.account else None,
            'member_id': self.member_id,
            'member_name': self.member.get_full_name() if self.member else None,
            'description': self.description,
            'payment_method': self.payment_method,
            'reference': self.reference_number,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }