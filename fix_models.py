#!/usr/bin/env python
"""Script to fix model relationships"""
import os
import re

def fix_file(filepath, replacements):
    """Apply replacements to a file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    
    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Fixed: {filepath}")
    else:
        print(f"⏭️  No changes: {filepath}")

# Files to fix
files_to_fix = [
    'app/models/deduction.py',
    'app/models/leave.py', 
    'app/models/payslip.py',
    'app/models/payroll.py'
]

# Replacements for each file
replacements = {
    'app/models/deduction.py': [
        # Comment out relationships that reference Employee
        (r'(\s+)employee = db\.relationship\(\'Employee\', back_populates=\'employee_deductions\'\)', 
         r'\1# employee = db.relationship(\'Employee\', back_populates=\'employee_deductions\')  # Added in relationships.py'),
        # Comment out the ForeignKey line (keep it commented, will be added in relationships.py)
        (r'(\s+)employee_id = db\.Column\(db\.Integer, db\.ForeignKey\(\'employees\.id\'\), nullable=False\)',
         r'\1# employee_id = db.Column(db.Integer, db.ForeignKey(\'employees.id\'), nullable=False)  # Added in relationships.py'),
    ],
    'app/models/leave.py': [
        # Comment out employee relationships
        (r'(\s+)employee = db\.relationship\(\'Employee\', back_populates=\'leave_balances\'\)',
         r'\1# employee = db.relationship(\'Employee\', back_populates=\'leave_balances\')  # Added in relationships.py'),
        (r'(\s+)employee = db\.relationship\(\'Employee\', backref=\'leave_requests\'\)',
         r'\1# employee = db.relationship(\'Employee\', backref=\'leave_requests\')  # Added in relationships.py'),
        # Comment out ForeignKey lines
        (r'(\s+)employee_id = db\.Column\(db\.Integer, db\.ForeignKey\(\'employees\.id\'\), nullable=False\)',
         r'\1# employee_id = db.Column(db.Integer, db.ForeignKey(\'employees.id\'), nullable=False)  # Added in relationships.py'),
    ],
    'app/models/payslip.py': [
        # Comment out employee relationship
        (r'(\s+)employee = db\.relationship\(\'Employee\', backref=\'payslips\'\)',
         r'\1# employee = db.relationship(\'Employee\', backref=\'payslips\')  # Added in relationships.py'),
        # Comment out ForeignKey line
        (r'(\s+)employee_id = db\.Column\(db\.Integer, db\.ForeignKey\(\'employees\.id\'\), nullable=False\)',
         r'\1# employee_id = db.Column(db.Integer, db.ForeignKey(\'employees.id\'), nullable=False)  # Added in relationships.py'),
    ],
    'app/models/payroll.py': [
        # Comment out employee relationship in PayrollLine
        (r'(\s+)employee = db\.relationship\(\'Employee\', backref=\'payroll_lines\'\)',
         r'\1# employee = db.relationship(\'Employee\', backref=\'payroll_lines\')  # Added in relationships.py'),
        # Comment out ForeignKey line
        (r'(\s+)employee_id = db\.Column\(db\.Integer, db\.ForeignKey\(\'employees\.id\'\), nullable=False\)',
         r'\1# employee_id = db.Column(db.Integer, db.ForeignKey(\'employees.id\'), nullable=False)  # Added in relationships.py'),
    ]
}

for filepath, file_replacements in replacements.items():
    if os.path.exists(filepath):
        fix_file(filepath, file_replacements)
    else:
        print(f"⚠️  File not found: {filepath}")

print("\n✅ Model fixes complete!")
