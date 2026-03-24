import re

with open('app/routes/accounting_routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the opening_balance line
content = re.sub(
    r'running_balance = float\(account\.opening_balance\)',
    'opening_balance = float(account.opening_balance) if account.opening_balance is not None else 0.0\n        running_balance = opening_balance',
    content
)

# Also fix the summary openingBalance
content = re.sub(
    r"'openingBalance': float\(account\.opening_balance\)",
    "'openingBalance': opening_balance",
    content
)

with open('app/routes/accounting_routes.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed ledger function to handle None opening_balance")
