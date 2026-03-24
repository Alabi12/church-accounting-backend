from app.extensions import db
from datetime import datetime

class JournalEntry(db.Model):
    __tablename__ = 'journal_entries'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    entry_number = db.Column(db.String(50), unique=True, nullable=False)
    entry_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    description = db.Column(db.Text)
    reference = db.Column(db.String(100))
    
    status = db.Column(db.String(20), nullable=False, default='DRAFT')
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    
    posted_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_at = db.Column(db.DateTime)
    
    voided_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    voided_at = db.Column(db.DateTime)
    void_reason = db.Column(db.Text)
    
    # Use back_populates instead of backref
    church = db.relationship('Church', back_populates='journal_entries')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_journal_entries')
    approver = db.relationship('User', foreign_keys=[approved_by], backref='approved_journal_entries')
    poster = db.relationship('User', foreign_keys=[posted_by], backref='posted_journal_entries')
    voider = db.relationship('User', foreign_keys=[voided_by], backref='voided_journal_entries')
    lines = db.relationship('JournalLine', back_populates='journal_entry', cascade='all, delete-orphan')
    
    def to_dict(self):
        creator_name = self.creator.full_name if self.creator else None
        approver_name = self.approver.full_name if self.approver else None
        poster_name = self.poster.full_name if self.poster else None
        voider_name = self.voider.full_name if self.voider else None
        
        total_debit = sum(float(line.debit) for line in self.lines)
        total_credit = sum(float(line.credit) for line in self.lines)
        is_balanced = abs(total_debit - total_credit) < 0.01
        
        return {
            'id': self.id,
            'entry_number': self.entry_number,
            'entry_date': self.entry_date.isoformat(),
            'description': self.description,
            'reference': self.reference,
            'status': self.status,
            'lines': [line.to_dict() for line in self.lines],
            'total_debit': total_debit,
            'total_credit': total_credit,
            'is_balanced': is_balanced,
            'created_by': self.created_by,
            'created_by_name': creator_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'approved_by': self.approved_by,
            'approved_by_name': approver_name,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'posted_by': self.posted_by,
            'posted_by_name': poster_name,
            'posted_at': self.posted_at.isoformat() if self.posted_at else None,
            'voided_by': self.voided_by,
            'voided_by_name': voider_name,
            'voided_at': self.voided_at.isoformat() if self.voided_at else None,
            'void_reason': self.void_reason,
            'church_id': self.church_id
        }


class JournalLine(db.Model):
    __tablename__ = 'journal_lines'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    
    debit = db.Column(db.Numeric(15, 2), default=0)
    credit = db.Column(db.Numeric(15, 2), default=0)
    
    description = db.Column(db.Text)
    
    journal_entry = db.relationship('JournalEntry', back_populates='lines')
    account = db.relationship('Account', backref='journal_lines')
    
    __table_args__ = (
        db.CheckConstraint('(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)', 
                          name='check_debit_credit_exclusive'),
        {'extend_existing': True}
    )
    
    def to_dict(self):
        account_code = self.account.account_code if self.account else None
        account_name = self.account.name if self.account else None
        
        return {
            'id': self.id,
            'journal_entry_id': self.journal_entry_id,
            'account_id': self.account_id,
            'account_code': account_code,
            'account_name': account_name,
            'debit': float(self.debit) if self.debit else 0,
            'credit': float(self.credit) if self.credit else 0,
            'description': self.description
        }
