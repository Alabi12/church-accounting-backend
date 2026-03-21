# app/models/employee.py
from app.extensions import db
from datetime import datetime

class Employee(db.Model):
    __tablename__ = 'employees'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    employee_code = db.Column(db.String(20), unique=True, nullable=False)
    
    # Personal Information
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    middle_name = db.Column(db.String(50))
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    city = db.Column(db.String(50))
    state = db.Column(db.String(50))
    postal_code = db.Column(db.String(20))
    country = db.Column(db.String(50), default='Ghana')
    
    # Identification
    national_id = db.Column(db.String(50))
    tax_id = db.Column(db.String(50))
    social_security_number = db.Column(db.String(20))
    
    # Employment Details
    department = db.Column(db.String(50))
    position = db.Column(db.String(100))
    hire_date = db.Column(db.Date, nullable=False)
    termination_date = db.Column(db.Date)
    employment_type = db.Column(db.String(20), default='full-time')
    pay_type = db.Column(db.String(20), default='salary')
    pay_rate = db.Column(db.Numeric(10, 2), nullable=False)
    pay_frequency = db.Column(db.String(20), default='monthly')
    overtime_rate = db.Column(db.Numeric(3, 2), default=1.5)
    
    # Bank Details
    bank_name = db.Column(db.String(100))
    bank_account_name = db.Column(db.String(100))
    bank_account_number = db.Column(db.String(50))
    bank_branch = db.Column(db.String(100))
    bank_sort_code = db.Column(db.String(20))
    
    # Status
    status = db.Column(db.String(20), default='active')
    
    # Metadata
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relationships - Using back_populates to avoid conflicts
    church = db.relationship('Church', backref='employees')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_employees')
    updater = db.relationship('User', foreign_keys=[updated_by], backref='updated_employees')
    time_entries = db.relationship('TimeEntry', back_populates='employee', lazy='dynamic')
    payroll_items = db.relationship('PayrollItem', back_populates='employee', lazy='dynamic')
    leave_balances = db.relationship('LeaveBalance', back_populates='employee', lazy='dynamic')
    employee_deductions = db.relationship('EmployeeDeduction', back_populates='employee', lazy='dynamic')
    
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def to_dict(self):
        return {
            'id': self.id,
            'church_id': self.church_id,
            'employee_code': self.employee_code,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.full_name(),
            'email': self.email,
            'phone': self.phone,
            'address': self.address,
            'city': self.city,
            'state': self.state,
            'department': self.department,
            'position': self.position,
            'hire_date': self.hire_date.isoformat() if self.hire_date else None,
            'employment_type': self.employment_type,
            'pay_type': self.pay_type,
            'pay_rate': float(self.pay_rate) if self.pay_rate else 0,
            'pay_frequency': self.pay_frequency,
            'bank_name': self.bank_name,
            'bank_account_number': self.bank_account_number,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class TimeEntry(db.Model):
    __tablename__ = 'time_entries'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    church_id = db.Column(db.Integer, db.ForeignKey('churches.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    
    work_date = db.Column(db.Date, nullable=False)
    hours_regular = db.Column(db.Numeric(5, 2), default=0)
    hours_overtime = db.Column(db.Numeric(5, 2), default=0)
    
    clock_in_time = db.Column(db.Time)
    clock_out_time = db.Column(db.Time)
    break_hours = db.Column(db.Numeric(3, 2), default=0)
    
    description = db.Column(db.Text)
    
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='draft')
    rejection_reason = db.Column(db.Text)
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relationships
    church = db.relationship('Church', backref='time_entries')
    approver = db.relationship('User', foreign_keys=[approved_by])
    creator = db.relationship('User', foreign_keys=[created_by])
    employee = db.relationship('Employee', back_populates='time_entries')
    
    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': self.employee.full_name() if self.employee else None,
            'work_date': self.work_date.isoformat() if self.work_date else None,
            'hours_regular': float(self.hours_regular),
            'hours_overtime': float(self.hours_overtime),
            'total_hours': float(self.hours_regular) + float(self.hours_overtime),
            'status': self.status,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None
        }