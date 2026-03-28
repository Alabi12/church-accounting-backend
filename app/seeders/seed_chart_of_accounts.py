# app/seeders/seed_chart_of_accounts.py
from app.extensions import db
from app.models.account import Account

def seed_chart_of_accounts(church_id):
    """Seed the complete chart of accounts for a church"""
    
    # Delete existing accounts for this church to start fresh
    deleted = Account.query.filter_by(church_id=church_id).delete()
    print(f"Deleted {deleted} existing accounts")
    
    all_accounts = [
        # ASSET ACCOUNTS (15)
        {'code': '1010', 'name': 'Cash', 'type': 'ASSET', 'category': 'Cash', 'normal_balance': 'debit'},
        {'code': '1020', 'name': 'Bank', 'type': 'ASSET', 'category': 'Bank', 'normal_balance': 'debit'},
        {'code': '1030', 'name': 'Accounts Receivable', 'type': 'ASSET', 'category': 'Receivables', 'normal_balance': 'debit'},
        {'code': '1040', 'name': 'Stock', 'type': 'ASSET', 'category': 'Inventory', 'normal_balance': 'debit'},
        {'code': '1050', 'name': 'Investment', 'type': 'ASSET', 'category': 'Investments', 'normal_balance': 'debit'},
        {'code': '1510', 'name': 'Land', 'type': 'ASSET', 'category': 'Tangible Assets', 'sub_category': 'Land', 'normal_balance': 'debit'},
        {'code': '1520', 'name': 'Buildings - Chapel', 'type': 'ASSET', 'category': 'Tangible Assets', 'sub_category': 'Buildings', 'normal_balance': 'debit'},
        {'code': '1530', 'name': 'Buildings - Manse', 'type': 'ASSET', 'category': 'Tangible Assets', 'sub_category': 'Buildings', 'normal_balance': 'debit'},
        {'code': '1540', 'name': 'Vehicles', 'type': 'ASSET', 'category': 'Tangible Assets', 'sub_category': 'Vehicles', 'normal_balance': 'debit'},
        {'code': '1550', 'name': 'Furniture and Fixtures', 'type': 'ASSET', 'category': 'Tangible Assets', 'sub_category': 'Furniture', 'normal_balance': 'debit'},
        {'code': '1560', 'name': 'Computers and Equipment', 'type': 'ASSET', 'category': 'Tangible Assets', 'sub_category': 'Equipment', 'normal_balance': 'debit'},
        {'code': '1570', 'name': 'Church Equipment', 'type': 'ASSET', 'category': 'Tangible Assets', 'sub_category': 'Equipment', 'normal_balance': 'debit'},
        {'code': '1910', 'name': 'Accumulated Depreciation - Buildings', 'type': 'ASSET', 'category': 'Depreciation', 'normal_balance': 'credit', 'is_contra': True},
        {'code': '1920', 'name': 'Accumulated Depreciation - Vehicles', 'type': 'ASSET', 'category': 'Depreciation', 'normal_balance': 'credit', 'is_contra': True},
        {'code': '1930', 'name': 'Accumulated Depreciation - Equipment', 'type': 'ASSET', 'category': 'Depreciation', 'normal_balance': 'credit', 'is_contra': True},
        
        # LIABILITY ACCOUNTS (5)
        {'code': '2010', 'name': 'Accounts Payable', 'type': 'LIABILITY', 'category': 'Payables', 'normal_balance': 'credit'},
        {'code': '2020', 'name': 'Loans', 'type': 'LIABILITY', 'category': 'Loans', 'normal_balance': 'credit'},
        {'code': '2030', 'name': 'Accrued Expense', 'type': 'LIABILITY', 'category': 'Accruals', 'normal_balance': 'credit'},
        {'code': '2040', 'name': 'PAYE Payable', 'type': 'LIABILITY', 'category': 'Taxes', 'normal_balance': 'credit'},
        {'code': '2050', 'name': 'SSNIT Payable', 'type': 'LIABILITY', 'category': 'Statutory', 'normal_balance': 'credit'},
        
        # EQUITY ACCOUNTS (3)
        {'code': '3010', 'name': 'Accumulated Fund', 'type': 'EQUITY', 'category': 'Accumulated Fund', 'normal_balance': 'credit'},
        {'code': '3020', 'name': 'Retained Earnings', 'type': 'EQUITY', 'category': 'Retained Earnings', 'normal_balance': 'credit'},
        {'code': '3090', 'name': 'Current Year Surplus/Deficit', 'type': 'EQUITY', 'category': 'Temporary', 'normal_balance': 'credit'},
        
        # REVENUE ACCOUNTS (14)
        {'code': '4010', 'name': 'Tithes', 'type': 'REVENUE', 'category': 'Tithes', 'normal_balance': 'credit'},
        {'code': '4020', 'name': 'Thanks Offering', 'type': 'REVENUE', 'category': 'Thanks Offering', 'normal_balance': 'credit'},
        {'code': '4030', 'name': 'Harvest Proceeds', 'type': 'REVENUE', 'category': 'Harvest Proceeds', 'normal_balance': 'credit'},
        {'code': '4040', 'name': 'Statutory Income', 'type': 'REVENUE', 'category': 'Statutory Income', 'normal_balance': 'credit'},
        {'code': '4050', 'name': 'Cemetery Income', 'type': 'REVENUE', 'category': 'Cemetery Income', 'normal_balance': 'credit'},
        {'code': '4060', 'name': 'Special Offering', 'type': 'REVENUE', 'category': 'Special Offering', 'normal_balance': 'credit'},
        {'code': '4070', 'name': 'Donations Received', 'type': 'REVENUE', 'category': 'Donations Received', 'normal_balance': 'credit'},
        {'code': '4080', 'name': 'Adults\' Normal Offering', 'type': 'REVENUE', 'category': 'Adults Offering', 'normal_balance': 'credit'},
        {'code': '4090', 'name': 'Junior Youth Offering', 'type': 'REVENUE', 'category': 'Youth Offering', 'normal_balance': 'credit'},
        {'code': '4100', 'name': 'Children Service Offering', 'type': 'REVENUE', 'category': 'Children Offering', 'normal_balance': 'credit'},
        {'code': '4110', 'name': 'Welfare Income', 'type': 'REVENUE', 'category': 'Welfare', 'normal_balance': 'credit'},
        {'code': '4120', 'name': 'Scholarship Income', 'type': 'REVENUE', 'category': 'Scholarship', 'normal_balance': 'credit'},
        {'code': '4130', 'name': 'Interest Income', 'type': 'REVENUE', 'category': 'Interest', 'normal_balance': 'credit'},
        {'code': '4190', 'name': 'Other Income', 'type': 'REVENUE', 'category': 'Other Income', 'normal_balance': 'credit'},
        
        # EXPENSE ACCOUNTS (21)
        {'code': '5010', 'name': 'Income Contribution', 'type': 'EXPENSE', 'category': 'Income Contribution', 'normal_balance': 'debit'},
        {'code': '5020', 'name': 'Cemetery', 'type': 'EXPENSE', 'category': 'Cemetery', 'normal_balance': 'debit'},
        {'code': '5030', 'name': 'Staff Cost', 'type': 'EXPENSE', 'category': 'Staff Cost', 'normal_balance': 'debit'},
        {'code': '5040', 'name': 'Printing and Stationeries', 'type': 'EXPENSE', 'category': 'Office Expenses', 'normal_balance': 'debit'},
        {'code': '5050', 'name': 'Transportation', 'type': 'EXPENSE', 'category': 'Transportation', 'normal_balance': 'debit'},
        {'code': '5060', 'name': 'Utilities', 'type': 'EXPENSE', 'category': 'Utilities', 'normal_balance': 'debit'},
        {'code': '5070', 'name': 'General Repairs and Maintenance', 'type': 'EXPENSE', 'category': 'Repairs', 'sub_category': 'General', 'normal_balance': 'debit'},
        {'code': '5080', 'name': 'Chapel Repairs and Maintenance', 'type': 'EXPENSE', 'category': 'Repairs', 'sub_category': 'Chapel', 'normal_balance': 'debit'},
        {'code': '5090', 'name': 'Manse Repairs and Maintenance', 'type': 'EXPENSE', 'category': 'Repairs', 'sub_category': 'Manse', 'normal_balance': 'debit'},
        {'code': '5100', 'name': 'Evangelism Expenses', 'type': 'EXPENSE', 'category': 'Evangelism', 'normal_balance': 'debit'},
        {'code': '5110', 'name': 'Conference and Meetings', 'type': 'EXPENSE', 'category': 'Meetings', 'normal_balance': 'debit'},
        {'code': '5120', 'name': 'Eucharist', 'type': 'EXPENSE', 'category': 'Eucharist', 'normal_balance': 'debit'},
        {'code': '5130', 'name': 'Donations', 'type': 'EXPENSE', 'category': 'Donations', 'normal_balance': 'debit'},
        {'code': '5140', 'name': 'Training and Courses', 'type': 'EXPENSE', 'category': 'Training', 'normal_balance': 'debit'},
        {'code': '5150', 'name': 'Entertainment and Hospitality', 'type': 'EXPENSE', 'category': 'Hospitality', 'normal_balance': 'debit'},
        {'code': '5160', 'name': 'General and Admin. Expenses', 'type': 'EXPENSE', 'category': 'Administrative', 'normal_balance': 'debit'},
        {'code': '5170', 'name': 'Professional Charges', 'type': 'EXPENSE', 'category': 'Professional Fees', 'normal_balance': 'debit'},
        {'code': '5180', 'name': 'Bank Charges', 'type': 'EXPENSE', 'category': 'Bank Charges', 'normal_balance': 'debit'},
        {'code': '5190', 'name': 'Harvest Expense', 'type': 'EXPENSE', 'category': 'Harvest', 'normal_balance': 'debit'},
        {'code': '5200', 'name': 'Sundry Expense', 'type': 'EXPENSE', 'category': 'Sundry', 'normal_balance': 'debit'},
        {'code': '5210', 'name': 'Depreciation', 'type': 'EXPENSE', 'category': 'Depreciation', 'normal_balance': 'debit'},
    ]
    
    # Create all accounts
    created = 0
    for acc_data in all_accounts:
        try:
            account = Account(
                church_id=church_id,
                account_code=acc_data['code'],
                name=acc_data['name'],
                display_name=f"{acc_data['code']} - {acc_data['name']}",
                account_type=acc_data['type'],
                category=acc_data.get('category'),
                sub_category=acc_data.get('sub_category'),
                level=2,
                opening_balance=0,
                current_balance=0,
                normal_balance=acc_data['normal_balance'],
                description=f"Standard {acc_data['type'].lower()} account: {acc_data['name']}",
                is_active=True,
                is_contra=acc_data.get('is_contra', False)
            )
            db.session.add(account)
            created += 1
        except Exception as e:
            print(f"Error creating {acc_data['code']}: {e}")
    
    db.session.commit()
    print(f"✅ Created {created} accounts for church {church_id}")
    return created