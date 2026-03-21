from app.models import Account, JournalEntry, JournalLine, Church
from app.extensions import db
from datetime import datetime, timedelta
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

class FinancialStatementService:
    
    def __init__(self, church_id):
        self.church_id = church_id
    
    def get_income_statement(self, start_date, end_date):
        """
        Generate income statement (Revenue - Expenses)
        Returns structured data with categories from Chart of Accounts
        """
        result = {
            'revenue': {
                'categories': {},
                'total': 0
            },
            'expenses': {
                'categories': {},
                'total': 0
            },
            'net_income': 0
        }
        
        # Get all revenue accounts
        revenue_accounts = Account.query.filter(
            Account.church_id == self.church_id,
            (Account.account_type == 'REVENUE') | (Account.account_code.like('4%')),
            Account.is_active == True
        ).order_by(Account.account_code).all()
        
        # Get all expense accounts
        expense_accounts = Account.query.filter(
            Account.church_id == self.church_id,
            (Account.account_type == 'EXPENSE') | (Account.account_code.like('5%')),
            Account.is_active == True
        ).order_by(Account.account_code).all()
        
        # Calculate revenue by category
        for account in revenue_accounts:
            balance = self._get_account_balance_for_period(account.id, start_date, end_date)
            if balance != 0:
                category = account.category or 'Other Income'
                if category not in result['revenue']['categories']:
                    result['revenue']['categories'][category] = {
                        'accounts': [],
                        'total': 0
                    }
                
                result['revenue']['categories'][category]['accounts'].append({
                    'code': account.account_code,
                    'name': account.name,
                    'amount': float(balance)
                })
                result['revenue']['categories'][category]['total'] += float(balance)
                result['revenue']['total'] += float(balance)
        
        # Calculate expenses by category
        for account in expense_accounts:
            balance = self._get_account_balance_for_period(account.id, start_date, end_date)
            if balance != 0:
                category = account.category or 'Other Expenses'
                if category not in result['expenses']['categories']:
                    result['expenses']['categories'][category] = {
                        'accounts': [],
                        'total': 0
                    }
                
                result['expenses']['categories'][category]['accounts'].append({
                    'code': account.account_code,
                    'name': account.name,
                    'amount': float(abs(balance))
                })
                result['expenses']['categories'][category]['total'] += float(abs(balance))
                result['expenses']['total'] += float(abs(balance))
        
        result['net_income'] = result['revenue']['total'] - result['expenses']['total']
        
        return result
    
    def get_balance_sheet(self, as_at_date):
        """
        Generate balance sheet (Assets = Liabilities + Equity)
        Returns structured data with proper categorization
        """
        from datetime import datetime
        
        print(f"\n📊 Generating Balance Sheet as at {as_at_date}")
        
        # Ensure as_at_date is a date object
        if isinstance(as_at_date, datetime):
            as_at_date = as_at_date.date()
        
        result = {
            'assets': {
                'current': [],
                'fixed': [],
                'other': [],
                'total': 0
            },
            'liabilities': {
                'current': [],
                'longTerm': [],
                'total': 0
            },
            'equity': {
                'accounts': [],
                'total': 0
            }
        }
        
        # Get all accounts
        all_accounts = Account.query.filter_by(
            church_id=self.church_id,
            is_active=True
        ).all()
        
        # Get net income for the period up to as_at_date
        year_start = datetime(as_at_date.year, 1, 1).date()
        net_income = 0
        if as_at_date > year_start:
            income_stmt = self.get_income_statement(year_start, as_at_date)
            net_income = income_stmt['net_income']
            print(f"Net income for period: {net_income}")
        
        # Process all accounts
        for account in all_accounts:
            balance = self._get_account_balance_as_at(account.id, as_at_date)
            if balance == 0:
                continue
            
            account_data = {
                'code': account.account_code,
                'name': account.name,
                'amount': float(balance),
                'category': account.category
            }
            
            # Assets
            if account.account_type == 'ASSET' or account.account_code.startswith('1'):
                # Current assets (cash, bank, receivables, inventory)
                if (account.account_code.startswith('1010') or 
                    account.account_code.startswith('1020') or
                    account.account_code.startswith('1030') or
                    account.account_code.startswith('1040') or
                    'cash' in account.name.lower() or
                    'bank' in account.name.lower() or
                    'receivable' in account.name.lower() or
                    'inventory' in account.name.lower() or
                    'stock' in account.name.lower()):
                    result['assets']['current'].append(account_data)
                    print(f"  Current Asset: {account.account_code} - {account.name}: {balance}")
                
                # Fixed assets (property, plant, equipment)
                elif (account.account_code.startswith('15') or
                    'building' in account.name.lower() or
                    'land' in account.name.lower() or
                    'equipment' in account.name.lower() or
                    'vehicle' in account.name.lower() or
                    'furniture' in account.name.lower() or
                    'fixture' in account.name.lower()):
                    result['assets']['fixed'].append(account_data)
                    print(f"  Fixed Asset: {account.account_code} - {account.name}: {balance}")
                
                # Other assets
                else:
                    result['assets']['other'].append(account_data)
                    print(f"  Other Asset: {account.account_code} - {account.name}: {balance}")
                
                result['assets']['total'] += float(balance)
            
            # Liabilities
            elif account.account_type == 'LIABILITY' or account.account_code.startswith('2'):
                # Current liabilities
                if (account.account_code.startswith('2010') or
                    account.account_code.startswith('2020') or
                    'payable' in account.name.lower() or
                    'accrued' in account.name.lower()):
                    result['liabilities']['current'].append(account_data)
                    print(f"  Current Liability: {account.account_code} - {account.name}: {balance}")
                
                # Long-term liabilities
                else:
                    result['liabilities']['longTerm'].append(account_data)
                    print(f"  Long-term Liability: {account.account_code} - {account.name}: {balance}")
                
                result['liabilities']['total'] += float(balance)
            
            # Equity
            elif account.account_type == 'EQUITY' or account.account_code.startswith('3'):
                # For Accumulated Fund/Retained Earnings, add net income
                if 'accumulated' in account.name.lower() or 'retained' in account.name.lower():
                    account_data['amount'] += net_income
                    print(f"  Adding net income {net_income} to {account.name}")
                
                result['equity']['accounts'].append(account_data)
                result['equity']['total'] += account_data['amount']
                print(f"  Equity: {account.account_code} - {account.name}: {account_data['amount']}")
        
        print(f"Assets total: {result['assets']['total']}")
        print(f"Liabilities total: {result['liabilities']['total']}")
        print(f"Equity total: {result['equity']['total']}")
        
        return result

    def get_cash_flow_statement(self, start_date, end_date):
        
        from sqlalchemy import func, Date
        from datetime import datetime, timedelta
        
        print(f"\n💰 Generating Cash Flow Statement for {start_date} to {end_date}")
        
        # Ensure dates are date objects
        if isinstance(start_date, datetime):
            start_date = start_date.date()
        if isinstance(end_date, datetime):
            end_date = end_date.date()
        
        result = {
            'operating': {
                'items': [],
                'net': 0
            },
            'investing': {
                'items': [],
                'net': 0
            },
            'financing': {
                'items': [],
                'net': 0
            },
            'netIncrease': 0,
            'beginningCash': 0,
            'endingCash': 0
        }
        
        # Get cash and bank accounts
        cash_accounts = Account.query.filter(
            Account.church_id == self.church_id,
            (Account.account_code.like('1010%')) | 
            (Account.name.ilike('%cash%')) |
            (Account.name.ilike('%petty%')),
            Account.is_active == True
        ).all()
        
        bank_accounts = Account.query.filter(
            Account.church_id == self.church_id,
            (Account.account_code.like('1020%')) | 
            (Account.name.ilike('%bank%')),
            Account.is_active == True
        ).all()
        
        all_cash_accounts = cash_accounts + bank_accounts
        cash_account_ids = [acc.id for acc in all_cash_accounts]
        print(f"Found {len(all_cash_accounts)} cash/bank accounts")
        
        # Calculate beginning cash balance (day before start_date)
        day_before = start_date - timedelta(days=1)
        for account in all_cash_accounts:
            beginning = self._get_account_balance_as_at(account.id, day_before)
            result['beginningCash'] += beginning
            print(f"  {account.name}: beginning balance = {beginning}")
        
        # Calculate ending cash balance
        for account in all_cash_accounts:
            ending = float(account.current_balance or 0)
            result['endingCash'] += ending
        
        print(f"Beginning cash: {result['beginningCash']}, Ending cash: {result['endingCash']}")
        
        # Operating activities keywords
        operating_keywords = [
            'tithe', 'offering', 'donation', 'salary', 'wage', 'rent', 'utility',
            'electricity', 'water', 'internet', 'phone', 'office', 'supplies',
            'maintenance', 'repair', 'cleaning', 'insurance', 'tax', 'legal',
            'consulting', 'advertising', 'marketing', 'travel', 'meals',
            'training', 'education', 'subscription', 'software', 'hosting',
            'printing', 'postage', 'shipping', 'fuel', 'income', 'revenue',
            'service', 'fee', 'pastor', 'ministry', 'outreach', 'mission'
        ]
        
        # Investing activities keywords
        investing_keywords = [
            'equipment', 'machinery', 'computer', 'hardware', 'server', 'furniture',
            'fixture', 'vehicle', 'car', 'truck', 'building', 'property', 'land',
            'construction', 'renovation', 'improvement', 'leasehold', 'patent',
            'trademark', 'copyright', 'license', 'intangible', 'asset', 'ppe',
            'plant', 'facility', 'warehouse'
        ]
        
        # Financing activities keywords
        financing_keywords = [
            'loan', 'debt', 'borrow', 'mortgage', 'bond', 'note payable', 'interest',
            'dividend', 'distribution', 'equity', 'capital', 'investment', 'stock',
            'share', 'security', 'treasury', 'buyback', 'withdrawal', 'owner',
            'partner', 'member'
        ]
        
        # Get all transactions affecting cash accounts
        if cash_account_ids:
            transactions = db.session.query(
                JournalLine, JournalEntry, Account
            ).join(
                JournalEntry,
                JournalLine.journal_entry_id == JournalEntry.id
            ).join(
                Account,
                JournalLine.account_id == Account.id
            ).filter(
                JournalEntry.church_id == self.church_id,
                func.date(JournalEntry.entry_date) >= start_date,
                func.date(JournalEntry.entry_date) <= end_date,
                JournalEntry.status == 'POSTED',
                JournalLine.account_id.in_(cash_account_ids)
            ).order_by(JournalEntry.entry_date).all()
            
            print(f"Found {len(transactions)} cash transactions in period")
            
            for line, entry, account in transactions:
                # Determine amount and direction
                if line.debit > 0:
                    amount = float(line.debit)
                    direction = 'inflow'
                else:
                    amount = -float(line.credit)
                    direction = 'outflow'
                
                # Find contra account for classification
                contra_line = JournalLine.query.filter(
                    JournalLine.journal_entry_id == entry.id,
                    JournalLine.account_id != account.id
                ).first()
                
                if contra_line:
                    contra_account = Account.query.get(contra_line.account_id)
                    if contra_account:
                        search_text = f"{entry.description or ''} {contra_account.name or ''} {contra_account.category or ''}".lower()
                        
                        item = {
                            'date': entry.entry_date.isoformat(),
                            'accountCode': contra_account.account_code,
                            'accountName': contra_account.name,
                            'description': entry.description or f"Transaction with {contra_account.name}",
                            'amount': amount
                        }
                        
                        # Classify based on contra account
                        if any(kw in search_text for kw in operating_keywords):
                            result['operating']['items'].append(item)
                            result['operating']['net'] += amount
                            print(f"  Operating: {amount}")
                        elif any(kw in search_text for kw in investing_keywords):
                            result['investing']['items'].append(item)
                            result['investing']['net'] += amount
                            print(f"  Investing: {amount}")
                        elif any(kw in search_text for kw in financing_keywords):
                            result['financing']['items'].append(item)
                            result['financing']['net'] += amount
                            print(f"  Financing: {amount}")
                        else:
                            # Default to operating
                            result['operating']['items'].append(item)
                            result['operating']['net'] += amount
                            print(f"  Operating (default): {amount}")
                else:
                    # No contra account found, classify based on entry description
                    search_text = f"{entry.description or ''} {account.name or ''}".lower()
                    item = {
                        'date': entry.entry_date.isoformat(),
                        'description': entry.description or f"Cash movement in {account.name}",
                        'amount': amount
                    }
                    
                    if any(kw in search_text for kw in operating_keywords):
                        result['operating']['items'].append(item)
                        result['operating']['net'] += amount
                    elif any(kw in search_text for kw in investing_keywords):
                        result['investing']['items'].append(item)
                        result['investing']['net'] += amount
                    elif any(kw in search_text for kw in financing_keywords):
                        result['financing']['items'].append(item)
                        result['financing']['net'] += amount
                    else:
                        result['operating']['items'].append(item)
                        result['operating']['net'] += amount
        
        result['netIncrease'] = result['endingCash'] - result['beginningCash']
        
        print(f"Cash flow summary - Operating: {result['operating']['net']}, "
            f"Investing: {result['investing']['net']}, "
            f"Financing: {result['financing']['net']}")
        print(f"Net increase: {result['netIncrease']}")
        
        return result


    def _get_account_balance_for_period(self, account_id, start_date, end_date):
        """
        Get the net change for an account during a period
        Fixed version that handles datetime correctly
        """
        from app.models import JournalEntry, JournalLine
        from sqlalchemy import func
        from datetime import datetime
        
        account = Account.query.get(account_id)
        if not account:
            print(f"⚠️ Account {account_id} not found")
            return 0
        
        # Ensure dates are date objects
        if isinstance(start_date, datetime):
            start_date = start_date.date()
        if isinstance(end_date, datetime):
            end_date = end_date.date()
        
        print(f"🔍 Calculating balance for account {account.account_code} - {account.name}")
        print(f"   Period: {start_date} to {end_date}")
        
        # Use date() function to compare only the date part
        if account.account_type == 'REVENUE' or account.account_code.startswith('4'):
            # Revenue accounts normally have credit balances
            result = db.session.query(
                func.coalesce(func.sum(JournalLine.credit), 0) -
                func.coalesce(func.sum(JournalLine.debit), 0)
            ).join(
                JournalEntry,
                JournalLine.journal_entry_id == JournalEntry.id
            ).filter(
                JournalLine.account_id == account_id,
                func.date(JournalEntry.entry_date) >= start_date,
                func.date(JournalEntry.entry_date) <= end_date,
                JournalEntry.status == 'POSTED'
            ).scalar()
        else:
            # Expense accounts normally have debit balances
            result = db.session.query(
                func.coalesce(func.sum(JournalLine.debit), 0) -
                func.coalesce(func.sum(JournalLine.credit), 0)
            ).join(
                JournalEntry,
                JournalLine.journal_entry_id == JournalEntry.id
            ).filter(
                JournalLine.account_id == account_id,
                func.date(JournalEntry.entry_date) >= start_date,
                func.date(JournalEntry.entry_date) <= end_date,
                JournalEntry.status == 'POSTED'
            ).scalar()
        
        print(f"   Calculation result: {result}")
        return float(result or 0)

    def get_receipt_payment_account(self, start_date, end_date):
        """
        Get receipt and payment account data
        Alias for get_receipt_payments_account to handle naming differences
        """
        print(f"💰 get_receipt_payment_account called - redirecting to get_receipt_payments_account")
        return self.get_receipt_payments_account(start_date, end_date)

    def get_receipt_payments_account(self, start_date, end_date):
        """
        Get receipt and payment account data with detailed breakdown by revenue/expense accounts
        """
        import traceback
        from datetime import datetime, timedelta
        from sqlalchemy import func
        
        print(f"\n{'='*60}")
        print(f"💰 Generating Receipt & Payment Account")
        print(f"{'='*60}")
        print(f"Start Date: {start_date}")
        print(f"End Date: {end_date}")
        print(f"Church ID: {self.church_id}")
        
        try:
            # Ensure dates are date objects
            if isinstance(start_date, datetime):
                start_date = start_date.date()
            if isinstance(end_date, datetime):
                end_date = end_date.date()
            
            print(f"Normalized dates: {start_date} to {end_date}")
            
            result = {
                'openingBalances': {
                    'cashAccounts': [],
                    'bankAccounts': [],
                    'total': 0
                },
                'receipts': {
                    'byAccount': {},  # Grouped by revenue account
                    'total': 0,
                    'items': []
                },
                'payments': {
                    'byAccount': {},  # Grouped by expense account
                    'total': 0,
                    'items': []
                },
                'closingBalances': {
                    'cashAccounts': [],
                    'bankAccounts': [],
                    'total': 0
                }
            }
            
            # Get cash and bank accounts
            print("\n📊 Fetching cash accounts...")
            cash_accounts = Account.query.filter(
                Account.church_id == self.church_id,
                (Account.account_code.like('1010%')) | 
                (Account.name.ilike('%cash%')) |
                (Account.name.ilike('%petty%')),
                Account.is_active == True
            ).all()
            print(f"Found {len(cash_accounts)} cash accounts")
            
            bank_accounts = Account.query.filter(
                Account.church_id == self.church_id,
                (Account.account_code.like('1020%')) | 
                (Account.name.ilike('%bank%')),
                Account.is_active == True
            ).all()
            print(f"Found {len(bank_accounts)} bank accounts")
            
            all_cash_accounts = cash_accounts + bank_accounts
            cash_account_ids = [acc.id for acc in all_cash_accounts]
            print(f"Total cash/bank accounts: {len(all_cash_accounts)}")
            
            # Get all revenue accounts for receipt classification
            revenue_accounts = Account.query.filter(
                Account.church_id == self.church_id,
                (Account.account_type == 'REVENUE') | (Account.account_code.like('4%')),
                Account.is_active == True
            ).all()
            revenue_dict = {acc.id: acc for acc in revenue_accounts}
            print(f"Found {len(revenue_accounts)} revenue accounts")
            
            # Get all expense accounts for payment classification
            expense_accounts = Account.query.filter(
                Account.church_id == self.church_id,
                (Account.account_type == 'EXPENSE') | (Account.account_code.like('5%')),
                Account.is_active == True
            ).all()
            expense_dict = {acc.id: acc for acc in expense_accounts}
            print(f"Found {len(expense_accounts)} expense accounts")
            
            # Calculate opening balances (day before start_date)
            day_before = start_date - timedelta(days=1)
            print(f"\n📅 Opening balances as at {day_before}")
            
            for account in cash_accounts:
                balance = self._get_account_balance_as_at(account.id, day_before)
                result['openingBalances']['cashAccounts'].append({
                    'name': account.name,
                    'code': account.account_code,
                    'openingBalance': float(balance)
                })
                result['openingBalances']['total'] += float(balance)
                print(f"  Cash - {account.name}: {balance}")
            
            for account in bank_accounts:
                balance = self._get_account_balance_as_at(account.id, day_before)
                result['openingBalances']['bankAccounts'].append({
                    'name': account.name,
                    'code': account.account_code,
                    'openingBalance': float(balance)
                })
                result['openingBalances']['total'] += float(balance)
                print(f"  Bank - {account.name}: {balance}")
            
            print(f"Total opening balance: {result['openingBalances']['total']}")
            
            # Get transactions for the period
            print(f"\n📊 Fetching transactions for period {start_date} to {end_date}")
            
            if cash_account_ids:
                transactions = db.session.query(
                    JournalLine, JournalEntry
                ).join(
                    JournalEntry,
                    JournalLine.journal_entry_id == JournalEntry.id
                ).filter(
                    JournalEntry.church_id == self.church_id,
                    func.date(JournalEntry.entry_date) >= start_date,
                    func.date(JournalEntry.entry_date) <= end_date,
                    JournalEntry.status == 'POSTED',
                    JournalLine.account_id.in_(cash_account_ids)
                ).order_by(JournalEntry.entry_date).all()
                
                print(f"Found {len(transactions)} cash transactions")
                
                for line, entry in transactions:
                    # Find the contra account (the other side of the journal entry)
                    contra_line = JournalLine.query.filter(
                        JournalLine.journal_entry_id == entry.id,
                        JournalLine.account_id != line.account_id
                    ).first()
                    
                    if not contra_line:
                        continue
                    
                    contra_account = Account.query.get(contra_line.account_id)
                    if not contra_account:
                        continue
                    
                    if line.debit > 0:  # Receipt (cash increased)
                        amount = float(line.debit)
                        result['receipts']['total'] += amount
                        
                        # Create item with detailed information
                        item = {
                            'date': entry.entry_date.isoformat(),
                            'cashAccount': {
                                'code': Account.query.get(line.account_id).account_code,
                                'name': Account.query.get(line.account_id).name
                            },
                            'contraAccount': {
                                'id': contra_account.id,
                                'code': contra_account.account_code,
                                'name': contra_account.name,
                                'type': contra_account.account_type,
                                'category': contra_account.category
                            },
                            'description': entry.description or 'Receipt',
                            'amount': amount
                        }
                        result['receipts']['items'].append(item)
                        
                        # Group by revenue account
                        account_key = f"{contra_account.account_code} - {contra_account.name}"
                        if account_key not in result['receipts']['byAccount']:
                            result['receipts']['byAccount'][account_key] = {
                                'code': contra_account.account_code,
                                'name': contra_account.name,
                                'type': contra_account.account_type,
                                'category': contra_account.category,
                                'total': 0,
                                'items': []
                            }
                        result['receipts']['byAccount'][account_key]['total'] += amount
                        result['receipts']['byAccount'][account_key]['items'].append(item)
                        
                        print(f"  Receipt: {amount} - {contra_account.account_code} {contra_account.name}")
                        
                    elif line.credit > 0:  # Payment (cash decreased)
                        amount = float(line.credit)
                        result['payments']['total'] += amount
                        
                        # Create item with detailed information
                        item = {
                            'date': entry.entry_date.isoformat(),
                            'cashAccount': {
                                'code': Account.query.get(line.account_id).account_code,
                                'name': Account.query.get(line.account_id).name
                            },
                            'contraAccount': {
                                'id': contra_account.id,
                                'code': contra_account.account_code,
                                'name': contra_account.name,
                                'type': contra_account.account_type,
                                'category': contra_account.category
                            },
                            'description': entry.description or 'Payment',
                            'amount': amount
                        }
                        result['payments']['items'].append(item)
                        
                        # Group by expense account
                        account_key = f"{contra_account.account_code} - {contra_account.name}"
                        if account_key not in result['payments']['byAccount']:
                            result['payments']['byAccount'][account_key] = {
                                'code': contra_account.account_code,
                                'name': contra_account.name,
                                'type': contra_account.account_type,
                                'category': contra_account.category,
                                'total': 0,
                                'items': []
                            }
                        result['payments']['byAccount'][account_key]['total'] += amount
                        result['payments']['byAccount'][account_key]['items'].append(item)
                        
                        print(f"  Payment: {amount} - {contra_account.account_code} {contra_account.name}")
            
            # Calculate closing balances
            print(f"\n📅 Closing balances")
            for account in cash_accounts:
                balance = float(account.current_balance or 0)
                result['closingBalances']['cashAccounts'].append({
                    'name': account.name,
                    'code': account.account_code,
                    'closingBalance': balance
                })
                result['closingBalances']['total'] += balance
                print(f"  Cash - {account.name}: {balance}")
            
            for account in bank_accounts:
                balance = float(account.current_balance or 0)
                result['closingBalances']['bankAccounts'].append({
                    'name': account.name,
                    'code': account.account_code,
                    'closingBalance': balance
                })
                result['closingBalances']['total'] += balance
                print(f"  Bank - {account.name}: {balance}")
            
            result['netCashFlow'] = result['receipts']['total'] - result['payments']['total']
            
            print(f"\n{'='*60}")
            print(f"✅ Receipt & Payment Account Summary")
            print(f"{'='*60}")
            print(f"Opening Balance: {result['openingBalances']['total']}")
            print(f"Total Receipts: {result['receipts']['total']}")
            print(f"  By Account:")
            for account, data in result['receipts']['byAccount'].items():
                print(f"    {account}: {data['total']}")
            print(f"Total Payments: {result['payments']['total']}")
            print(f"  By Account:")
            for account, data in result['payments']['byAccount'].items():
                print(f"    {account}: {data['total']}")
            print(f"Net Cash Flow: {result['netCashFlow']}")
            print(f"Closing Balance: {result['closingBalances']['total']}")
            print(f"{'='*60}")
            
            return result
            
        except Exception as e:
            print(f"\n❌ UNHANDLED ERROR in get_receipt_payments_account:")
            print(f"Error: {str(e)}")
            traceback.print_exc()
            
            # Return empty result instead of crashing
            return {
                'openingBalances': {'cashAccounts': [], 'bankAccounts': [], 'total': 0},
                'receipts': {'byAccount': {}, 'total': 0, 'items': []},
                'payments': {'byAccount': {}, 'total': 0, 'items': []},
                'closingBalances': {'cashAccounts': [], 'bankAccounts': [], 'total': 0},
                'netCashFlow': 0
        }
      
    def _get_account_balance_as_at(self, account_id, as_at_date):
        """
        Get account balance as at a specific date
        Includes opening balance + all transactions up to that date
        """
        from app.models import JournalEntry, JournalLine
        
        # Get opening balance
        account = Account.query.get(account_id)
        if not account:
            return 0
        opening = float(account.opening_balance or 0)
        
        # Get net transactions up to as_at_date
        transactions = db.session.query(
            db.func.coalesce(db.func.sum(JournalLine.debit), 0) -
            db.func.coalesce(db.func.sum(JournalLine.credit), 0)
        ).join(
            JournalEntry,
            JournalLine.journal_entry_id == JournalEntry.id
        ).filter(
            JournalLine.account_id == account_id,
            JournalEntry.entry_date <= as_at_date,
            JournalEntry.status == 'POSTED'
        ).scalar()
        
        return opening + float(transactions or 0)
    
    def get_trial_balance(self, as_at_date):
        """
        Generate trial balance as at a specific date
        """
        accounts = Account.query.filter_by(
            church_id=self.church_id,
            is_active=True
        ).order_by(Account.account_code).all()
        
        account_list = []
        total_debits = 0
        total_credits = 0
        
        for acc in accounts:
            balance = self._get_account_balance_as_at(acc.id, as_at_date)
            
            # Determine if the balance is debit or credit based on account type
            if acc.account_type in ['ASSET', 'EXPENSE']:
                if balance >= 0:
                    debit = balance
                    credit = 0
                else:
                    debit = 0
                    credit = abs(balance)
            else:  # LIABILITY, EQUITY, REVENUE
                if balance >= 0:
                    debit = 0
                    credit = balance
                else:
                    debit = abs(balance)
                    credit = 0
            
            total_debits += debit
            total_credits += credit
            
            account_list.append({
                'id': acc.id,
                'code': acc.account_code,
                'name': acc.name,
                'type': acc.account_type,
                'category': acc.category,
                'debit': float(debit),
                'credit': float(credit),
                'balance': float(balance)
            })
        
        return {
            'accounts': account_list,
            'total_debits': float(total_debits),
            'total_credits': float(total_credits),
            'difference': float(total_debits - total_credits),
            'is_balanced': abs(total_debits - total_credits) < 0.01,
            'as_at': as_at_date.isoformat() if isinstance(as_at_date, datetime) else str(as_at_date)
        }
    
    def get_general_ledger(self, account_id, start_date=None, end_date=None):
        """
        Get general ledger entries for a specific account
        """
        account = Account.query.filter_by(
            id=account_id,
            church_id=self.church_id
        ).first()
        
        if not account:
            return None
        
        query = db.session.query(
            JournalLine, JournalEntry
        ).join(
            JournalEntry,
            JournalLine.journal_entry_id == JournalEntry.id
        ).filter(
            JournalLine.account_id == account_id,
            JournalEntry.church_id == self.church_id,
            JournalEntry.status == 'POSTED'
        )
        
        if start_date:
            query = query.filter(JournalEntry.entry_date >= start_date)
        
        if end_date:
            end = end_date.replace(hour=23, minute=59, second=59) if isinstance(end_date, datetime) else end_date
            query = query.filter(JournalEntry.entry_date <= end)
        
        results = query.order_by(JournalEntry.entry_date).all()
        
        # Calculate running balance
        entries = []
        running_balance = float(account.opening_balance)
        
        # Add opening balance entry
        if results or account.opening_balance != 0:
            entries.append({
                'id': None,
                'date': start_date.isoformat() if start_date else account.created_at.isoformat(),
                'description': 'Opening Balance',
                'reference': 'OPENING',
                'debit': 0,
                'credit': 0,
                'balance': running_balance,
                'is_opening': True
            })
        
        for line, entry in results:
            if line.debit > 0:
                running_balance += float(line.debit)
            else:
                running_balance -= float(line.credit)
            
            entries.append({
                'id': line.id,
                'date': entry.entry_date.isoformat(),
                'description': entry.description,
                'reference': entry.entry_number,
                'debit': float(line.debit),
                'credit': float(line.credit),
                'balance': running_balance
            })
        
        # Calculate summary
        total_debit = sum(e['debit'] for e in entries if not e.get('is_opening'))
        total_credit = sum(e['credit'] for e in entries if not e.get('is_opening'))
        
        return {
            'account': {
                'id': account.id,
                'code': account.account_code,
                'name': account.name,
                'type': account.account_type
            },
            'entries': entries,
            'summary': {
                'opening_balance': float(account.opening_balance),
                'total_debit': float(total_debit),
                'total_credit': float(total_credit),
                'closing_balance': float(running_balance)
            }
        }