# app/models/chart_of_accounts.py
"""
Chart of Accounts based on the church accounting document
"""

# ==================== REVENUE ACCOUNTS ====================
REVENUE_ACCOUNTS = [
    # Main Revenue Categories
    {'code': '4010', 'name': 'Tithes', 'category': 'Tithes', 'normal_balance': 'credit'},
    {'code': '4020', 'name': 'Thanks Offering', 'category': 'Thanks Offering', 'normal_balance': 'credit'},
    {'code': '4030', 'name': 'Harvest Proceeds', 'category': 'Harvest Proceeds', 'normal_balance': 'credit'},
    {'code': '4040', 'name': 'Statutory Income', 'category': 'Statutory Income', 'normal_balance': 'credit'},
    {'code': '4050', 'name': 'Cemetery Income', 'category': 'Cemetery Income', 'normal_balance': 'credit'},
    {'code': '4060', 'name': 'Special Offering', 'category': 'Special Offering', 'normal_balance': 'credit'},
    {'code': '4070', 'name': 'Donations Received', 'category': 'Donations Received', 'normal_balance': 'credit'},
    {'code': '4080', 'name': 'Adults\' Normal Offering', 'category': 'Adults Offering', 'normal_balance': 'credit'},
    {'code': '4090', 'name': 'Junior Youth Offering', 'category': 'Youth Offering', 'normal_balance': 'credit'},
    {'code': '4100', 'name': 'Children Service Offering', 'category': 'Children Offering', 'normal_balance': 'credit'},
    {'code': '4110', 'name': 'Welfare Income', 'category': 'Welfare', 'normal_balance': 'credit'},
    {'code': '4120', 'name': 'Scholarship Income', 'category': 'Scholarship', 'normal_balance': 'credit'},
    {'code': '4130', 'name': 'Interest Income', 'category': 'Interest', 'normal_balance': 'credit'},
    {'code': '4190', 'name': 'Other Income', 'category': 'Other Income', 'normal_balance': 'credit'},
]

# ==================== EXPENSE ACCOUNTS ====================
EXPENSE_ACCOUNTS = [
    # Staff Costs
    {'code': '5010', 'name': 'Income Contribution', 'category': 'Income Contribution', 'normal_balance': 'debit'},
    {'code': '5020', 'name': 'Staff Cost - Salaries', 'category': 'Staff Cost', 'sub_category': 'Salaries', 'normal_balance': 'debit'},
    {'code': '5021', 'name': 'Staff Cost - Wages', 'category': 'Staff Cost', 'sub_category': 'Wages', 'normal_balance': 'debit'},
    {'code': '5022', 'name': 'Staff Cost - Benefits', 'category': 'Staff Cost', 'sub_category': 'Benefits', 'normal_balance': 'debit'},
    {'code': '5023', 'name': 'Staff Cost - Allowances', 'category': 'Staff Cost', 'sub_category': 'Allowances', 'normal_balance': 'debit'},
    
    # Administrative Expenses
    {'code': '5030', 'name': 'Printing and Stationeries', 'category': 'Office Expenses', 'normal_balance': 'debit'},
    {'code': '5040', 'name': 'Transportation', 'category': 'Transportation', 'normal_balance': 'debit'},
    {'code': '5050', 'name': 'Utilities', 'category': 'Utilities', 'normal_balance': 'debit'},
    {'code': '5060', 'name': 'General Repairs and Maintenance', 'category': 'Repairs', 'sub_category': 'General', 'normal_balance': 'debit'},
    {'code': '5070', 'name': 'Chapel Repairs and Maintenance', 'category': 'Repairs', 'sub_category': 'Chapel', 'normal_balance': 'debit'},
    {'code': '5080', 'name': 'Manse Repairs and Maintenance', 'category': 'Repairs', 'sub_category': 'Manse', 'normal_balance': 'debit'},
    
    # Ministry Expenses
    {'code': '5090', 'name': 'Evangelism Expenses', 'category': 'Evangelism', 'normal_balance': 'debit'},
    {'code': '5100', 'name': 'Conference and Meetings', 'category': 'Meetings', 'normal_balance': 'debit'},
    {'code': '5110', 'name': 'Eucharist', 'category': 'Eucharist', 'normal_balance': 'debit'},
    {'code': '5120', 'name': 'Donations Given', 'category': 'Donations', 'normal_balance': 'debit'},
    {'code': '5130', 'name': 'Training and Courses', 'category': 'Training', 'normal_balance': 'debit'},
    {'code': '5140', 'name': 'Entertainment and Hospitality', 'category': 'Hospitality', 'normal_balance': 'debit'},
    
    # General Expenses
    {'code': '5150', 'name': 'General and Admin Expenses', 'category': 'Administrative', 'normal_balance': 'debit'},
    {'code': '5160', 'name': 'Professional Charges', 'category': 'Professional Fees', 'normal_balance': 'debit'},
    {'code': '5170', 'name': 'Bank Charges', 'category': 'Bank Charges', 'normal_balance': 'debit'},
    {'code': '5180', 'name': 'Harvest Expense', 'category': 'Harvest', 'normal_balance': 'debit'},
    {'code': '5190', 'name': 'Sundry Expense', 'category': 'Sundry', 'normal_balance': 'debit'},
    {'code': '5200', 'name': 'Depreciation', 'category': 'Depreciation', 'normal_balance': 'debit'},
]

