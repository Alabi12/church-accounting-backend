from app.extensions import db
from datetime import datetime

class Payslip(db.Model):
    __tablename__ = 'payslips'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    payroll_line_id = db.Column(db.Integer, db.ForeignKey('payroll_lines.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'), nullable=False)
    
    payslip_number = db.Column(db.String(50), unique=True, nullable=False)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    pdf_path = db.Column(db.String(500))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    payroll_line = db.relationship('PayrollLine', backref='payslip', uselist=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'payroll_line_id': self.payroll_line_id,
            'employee_id': self.employee_id,
            'payroll_run_id': self.payroll_run_id,
            'payslip_number': self.payslip_number,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'pdf_path': self.pdf_path
        }
