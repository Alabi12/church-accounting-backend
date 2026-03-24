from app.extensions import db
from datetime import datetime

class Church(db.Model):
    __tablename__ = 'churches'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.Text)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(200))
    website = db.Column(db.String(200))
    # logo = db.Column(db.String(500))  # Comment out or remove this line
    tax_id = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relationships
    members = db.relationship('Member', back_populates='church')
    budgets = db.relationship('Budget', back_populates='church')
    users = db.relationship('User', back_populates='church')
    settings = db.relationship('Setting', back_populates='church')
    approval_workflows = db.relationship('ApprovalWorkflow', back_populates='church')
    approval_requests = db.relationship('ApprovalRequest', back_populates='church')
    payroll_runs = db.relationship('PayrollRun', back_populates='church')
    journal_entries = db.relationship('JournalEntry', back_populates='church')
    accounts = db.relationship('Account', back_populates='church')
    transactions = db.relationship('Transaction', back_populates='church')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'address': self.address,
            'phone': self.phone,
            'email': self.email,
            'website': self.website,
            # 'logo': self.logo,  # Remove if logo is commented out
            'tax_id': self.tax_id
        }
