import re

with open('app/routes/accounting_routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add trial balance export handling to the export function
# Find where trialbalance is handled and fix it

# Replace the trialbalance section
new_trialbalance_section = '''
        elif statement_type == 'trialbalance' or statement_type == 'trial-balance':
            if not end_date_str:
                return jsonify({'error': 'End date required for trial balance'}), 400
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            # Get trial balance from the trial balance endpoint
            from app.routes.accounting_routes import get_trial_balance
            statement_data = get_trial_balance(church_id, end_date)
            period_start = end_date_str
            period_end = end_date_str
'''

# Replace the old trialbalance handling
content = re.sub(r'elif statement_type == [\'"]trialbalance[\'"].*?(?=elif|else:)', new_trialbalance_section, content, flags=re.DOTALL)

# Also add a helper function to get trial balance data if not exists
if 'def get_trial_balance' not in content:
    trial_balance_func = '''

def get_trial_balance(church_id, as_at_date):
    """Get trial balance data"""
    from app.models import Account
    
    accounts = Account.query.filter_by(
        church_id=church_id,
        is_active=True
    ).order_by(Account.account_type, Account.account_code).all()
    
    account_list = []
    total_debits = 0
    total_credits = 0
    
    for acc in accounts:
        balance = float(acc.current_balance)
        
        if acc.account_type in ['ASSET', 'EXPENSE']:
            debit = balance if balance > 0 else 0
            credit = abs(balance) if balance < 0 else 0
        else:
            debit = abs(balance) if balance < 0 else 0
            credit = balance if balance > 0 else 0
        
        total_debits += debit
        total_credits += credit
        
        account_list.append({
            'code': acc.account_code,
            'name': acc.name,
            'type': acc.account_type,
            'debit': debit,
            'credit': credit,
            'balance': balance
        })
    
    return {
        'accounts': account_list,
        'totalDebits': total_debits,
        'totalCredits': total_credits,
        'isBalanced': abs(total_debits - total_credits) < 0.01,
        'asAt': as_at_date.isoformat()
    }
'''
    content += trial_balance_func

with open('app/routes/accounting_routes.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Updated trial balance export handling")