# ==================== ASSET ACCOUNTS ====================
ASSET_ACCOUNTS = [
    # Current Assets
    {'code': '1010', 'name': 'Cash - Petty Cash', 'category': 'Cash', 'normal_balance': 'debit'},
    {'code': '1020', 'name': 'Cash - Main Cash', 'category': 'Cash', 'normal_balance': 'debit'},
    {'code': '1110', 'name': 'Bank - Current Account', 'category': 'Bank', 'normal_balance': 'debit'},
    {'code': '1120', 'name': 'Bank - Savings Account', 'category': 'Bank', 'normal_balance': 'debit'},
    {'code': '1130', 'name': 'Bank - Fixed Deposit', 'category': 'Bank', 'normal_balance': 'debit'},
    {'code': '1210', 'name': 'Accounts Receivable', 'category': 'Receivables', 'normal_balance': 'debit'},
    {'code': '1220', 'name': 'Stock/Inventory', 'category': 'Inventory', 'normal_balance': 'debit'},
    {'code': '1230', 'name': 'Investments - Short Term', 'category': 'Investments', 'normal_balance': 'debit'},
    
    # Non-Current Assets
    {'code': '1410', 'name': 'Investments - Long Term', 'category': 'Investments', 'normal_balance': 'debit'},
    {'code': '1510', 'name': 'Land', 'category': 'Tangible Assets', 'sub_category': 'Land', 'normal_balance': 'debit'},
    {'code': '1520', 'name': 'Buildings - Chapel', 'category': 'Tangible Assets', 'sub_category': 'Buildings', 'normal_balance': 'debit'},
    {'code': '1530', 'name': 'Buildings - Manse', 'category': 'Tangible Assets', 'sub_category': 'Buildings', 'normal_balance': 'debit'},
    {'code': '1540', 'name': 'Vehicles', 'category': 'Tangible Assets', 'sub_category': 'Vehicles', 'normal_balance': 'debit'},
    {'code': '1550', 'name': 'Furniture and Fixtures', 'category': 'Tangible Assets', 'sub_category': 'Furniture', 'normal_balance': 'debit'},
    {'code': '1560', 'name': 'Computers and Equipment', 'category': 'Tangible Assets', 'sub_category': 'Equipment', 'normal_balance': 'debit'},
    {'code': '1570', 'name': 'Church Equipment', 'category': 'Tangible Assets', 'sub_category': 'Equipment', 'normal_balance': 'debit'},
    
    # Contra Assets
    {'code': '1910', 'name': 'Accumulated Depreciation - Buildings', 'category': 'Depreciation', 'is_contra': True, 'normal_balance': 'credit'},
    {'code': '1920', 'name': 'Accumulated Depreciation - Vehicles', 'category': 'Depreciation', 'is_contra': True, 'normal_balance': 'credit'},
    {'code': '1930', 'name': 'Accumulated Depreciation - Equipment', 'category': 'Depreciation', 'is_contra': True, 'normal_balance': 'credit'},
]

# ==================== LIABILITY ACCOUNTS ====================
LIABILITY_ACCOUNTS = [
    # Current Liabilities
    {'code': '2010', 'name': 'Accounts Payable', 'category': 'Payables', 'normal_balance': 'credit'},
    {'code': '2020', 'name': 'Accrued Expenses', 'category': 'Accruals', 'normal_balance': 'credit'},
    {'code': '2030', 'name': 'PAYE Payable', 'category': 'Taxes', 'normal_balance': 'credit'},
    {'code': '2040', 'name': 'SSNIT Payable', 'category': 'Statutory', 'normal_balance': 'credit'},
    {'code': '2050', 'name': 'Tithe Payable', 'category': 'Payables', 'normal_balance': 'credit'},
    
    # Long-term Liabilities
    {'code': '2310', 'name': 'Loans - Bank', 'category': 'Loans', 'normal_balance': 'credit'},
    {'code': '2320', 'name': 'Loans - Members', 'category': 'Loans', 'normal_balance': 'credit'},
    {'code': '2330', 'name': 'Mortgages', 'category': 'Loans', 'normal_balance': 'credit'},
]

# ==================== EQUITY ACCOUNTS ====================
EQUITY_ACCOUNTS = [
    {'code': '3010', 'name': 'Accumulated Fund', 'category': 'Accumulated Fund', 'normal_balance': 'credit'},
    {'code': '3020', 'name': 'Retained Earnings', 'category': 'Retained Earnings', 'normal_balance': 'credit'},
    {'code': '3090', 'name': 'Current Year Surplus/Deficit', 'category': 'Temporary', 'normal_balance': 'credit'},
]

# Complete Chart of Accounts
CHART_OF_ACCOUNTS = {
    'REVENUE': REVENUE_ACCOUNTS,
    'EXPENSE': EXPENSE_ACCOUNTS,
    'ASSET': ASSET_ACCOUNTS,
    'LIABILITY': LIABILITY_ACCOUNTS,
    'EQUITY': EQUITY_ACCOUNTS,
}

# Account type mapping for statements
ACCOUNT_TYPE_MAPPING = {
    # For Income Statement
    'REVENUE': 'income_statement',
    'EXPENSE': 'income_statement',
    
    # For Balance Sheet
    'ASSET': 'balance_sheet',
    'LIABILITY': 'balance_sheet',
    'EQUITY': 'balance_sheet',
}

# Category grouping for financial statements
CATEGORY_GROUPS = {
    'income': {
        'Tithes': ['4010'],
        'Offerings': ['4020', '4060', '4080', '4090', '4100'],
        'Donations': ['4070'],
        'Special Income': ['4030', '4040', '4050', '4110', '4120', '4130', '4190'],
    },
    'expenditure': {
        'Staff Costs': ['5020', '5021', '5022', '5023'],
        'Operational Expenses': ['5030', '5040', '5050', '5060', '5070', '5080'],
        'Ministry Expenses': ['5090', '5100', '5110', '5120', '5130', '5140'],
        'Administrative Expenses': ['5150', '5160'],
        'Financial Costs': ['5170'],
        'Other Expenses': ['5010', '5180', '5190', '5200'],
    }
}