# app/models/payslip.py
from app.extensions import db
from datetime import datetime

class Payslip(db.Model):
    __tablename__ = 'payslips'
    
    id = db.Column(db.Integer, primary_key=True)
    payroll_line_id = db.Column(db.Integer, db.ForeignKey('payroll_lines.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'), nullable=False)
    
    # Payslip data
    payslip_number = db.Column(db.String(50), unique=True, nullable=False)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    pdf_path = db.Column(db.String(500))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships - use string references
    payroll_line = db.relationship('PayrollLine', backref='payslip', uselist=False)
    employee = db.relationship('Employee', backref='payslips')
    payroll_run = db.relationship('PayrollRun', backref='payslips')