import re

with open('app/routes/accounting_routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the export_financial_statement function and replace it
old_function_pattern = r'(@accounting_bp\.route\([^\)]+\)\s*\n\s*def export_financial_statement\(\):.*?)(?=@accounting_bp\.route|\Z)'

new_function = '''@accounting_bp.route('/financial-statements/export', methods=['GET', 'OPTIONS'])
@token_required
def export_financial_statement():
    """Export financial statement as CSV or PDF"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        statement_type = request.args.get('type', 'income').lower()
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')
        format_type = request.args.get('format', 'csv').lower()
        
        service = FinancialStatementService(church_id)
        
        # Handle different statement types
        if statement_type == 'income' or statement_type == 'income-statement':
            if not start_date_str or not end_date_str:
                return jsonify({'error': 'Start date and end date required for income statement'}), 400
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            statement_data = service.get_income_statement(start_date, end_date)
            period_start = start_date_str
            period_end = end_date_str
            
        elif statement_type == 'balance' or statement_type == 'balance-sheet':
            if not end_date_str:
                return jsonify({'error': 'End date required for balance sheet'}), 400
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            statement_data = service.get_balance_sheet(end_date)
            period_start = end_date_str
            period_end = end_date_str
            
        elif statement_type == 'trialbalance' or statement_type == 'trial-balance':
            if not end_date_str:
                return jsonify({'error': 'End date required for trial balance'}), 400
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            # Get trial balance data
            statement_data = get_trial_balance_data(church_id, end_date)
            period_start = end_date_str
            period_end = end_date_str
            
        elif statement_type == 'receipt-payment':
            if not start_date_str or not end_date_str:
                return jsonify({'error': 'Start date and end date required for receipt & payment'}), 400
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            statement_data = service.get_receipt_payment_account(start_date, end_date)
            period_start = start_date_str
            period_end = end_date_str
            
        elif statement_type == 'cashflow' or statement_type == 'cash-flow':
            if not start_date_str or not end_date_str:
                return jsonify({'error': 'Start date and end date required for cash flow statement'}), 400
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            statement_data = service.get_cash_flow_statement(start_date, end_date)
            period_start = start_date_str
            period_end = end_date_str
            
        else:
            return jsonify({'error': f'Invalid statement type: {statement_type}'}), 400
        
        if format_type == 'csv':
            return export_as_csv(statement_data, statement_type, period_start, period_end)
        elif format_type == 'pdf':
            return export_as_pdf(statement_data, statement_type, period_start, period_end)
        else:
            return jsonify({'error': 'Unsupported format'}), 400
            
    except Exception as e:
        logger.error(f"Error exporting statement: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to export statement: {str(e)}'}), 500


def get_trial_balance_data(church_id, as_at_date):
    """Get trial balance data for export"""
    from app.models import Account
    
    # Get all active accounts
    accounts = Account.query.filter_by(
        church_id=church_id,
        is_active=True
    ).order_by(Account.account_type, Account.account_code).all()
    
    account_list = []
    total_debits = 0
    total_credits = 0
    
    for acc in accounts:
        balance = float(acc.current_balance)
        
        # Determine if balance should be debit or credit based on account type
        if acc.account_type in ['ASSET', 'EXPENSE']:
            debit = balance if balance > 0 else 0
            credit = abs(balance) if balance < 0 else 0
        elif acc.account_type in ['LIABILITY', 'EQUITY', 'REVENUE']:
            debit = abs(balance) if balance < 0 else 0
            credit = balance if balance > 0 else 0
        else:
            debit = balance if balance > 0 else 0
            credit = abs(balance) if balance < 0 else 0
        
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
        'asAt': as_at_date.isoformat() if hasattr(as_at_date, 'isoformat') else str(as_at_date)
    }
'''

# Replace the function
content = re.sub(old_function_pattern, new_function, content, flags=re.DOTALL)

with open('app/routes/accounting_routes.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed export function to properly handle balance sheet and trial balance")
