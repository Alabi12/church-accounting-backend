import re

with open('app/routes/payroll_routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find and replace the employee query in calculate_payroll
# Look for pattern with status='active' and replace with is_active=True
content = re.sub(
    r'Employee\.query\.filter_by\(\s*\n?\s*church_id=church_id,\s*\n?\s*status=[\'"]active[\'"]\s*\n?\s*\)',
    'Employee.query.filter_by(church_id=church_id, is_active=True)',
    content,
    flags=re.DOTALL
)

# Also replace any other status references
content = re.sub(
    r'status=[\'"]active[\'"]',
    'is_active=True',
    content
)

content = re.sub(
    r'status=[\'"]inactive[\'"]',
    'is_active=False',
    content
)

with open('app/routes/payroll_routes.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed payroll calculate function to use is_active=True")
