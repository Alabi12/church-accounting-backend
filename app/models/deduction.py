from app.extensions import db
from datetime import datetime
from decimal import Decimal

class DeductionType(db.Model):
    __tablename__ = "deduction_types"
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    is_percentage = db.Column(db.Boolean, default=True)
    default_value = db.Column(db.Numeric(10, 2), default=0)
    is_mandatory = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "is_percentage": self.is_percentage,
            "default_value": float(self.default_value),
            "is_mandatory": self.is_mandatory,
            "is_active": self.is_active
        }


class EmployeeDeduction(db.Model):
    __tablename__ = "employee_deductions"
    
    id = db.Column(db.Integer, primary_key=True)
    deduction_type_id = db.Column(db.Integer, db.ForeignKey("deduction_types.id"), nullable=False)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey("payroll_runs.id"), nullable=True)
    
    amount = db.Column(db.Numeric(15, 2), default=0)
    percentage = db.Column(db.Numeric(5, 2), default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "deduction_type_id": self.deduction_type_id,
            "amount": float(self.amount),
            "percentage": float(self.percentage),
            "is_active": self.is_active
        }
