# app/utils/account_classifier.py
"""
Utility for classifying accounts based on Chart of Accounts structure
Helps determine account types, categories, and behaviors for financial statements
"""
from app.models.chart_of_accounts import CHART_OF_ACCOUNTS, CATEGORY_GROUPS

class AccountClassifier:
    """
    Classifies accounts for financial statement generation and validation
    """
    
    # Account type groups for financial statements
    BALANCE_SHEET_TYPES = ['ASSET', 'LIABILITY', 'EQUITY']
    INCOME_STATEMENT_TYPES = ['REVENUE', 'EXPENSE']
    
    # Normal balance rules
    NORMAL_BALANCE = {
        'ASSET': 'debit',
        'EXPENSE': 'debit',
        'LIABILITY': 'credit',
        'EQUITY': 'credit',
        'REVENUE': 'credit'
    }
    
    @classmethod
    def get_account_type(cls, account_code):
        """
        Determine account type from account code prefix
        Based on standard accounting code ranges
        """
        if not account_code:
            return None
        
        # Convert to string and get first digit
        code_str = str(account_code)
        first_digit = code_str[0] if code_str else '0'
        
        # Map first digit to account type
        type_map = {
            '1': 'ASSET',
            '2': 'LIABILITY',
            '3': 'EQUITY',
            '4': 'REVENUE',
            '5': 'EXPENSE',
            '6': 'EXPENSE',  # Some charts use 6 for expenses
        }
        
        return type_map.get(first_digit, 'EXPENSE')
    
    @classmethod
    def get_category_group(cls, account_code, account_type=None):
        """
        Get the category group for an account (for financial statement grouping)
        """
        if not account_code:
            return 'Other'
        
        code_str = str(account_code)
        
        # Check income categories
        for group_name, codes in CATEGORY_GROUPS.get('income', {}).items():
            if code_str in codes:
                return group_name
        
        # Check expense categories
        for group_name, codes in CATEGORY_GROUPS.get('expenses', {}).items():
            if code_str in codes:
                return group_name
        
        # Default by account type
        if account_type == 'REVENUE':
            return 'Other Income'
        elif account_type == 'EXPENSE':
            return 'Other Expenses'
        elif account_type == 'ASSET':
            return 'Other Assets'
        elif account_type == 'LIABILITY':
            return 'Other Liabilities'
        elif account_type == 'EQUITY':
            return 'Equity'
        
        return 'Other'
    
    @classmethod
    def is_contra_account(cls, account_name, account_code=None):
        """
        Determine if an account is a contra account
        (reduces the balance of another account)
        """
        contra_keywords = [
            'accumulated depreciation',
            'allowance for doubtful',
            'contra',
            'discount',
            'returns',
            'allowances'
        ]
        
        account_name_lower = account_name.lower()
        for keyword in contra_keywords:
            if keyword in account_name_lower:
                return True
        
        # Check by code pattern (some charts use 1xxx for contra)
        if account_code and str(account_code).startswith('19'):
            return True
        
        return False
    
    @classmethod
    def get_normal_balance(cls, account_type, is_contra=False):
        """
        Get the normal balance side for an account type
        """
        normal = cls.NORMAL_BALANCE.get(account_type, 'debit')
        
        # Contra accounts have opposite normal balance
        if is_contra:
            return 'credit' if normal == 'debit' else 'debit'
        
        return normal
    
    @classmethod
    def classify_asset_type(cls, account):
        """
        Classify assets into current/fixed/other for balance sheet
        """
        if account.account_type != 'ASSET':
            return None
        
        category = (account.category or '').lower()
        name = (account.name or '').lower()
        code = str(account.account_code or '')
        
        # Current Assets
        if any(keyword in category or keyword in name for keyword in 
               ['cash', 'bank', 'receivable', 'inventory', 'prepaid', 'current']):
            return 'current'
        
        # Fixed Assets
        if any(keyword in category or keyword in name for keyword in 
               ['fixed', 'property', 'plant', 'equipment', 'building', 'land', 
                'vehicle', 'furniture', 'fixture', 'tangible']):
            return 'fixed'
        
        # By code range (1000-1499 often current, 1500+ fixed)
        if code and len(code) >= 4:
            code_prefix = code[:2]
            if code_prefix in ['10', '11', '12', '13', '14']:
                return 'current'
            elif code_prefix in ['15', '16', '17', '18']:
                return 'fixed'
        
        return 'other'
    
    @classmethod
    def classify_liability_type(cls, account):
        """
        Classify liabilities into current/long-term for balance sheet
        """
        if account.account_type != 'LIABILITY':
            return None
        
        category = (account.category or '').lower()
        name = (account.name or '').lower()
        code = str(account.account_code or '')
        
        # Current Liabilities
        if any(keyword in category or keyword in name for keyword in 
               ['payable', 'accrued', 'tax', 'current', 'short-term']):
            return 'current'
        
        # Long-term Liabilities
        if any(keyword in category or keyword in name for keyword in 
               ['loan', 'mortgage', 'long-term', 'note', 'bond']):
            return 'long_term'
        
        # By code range (2000-2499 often current, 2500+ long-term)
        if code and len(code) >= 4:
            code_prefix = code[:2]
            if code_prefix in ['20', '21', '22', '23', '24']:
                return 'current'
            elif code_prefix in ['25', '26', '27', '28', '29']:
                return 'long_term'
        
        return 'current'  # Default to current
    
    @classmethod
    def get_statement_section(cls, account):
        """
        Determine which financial statement section an account belongs to
        """
        if account.account_type in cls.INCOME_STATEMENT_TYPES:
            return 'income_statement'
        elif account.account_type in cls.BALANCE_SHEET_TYPES:
            return 'balance_sheet'
        else:
            return 'other'
    
    @classmethod
    def validate_account_structure(cls, accounts):
        """
        Validate a list of accounts for proper structure
        Returns list of issues found
        """
        issues = []
        account_codes = set()
        
        for acc in accounts:
            # Check for duplicate codes
            if acc.account_code in account_codes:
                issues.append(f"Duplicate account code: {acc.account_code}")
            account_codes.add(acc.account_code)
            
            # Validate account type
            if acc.account_type not in cls.NORMAL_BALANCE:
                issues.append(f"Invalid account type for {acc.account_code}: {acc.account_type}")
            
            # Check for missing category
            if not acc.category and acc.account_type in ['REVENUE', 'EXPENSE']:
                issues.append(f"Missing category for {acc.account_code}: {acc.name}")
            
            # Validate parent-child relationships
            if acc.parent_account_id:
                parent = next((a for a in accounts if a.id == acc.parent_account_id), None)
                if not parent:
                    issues.append(f"Parent account not found for {acc.account_code}")
                elif parent.account_type != acc.account_type:
                    issues.append(f"Parent account type mismatch for {acc.account_code}")
        
        return issues
    
    @classmethod
    def suggest_account_code(cls, account_type, category=None):
        """
        Suggest an appropriate account code based on type and category
        """
        # Base ranges by type
        ranges = {
            'ASSET': (1000, 1999),
            'LIABILITY': (2000, 2999),
            'EQUITY': (3000, 3999),
            'REVENUE': (4000, 4999),
            'EXPENSE': (5000, 5999),
        }
        
        # Sub-ranges by category
        category_ranges = {
            'Cash': (1010, 1099),
            'Bank': (1100, 1199),
            'Receivables': (1200, 1299),
            'Inventory': (1300, 1399),
            'Investments': (1400, 1499),
            'Tangible Assets': (1500, 1599),
            'Intangible Assets': (1600, 1699),
            
            'Payables': (2010, 2099),
            'Accruals': (2100, 2199),
            'Taxes': (2200, 2299),
            'Loans': (2300, 2399),
            
            'Accumulated Fund': (3010, 3099),
            'Retained Earnings': (3100, 3199),
            
            'Tithes': (4010, 4019),
            'Offerings': (4020, 4099),
            'Donations': (4100, 4199),
            'Other Income': (4900, 4999),
            
            'Staff Cost': (5010, 5099),
            'Office Expenses': (5100, 5199),
            'Utilities': (5200, 5299),
            'Repairs': (5300, 5399),
            'Ministry Expenses': (5400, 5499),
        }
        
        if category and category in category_ranges:
            start, end = category_ranges[category]
            return f"{start}"
        elif account_type in ranges:
            start, end = ranges[account_type]
            return f"{start}"
        
        return "0000"