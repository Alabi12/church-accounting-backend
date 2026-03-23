# app/models/tax.py
from app.extensions import db
from datetime import datetime

class TaxTable(db.Model):
    __tablename__ = 'tax_tables'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    tax_year = db.Column(db.Integer, nullable=False)
    
    bracket_from = db.Column(db.Numeric(10, 2), nullable=False)
    bracket_to = db.Column(db.Numeric(10, 2))
    rate = db.Column(db.Numeric(5, 2), nullable=False)
    
    ss_employee_rate = db.Column(db.Numeric(5, 2), default=5.5)
    ss_employer_rate = db.Column(db.Numeric(5, 2), default=13.0)
    ss_annual_limit = db.Column(db.Numeric(10, 2))
    
    hi_employee_rate = db.Column(db.Numeric(5, 2), default=2.5)
    hi_employer_rate = db.Column(db.Numeric(5, 2), default=2.5)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    church = db.relationship('Church', backref='tax_tables')
    
    def to_dict(self):
        return {
            'id': self.id,
            'tax_year': self.tax_year,
            'bracket_from': float(self.bracket_from),
            'bracket_to': float(self.bracket_to) if self.bracket_to else None,
            'rate': float(self.rate),
            'ss_employee_rate': float(self.ss_employee_rate),
            'ss_employer_rate': float(self.ss_employer_rate),
            'hi_employee_rate': float(self.hi_employee_rate),
            'hi_employer_rate': float(self.hi_employer_rate)
        }