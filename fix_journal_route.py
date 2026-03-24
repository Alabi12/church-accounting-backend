# Run this to fix the journal entry route
import re

with open('app/routes/accounting_routes.py', 'r') as f:
    content = f.read()

# Remove notes from journal entry creation
content = re.sub(
    r'notes=data\.get\(\'notes\'\),\s*', 
    '', 
    content
)

# Also remove notes from the data dict if it exists
content = re.sub(
    r"'notes': data\.get\('notes'\),\s*", 
    '', 
    content
)

with open('app/routes/accounting_routes.py', 'w') as f:
    f.write(content)

print("✅ Fixed journal entry route")
