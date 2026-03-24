import re

with open('app/routes/payroll_routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix line 685: Employee.status == 'active'
content = content.replace(
    "Employee.status == 'active'",
    "Employee.is_active == True"
)

# Fix line 699: PayrollRun.status == 'draft' (this might be correct - it's payroll run status, not employee)
# Keep this as is since it's referring to PayrollRun status

# Fix line 927: status='draft' (this is for PayrollRun status, keep it)

# Also fix any other Employee.status references
content = re.sub(
    r'Employee\.status\s*==\s*[\'"]active[\'"]',
    'Employee.is_active == True',
    content
)

content = re.sub(
    r'Employee\.status\s*==\s*[\'"]inactive[\'"]',
    'Employee.is_active == False',
    content
)

# Fix any filter_by with status for Employee
content = re.sub(
    r'Employee\.query\.filter_by\([^)]*status=[\'"]active[\'"][^)]*\)',
    'Employee.query.filter_by(is_active=True)',
    content
)

with open('app/routes/payroll_routes.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed all Employee.status references to use Employee.is_active")
