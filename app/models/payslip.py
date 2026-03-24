from app.extensions import db
from datetime import datetime

class Payslip(db.Model):
    __tablename__ = 'payslips'
    
    id = db.Column(db.Integer, primary_key=True)
    payroll_line_id = db.Column(db.Integer, db.ForeignKey('payroll_lines.id'))
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'))
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'))
    payslip_number = db.Column(db.String(50), unique=True, nullable=False)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    pdf_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Add this line - it's currently missing!
    pdf_data = db.Column(db.LargeBinary)  # Add this field
    
    id = db.Column(db.Integer, primary_key=True)
    payroll_line_id = db.Column(db.Integer, db.ForeignKey('payroll_lines.id'))
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'))
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'))
    payslip_number = db.Column(db.String(50), unique=True, nullable=False)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    pdf_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Add this line - it's missing!
    pdf_data = db.Column(db.LargeBinary)  # Store PDF binary data
    
    # Relationships
    payroll_line = db.relationship('PayrollLine', backref='payslips')
    employee = db.relationship('Employee', backref='payslips')
    payroll_run = db.relationship('PayrollRun', backref='payslips')
    
    def to_dict(self):
        return {
            'id': self.id,
            'payslip_number': self.payslip_number,
            'employee_id': self.employee_id,
            'payroll_run_id': self.payroll_run_id,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'has_pdf': self.pdf_data is not None
        }