from app.extensions import db
from datetime import datetime


class ReconciliationRecord(db.Model):
    __tablename__ = 'reconciliation_records'

    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    reconciliation_date = db.Column(db.Date, nullable=False)

    opening_balance = db.Column(db.Numeric(15, 2), default=0)
    statement_balance = db.Column(db.Numeric(15, 2), default=0)
    book_balance = db.Column(db.Numeric(15, 2), default=0)
    reconciled_bank_balance = db.Column(db.Numeric(15, 2), default=0)
    reconciled_book_balance = db.Column(db.Numeric(15, 2), default=0)
    difference = db.Column(db.Numeric(15, 2), default=0)

    status = db.Column(db.String(20), default='IN_PROGRESS')
    # NOT_STARTED | IN_PROGRESS | COMPLETED | LOCKED

    completed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    completed_at = db.Column(db.DateTime)
    unlocked_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    unlocked_at = db.Column(db.DateTime)
    unlock_reason = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = db.relationship('Account', backref='reconciliations')