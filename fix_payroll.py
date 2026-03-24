import re

with open('app/routes/payroll_routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace status='active' with is_active=1
content = re.sub(r"status = 'active'", "is_active = 1", content)
content = re.sub(r"status='active'", "is_active=1", content)
content = re.sub(r'status = "active"', "is_active = 1", content)

# Also update the test-basic endpoint
content = re.sub(r"WHERE status = 'active'", "WHERE is_active = 1", content)

with open('app/routes/payroll_routes.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Updated payroll routes to use is_active instead of status")
