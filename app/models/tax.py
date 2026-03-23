# app/models/tax.py
from app.extensions import db
from datetime import datetime
from decimal import Decimal

class TaxTable(db.Model):
    __tablename__ = 'tax_tables'
    
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    
    # Tax brackets
    bracket_1_limit = db.Column(db.Numeric(15, 2), default=402)  # First 402 GHS at 0%
    bracket_2_limit = db.Column(db.Numeric(15, 2), default=110)  # Next 110 at 5%
    bracket_3_limit = db.Column(db.Numeric(15, 2), default=130)  # Next 130 at 10%
    bracket_4_limit = db.Column(db.Numeric(15, 2), default=3000) # Next 3000 at 17.5%
    bracket_5_limit = db.Column(db.Numeric(15, 2), default=20000) # Next 20000 at 25%
    # Remainder at 30%
    
    bracket_1_rate = db.Column(db.Numeric(5, 2), default=0)      # 0%
    bracket_2_rate = db.Column(db.Numeric(5, 2), default=5)      # 5%
    bracket_3_rate = db.Column(db.Numeric(5, 2), default=10)     # 10%
    bracket_4_rate = db.Column(db.Numeric(5, 2), default=17.5)   # 17.5%
    bracket_5_rate = db.Column(db.Numeric(5, 2), default=25)     # 25%
    bracket_6_rate = db.Column(db.Numeric(5, 2), default=30)     # 30%
    
    # SSNIT rates
    ssnit_employee_rate = db.Column(db.Numeric(5, 2), default=5.5)
    ssnit_employer_rate = db.Column(db.Numeric(5, 2), default=13)
    
    # Provident fund rates
    provident_fund_employee_rate = db.Column(db.Numeric(5, 2), default=5)
    provident_fund_employer_rate = db.Column(db.Numeric(5, 2), default=10)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'year': self.year,
            'description': self.description,
            'is_active': self.is_active,
            'brackets': [
                {'limit': float(self.bracket_1_limit), 'rate': float(self.bracket_1_rate)},
                {'limit': float(self.bracket_2_limit), 'rate': float(self.bracket_2_rate)},
                {'limit': float(self.bracket_3_limit), 'rate': float(self.bracket_3_rate)},
                {'limit': float(self.bracket_4_limit), 'rate': float(self.bracket_4_rate)},
                {'limit': float(self.bracket_5_limit), 'rate': float(self.bracket_5_rate)},
                {'limit': None, 'rate': float(self.bracket_6_rate)}
            ],
            'ssnit': {
                'employee_rate': float(self.ssnit_employee_rate),
                'employer_rate': float(self.ssnit_employer_rate)
            },
            'provident_fund': {
                'employee_rate': float(self.provident_fund_employee_rate),
                'employer_rate': float(self.provident_fund_employer_rate)
            }
        }