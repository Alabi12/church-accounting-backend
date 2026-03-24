import re

# Read the file
with open('app/routes/accounting_routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find and replace the export_financial_statement function
# The pattern to find the function
pattern = r'(@accounting_bp\.route\([^\)]+\)\s*\n\s*def export_financial_statement\(\):.*?(?=@accounting_bp\.route|\Z))'

# Create the corrected function
corrected_function = '''@accounting_bp.route('/financial-statements/export', methods=['GET', 'OPTIONS'])
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
        if statement_type == 'income':
            if not start_date_str or not end_date_str:
                return jsonify({'error': 'Start date and end date required for income statement'}), 400
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            statement_data = service.get_income_statement(start_date, end_date)
            period_text = f"{start_date_str} to {end_date_str}"
            
        elif statement_type == 'balance':
            if not end_date_str:
                return jsonify({'error': 'End date required for balance sheet'}), 400
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            statement_data = service.get_balance_sheet(end_date)
            period_text = f"As at {end_date_str}"
            
        elif statement_type == 'receipt-payment':
            if not start_date_str or not end_date_str:
                return jsonify({'error': 'Start date and end date required for receipt & payment'}), 400
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            statement_data = service.get_receipt_payment_account(start_date, end_date)
            period_text = f"{start_date_str} to {end_date_str}"
            
        elif statement_type == 'cashflow':
            if not start_date_str or not end_date_str:
                return jsonify({'error': 'Start date and end date required for cash flow statement'}), 400
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            statement_data = service.get_cash_flow_statement(start_date, end_date)
            period_text = f"{start_date_str} to {end_date_str}"
            
        else:
            return jsonify({'error': f'Invalid statement type: {statement_type}'}), 400
        
        if format_type == 'csv':
            return export_as_csv(statement_data, statement_type, start_date_str, end_date_str)
        elif format_type == 'pdf':
            return export_as_pdf(statement_data, statement_type, start_date_str, end_date_str)
        else:
            return jsonify({'error': 'Unsupported format'}), 400
            
    except Exception as e:
        logger.error(f"Error exporting statement: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': f'Failed to export statement: {str(e)}'}), 500
'''

# Replace the function
content = re.sub(pattern, corrected_function, content, flags=re.DOTALL)

# Write back
with open('app/routes/accounting_routes.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed export_financial_statement function")
