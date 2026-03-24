from app.extensions import db
from datetime import datetime
from decimal import Decimal

class PayrollRun(db.Model):
    __tablename__ = 'payroll_runs'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    run_number = db.Column(db.String(50), unique=True, nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    
    # Statuses: INITIATED, CALCULATED, REVIEWED, APPROVED, PROCESSED
    status = db.Column(db.String(20), default='INITIATED')
    
    # Amounts - match database column names
    total_gross = db.Column(db.Numeric(15, 2), default=0)
    total_deductions = db.Column(db.Numeric(15, 2), default=0)
    total_tax = db.Column(db.Numeric(15, 2), default=0)
    total_net = db.Column(db.Numeric(15, 2), default=0)
    
    # Admin initiation
    initiated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    initiated_at = db.Column(db.DateTime)
    
    # Accountant calculation
    calculated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    calculated_at = db.Column(db.DateTime)
    calculation_notes = db.Column(db.Text)
    
    # Treasurer review
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_at = db.Column(db.DateTime)
    review_comments = db.Column(db.Text)
    
    # Treasurer approval
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    approval_comments = db.Column(db.Text)
    
    # Processing
    processed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    processed_at = db.Column(db.DateTime)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'))
    
    # Attachments
    attachment_path = db.Column(db.String(500))
    attachment_filename = db.Column(db.String(255))
    attachment_uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    attachment_uploaded_at = db.Column(db.DateTime)
    attachment_verified = db.Column(db.Boolean, default=False)
    attachment_verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    attachment_verified_at = db.Column(db.DateTime)
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    church = db.relationship('Church', back_populates='payroll_runs')
    lines = db.relationship('PayrollLine', backref='payroll_run', cascade='all, delete-orphan')
    
    @property
    def gross_pay(self):
        return self.total_gross
    
    @property
    def net_pay(self):
        return self.total_net
    
    def to_dict(self):
        """Convert PayrollRun to dictionary with all fields frontend expects"""
        # Calculate total tax if not stored
        total_tax = float(self.total_tax) if self.total_tax is not None else 0.0
        if total_tax == 0 and hasattr(self, 'lines') and self.lines:
            total_tax = sum(float(line.paye_tax or 0) for line in self.lines)
        
        # Get payroll line items for the employees tab
        items = []
        if hasattr(self, 'lines') and self.lines:
            for line in self.lines:
                employee = line.employee
                items.append({
                    'id': line.id,
                    'employee_id': line.employee_id,
                    'employee_name': f"{employee.first_name} {employee.last_name}" if employee else f"Employee {line.employee_id}",
                    'department': employee.department if employee else 'N/A',
                    'basic_salary': float(line.basic_salary or 0),
                    'allowances': float(line.allowances or 0),
                    'gross_pay': float(line.gross_earnings or 0),
                    'tax_amount': float(line.paye_tax or 0),
                    'pension_amount': float(line.ssnit_employee or 0),
                    'other_deductions': float(line.other_deductions or 0),
                    'net_pay': float(line.net_pay or 0),
                    'employee': {
                        'department': employee.department if employee else 'N/A'
                    }
                })
        
        return {
            'id': self.id,
            'run_number': self.run_number,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'payment_date': self.payment_date.isoformat() if self.payment_date else None,
            'status': self.status.lower() if self.status else 'draft',
            # Frontend expects these names
            'total_gross': float(self.total_gross) if self.total_gross is not None else 0.0,
            'total_deductions': float(self.total_deductions) if self.total_deductions is not None else 0.0,
            'total_tax': total_tax,
            'total_net': float(self.total_net) if self.total_net is not None else 0.0,
            'employee_count': len(self.lines) if hasattr(self, 'lines') else 0,
            'items': items,
            # Backwards compatibility (for existing code)
            'gross_pay': float(self.total_gross) if self.total_gross is not None else 0.0,
            'net_pay': float(self.total_net) if self.total_net is not None else 0.0,
            # Admin fields
            'initiated_by': self.initiated_by,
            'initiated_at': self.initiated_at.isoformat() if self.initiated_at else None,
            'calculated_by': self.calculated_by,
            'calculated_at': self.calculated_at.isoformat() if self.calculated_at else None,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'processed_by': self.processed_by,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'journal_entry_id': self.journal_entry_id,
            'has_attachment': bool(self.attachment_path),
            'attachment_verified': self.attachment_verified
        }


class PayrollLine(db.Model):
    __tablename__ = 'payroll_lines'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    
    # Earnings
    basic_salary = db.Column(db.Numeric(15, 2), default=0)
    allowances = db.Column(db.Numeric(15, 2), default=0)
    overtime = db.Column(db.Numeric(15, 2), default=0)
    bonus = db.Column(db.Numeric(15, 2), default=0)
    leave_payment = db.Column(db.Numeric(15, 2), default=0)
    
    # Deductions
    paye_tax = db.Column(db.Numeric(15, 2), default=0)
    ssnit_employee = db.Column(db.Numeric(15, 2), default=0)
    ssnit_employer = db.Column(db.Numeric(15, 2), default=0)
    provident_fund = db.Column(db.Numeric(15, 2), default=0)
    other_deductions = db.Column(db.Numeric(15, 2), default=0)
    
    # Totals
    gross_earnings = db.Column(db.Numeric(15, 2), default=0)
    total_deductions = db.Column(db.Numeric(15, 2), default=0)
    net_pay = db.Column(db.Numeric(15, 2), default=0)
    
    leave_days_taken = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    employee = db.relationship('Employee', backref='payroll_lines')
    
    def calculate_totals(self):
        """Calculate gross earnings, total deductions, and net pay"""
        # Calculate gross earnings
        self.gross_earnings = (self.basic_salary or 0) + (self.allowances or 0) + \
                              (self.overtime or 0) + (self.bonus or 0) + (self.leave_payment or 0)
        
        # Calculate total deductions
        self.total_deductions = (self.paye_tax or 0) + (self.ssnit_employee or 0) + \
                                (self.provident_fund or 0) + (self.other_deductions or 0)
        
        # Calculate net pay
        self.net_pay = self.gross_earnings - self.total_deductions
        
        return self
    
    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': self.employee.full_name() if self.employee else '',
            'basic_salary': float(self.basic_salary or 0),
            'allowances': float(self.allowances or 0),
            'overtime': float(self.overtime or 0),
            'bonus': float(self.bonus or 0),
            'leave_payment': float(self.leave_payment or 0),
            'gross_earnings': float(self.gross_earnings or 0),
            'paye_tax': float(self.paye_tax or 0),
            'ssnit_employee': float(self.ssnit_employee or 0),
            'ssnit_employer': float(self.ssnit_employer or 0),
            'provident_fund': float(self.provident_fund or 0),
            'other_deductions': float(self.other_deductions or 0),
            'total_deductions': float(self.total_deductions or 0),
            'net_pay': float(self.net_pay or 0),
            # Frontend compatibility fields
            'gross_pay': float(self.gross_earnings or 0),
            'tax_amount': float(self.paye_tax or 0),
            'pension_amount': float(self.ssnit_employee or 0),
            'leave_days_taken': self.leave_days_taken or 0
        }