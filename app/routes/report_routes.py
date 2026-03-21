from flask import Blueprint, request, jsonify, g, make_response
from datetime import datetime, timedelta
import logging
import traceback
import csv
import io
from sqlalchemy import func, and_, or_

from app.models import Transaction, Account, Member, Budget, User
from app.extensions import db
from app.routes.auth_routes import token_required
from app.services.financial_statement_service import FinancialStatementService
from app.models.chart_of_accounts import CATEGORY_GROUPS

logger = logging.getLogger(__name__)
report_bp = Blueprint('report', __name__)

@report_bp.route('/financial', methods=['GET', 'OPTIONS'])
@token_required
def get_financial_report():
    """Get financial reports (income-statement, balance-sheet, cash-flow, receipt-payment, trial-balance)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        report_type = request.args.get('type', 'income-statement')
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')
        
        # Parse dates with proper error handling
        start = None
        end = None
        
        # Handle start date
        if start_date_str and start_date_str != 'undefined' and start_date_str != '':
            try:
                start = datetime.fromisoformat(start_date_str.replace('Z', '+00:00'))
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid start date format: {start_date_str}, error: {e}")
                start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Handle end date
        if end_date_str and end_date_str != 'undefined' and end_date_str != '':
            try:
                end = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                end = end.replace(hour=23, minute=59, second=59)
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid end date format: {end_date_str}, error: {e}")
                end = datetime.utcnow()
        else:
            end = datetime.utcnow()
        
        logger.info(f"Generating {report_type} report from {start} to {end}")
        
        # Use the financial statement service
        service = FinancialStatementService(church_id)
        
        if report_type == 'income-statement':
            data = service.get_income_statement(start.date(), end.date())
            return jsonify({
                'title': 'Income Statement',
                'period': f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}",
                'revenue': data['revenue'],
                'expenses': data['expenses'],
                'netIncome': data['net_income'],
                'categoryGroups': CATEGORY_GROUPS
            }), 200
            
        elif report_type == 'balance-sheet':
            data = service.get_balance_sheet(end.date())
            return jsonify({
                'title': 'Balance Sheet',
                'asOf': end.strftime('%Y-%m-%d'),
                'assets': data['assets'],
                'liabilities': data['liabilities'],
                'equity': data['equity']
            }), 200
            
        elif report_type == 'receipt-payment':
            data = service.get_receipt_payment_account(start.date(), end.date())
            return jsonify({
                'title': 'Receipt & Payment Account',
                'period': f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}",
                'openingBalances': data['opening_balances'],
                'receipts': data['receipts'],
                'payments': data['payments'],
                'closingBalances': data['closing_balances'],
                'netPosition': data['receipts']['total'] - data['payments']['total']
            }), 200
            
        elif report_type == 'trial-balance':
            return get_trial_balance(church_id, end)
            
        elif report_type == 'cash-flow':
            # For cash flow, we'll enhance the existing function
            return get_cash_flow_report(church_id, start, end)
            
        else:
            return jsonify({'error': 'Invalid report type'}), 400
            
    except Exception as e:
        logger.error(f"Error generating financial report: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


def get_trial_balance(church_id, as_of_date):
    """Generate trial balance report"""
    as_of = as_of_date
    
    # Get all active accounts
    accounts = Account.query.filter_by(
        church_id=church_id,
        is_active=True
    ).order_by(Account.account_code).all()
    
    accounts_data = []
    total_debits = 0
    total_credits = 0
    
    # Group accounts by type for better presentation
    grouped_accounts = {
        'ASSET': [],
        'LIABILITY': [],
        'EQUITY': [],
        'REVENUE': [],
        'EXPENSE': []
    }
    
    for acc in accounts:
        balance = float(acc.current_balance)
        
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
        
        account_item = {
            'code': acc.account_code,
            'name': acc.name,
            'category': acc.category,
            'type': acc.account_type,
            'debit': float(debit),
            'credit': float(credit)
        }
        
        grouped_accounts[acc.account_type].append(account_item)
        accounts_data.append(account_item)
    
    difference = total_debits - total_credits
    in_balance = abs(difference) < 0.01
    
    return jsonify({
        'title': 'Trial Balance',
        'asOf': as_of.strftime('%Y-%m-%d'),
        'groupedAccounts': grouped_accounts,
        'accounts': accounts_data,
        'totalDebits': float(total_debits),
        'totalCredits': float(total_credits),
        'difference': float(difference),
        'inBalance': in_balance
    }), 200


def get_cash_flow_report(church_id, start_date, end_date):
    """Generate cash flow statement"""
    start = start_date
    end = end_date
    
    # Get cash and bank accounts
    cash_accounts = Account.get_cash_accounts(church_id)
    bank_accounts = Account.get_bank_accounts(church_id)
    
    if not cash_accounts and not bank_accounts:
        return jsonify({'error': 'Cash/Bank accounts not found'}), 404
    
    # Get all transactions in period that affect cash/bank
    all_cash_accounts = cash_accounts + bank_accounts
    cash_account_ids = [acc.id for acc in all_cash_accounts]
    
    from app.models import JournalEntry, JournalLine
    
    transactions = db.session.query(
        JournalLine, JournalEntry, Account
    ).join(
        JournalEntry,
        JournalLine.journal_entry_id == JournalEntry.id
    ).join(
        Account,
        JournalLine.account_id == Account.id
    ).filter(
        JournalEntry.church_id == church_id,
        JournalEntry.entry_date >= start,
        JournalEntry.entry_date <= end,
        JournalEntry.status == 'POSTED',
        JournalLine.account_id.in_(cash_account_ids)
    ).all()
    
    operating = []
    investing = []
    financing = []
    
    operating_net = 0
    investing_net = 0
    financing_net = 0
    
    for line, entry, account in transactions:
        amount = float(line.debit) - float(line.credit)
        
        item = {
            'date': entry.entry_date.strftime('%Y-%m-%d'),
            'description': entry.description,
            'amount': amount,
            'account': account.name
        }
        
        # Classify based on the contra account (need to get the other side of the entry)
        contra_line = JournalLine.query.filter(
            JournalLine.journal_entry_id == entry.id,
            JournalLine.account_id != account.id
        ).first()
        
        if contra_line:
            contra_account = Account.query.get(contra_line.account_id)
            if contra_account:
                # Operating: Income, Expense, Current Assets/Liabilities
                if contra_account.account_type in ['REVENUE', 'EXPENSE']:
                    operating.append(item)
                    operating_net += amount
                # Investing: Fixed Assets, Long-term Investments
                elif contra_account.category in ['Tangible Assets', 'Investments']:
                    investing.append(item)
                    investing_net += amount
                # Financing: Loans, Equity
                elif contra_account.account_type in ['LIABILITY', 'EQUITY']:
                    financing.append(item)
                    financing_net += amount
                else:
                    operating.append(item)
                    operating_net += amount
            else:
                operating.append(item)
                operating_net += amount
        else:
            operating.append(item)
            operating_net += amount
    
    # Get beginning and ending cash
    beginning_cash = 0
    ending_cash = 0
    
    for acc in all_cash_accounts:
        beginning_cash += float(acc.opening_balance)
        ending_cash += float(acc.current_balance)
    
    net_cash_flow = ending_cash - beginning_cash
    
    return jsonify({
        'title': 'Cash Flow Statement',
        'period': f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}",
        'operating': {
            'items': operating,
            'net': float(operating_net)
        },
        'investing': {
            'items': investing,
            'net': float(investing_net)
        },
        'financing': {
            'items': financing,
            'net': float(financing_net)
        },
        'netCashFlow': float(net_cash_flow),
        'beginningCash': beginning_cash,
        'endingCash': ending_cash
    }), 200


@report_bp.route('/financial/export', methods=['GET', 'OPTIONS'])
@token_required
def export_financial_report():
    """Export financial report as CSV"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        report_type = request.args.get('type', 'income-statement')
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')
        format_type = request.args.get('format', 'csv')
        
        # Parse dates
        start = None
        end = None
        
        if start_date_str and start_date_str != 'undefined' and start_date_str != '':
            try:
                start = datetime.fromisoformat(start_date_str.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        if end_date_str and end_date_str != 'undefined' and end_date_str != '':
            try:
                end = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                end = end.replace(hour=23, minute=59, second=59)
            except (ValueError, TypeError):
                end = datetime.utcnow()
        else:
            end = datetime.utcnow()
        
        if format_type == 'csv':
            if report_type == 'receipt-payment':
                return export_receipt_payment_csv(church_id, start, end)
            elif report_type == 'income-statement':
                return export_income_statement_csv(church_id, start, end)
            elif report_type == 'balance-sheet':
                return export_balance_sheet_csv(church_id, end)
            elif report_type == 'cash-flow':
                return export_cash_flow_csv(church_id, start, end)
            elif report_type == 'trial-balance':
                return export_trial_balance_csv(church_id, end)
            else:
                return jsonify({'error': 'Invalid report type'}), 400
        else:
            return jsonify({'error': 'Only CSV export is supported'}), 400
            
    except Exception as e:
        logger.error(f"Error exporting report: {str(e)}")
        return jsonify({'error': 'Failed to export report'}), 500


def export_trial_balance_csv(church_id, as_of_date):
    """Export trial balance as CSV"""
    
    # Get all active accounts
    accounts = Account.query.filter_by(
        church_id=church_id,
        is_active=True
    ).order_by(Account.account_type, Account.account_code).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['Trial Balance'])
    writer.writerow([f"As of {as_of_date.date()}"])
    writer.writerow([])
    
    # Table headers
    writer.writerow(['Account Code', 'Account Name', 'Account Type', 'Category', 'Debit (GHS)', 'Credit (GHS)'])
    
    total_debits = 0
    total_credits = 0
    current_type = None
    
    for acc in accounts:
        balance = float(acc.current_balance)
        
        # Add type separator
        if current_type != acc.account_type:
            current_type = acc.account_type
            writer.writerow([f"--- {current_type} ---", '', '', '', '', ''])
        
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
        
        writer.writerow([
            acc.account_code,
            acc.name,
            acc.account_type,
            acc.category or '-',
            f"{debit:,.2f}" if debit > 0 else '',
            f"{credit:,.2f}" if credit > 0 else ''
        ])
    
    writer.writerow([])
    writer.writerow(['TOTALS', '', '', '', f"{total_debits:,.2f}", f"{total_credits:,.2f}"])
    
    difference = total_debits - total_credits
    writer.writerow(['Difference', '', '', '', '', f"{difference:,.2f}"])
    
    if abs(difference) < 0.01:
        writer.writerow(['Status', '', '', '', '', 'IN BALANCE'])
    else:
        writer.writerow(['Status', '', '', '', '', 'OUT OF BALANCE'])
    
    output.seek(0)
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=trial_balance_{as_of_date.date()}.csv'
    
    return response


def export_income_statement_csv(church_id, start_date, end_date):
    """Export income statement as CSV"""
    
    service = FinancialStatementService(church_id)
    data = service.get_income_statement(start_date.date(), end_date.date())
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Income Statement'])
    writer.writerow([f"Period: {start_date.date()} to {end_date.date()}"])
    writer.writerow([])
    
    # Income section
    writer.writerow(['INCOME'])
    writer.writerow(['Category', 'Amount (GHS)'])
    
    for category, cat_data in data['revenue']['categories'].items():
        writer.writerow([category, ''])
        for account in cat_data['accounts']:
            writer.writerow([f"  {account['code']} - {account['name']}", f"{account['amount']:,.2f}"])
        writer.writerow([f"Total {category}", f"{cat_data['total']:,.2f}"])
        writer.writerow([])
    
    writer.writerow(['Total Income', f"{data['revenue']['total']:,.2f}"])
    writer.writerow([])
    
    # Expenses section
    writer.writerow(['EXPENSES'])
    writer.writerow(['Category', 'Amount (GHS)'])
    
    for category, cat_data in data['expenses']['categories'].items():
        writer.writerow([category, ''])
        for account in cat_data['accounts']:
            writer.writerow([f"  {account['code']} - {account['name']}", f"{account['amount']:,.2f}"])
        writer.writerow([f"Total {category}", f"{cat_data['total']:,.2f}"])
        writer.writerow([])
    
    writer.writerow(['Total Expenses', f"{data['expenses']['total']:,.2f}"])
    writer.writerow([])
    
    # Summary
    writer.writerow(['NET INCOME', f"{data['net_income']:,.2f}"])
    
    output.seek(0)
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=income_statement_{start_date.date()}_to_{end_date.date()}.csv'
    
    return response


def export_balance_sheet_csv(church_id, as_of_date):
    """Export balance sheet as CSV"""
    
    service = FinancialStatementService(church_id)
    data = service.get_balance_sheet(as_of_date.date())
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['Balance Sheet'])
    writer.writerow([f"As of {as_of_date.date()}"])
    writer.writerow([])
    
    # Assets
    writer.writerow(['ASSETS'])
    writer.writerow(['Account', 'Amount (GHS)'])
    
    for asset in data['assets']['current']:
        writer.writerow([f"  {asset['code']} - {asset['name']}", f"{asset['amount']:,.2f}"])
    writer.writerow(['Total Current Assets', f"{data['assets']['current_total']:,.2f}"])
    writer.writerow([])
    
    for asset in data['assets']['fixed']:
        writer.writerow([f"  {asset['code']} - {asset['name']}", f"{asset['amount']:,.2f}"])
    writer.writerow(['Total Fixed Assets', f"{data['assets']['fixed_total']:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['TOTAL ASSETS', f"{data['assets']['total']:,.2f}"])
    writer.writerow([])
    
    # Liabilities
    writer.writerow(['LIABILITIES'])
    writer.writerow(['Account', 'Amount (GHS)'])
    
    for liability in data['liabilities']['current']:
        writer.writerow([f"  {liability['code']} - {liability['name']}", f"{liability['amount']:,.2f}"])
    writer.writerow(['Total Current Liabilities', f"{data['liabilities']['current_total']:,.2f}"])
    writer.writerow([])
    
    for liability in data['liabilities']['long_term']:
        writer.writerow([f"  {liability['code']} - {liability['name']}", f"{liability['amount']:,.2f}"])
    writer.writerow(['Total Long-term Liabilities', f"{data['liabilities']['long_term_total']:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['TOTAL LIABILITIES', f"{data['liabilities']['total']:,.2f}"])
    writer.writerow([])
    
    # Equity
    writer.writerow(['EQUITY'])
    writer.writerow(['Account', 'Amount (GHS)'])
    
    for eq in data['equity']['accounts']:
        writer.writerow([f"  {eq['code']} - {eq['name']}", f"{eq['amount']:,.2f}"])
    
    writer.writerow(['TOTAL EQUITY', f"{data['equity']['total']:,.2f}"])
    writer.writerow([])
    
    # Verification
    total_liabilities_equity = data['liabilities']['total'] + data['equity']['total']
    writer.writerow(['VERIFICATION', ''])
    writer.writerow(['Total Assets', f"{data['assets']['total']:,.2f}"])
    writer.writerow(['Total Liabilities + Equity', f"{total_liabilities_equity:,.2f}"])
    
    output.seek(0)
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=balance_sheet_{as_of_date.date()}.csv'
    
    return response


def export_receipt_payment_csv(church_id, start_date, end_date):
    """Export Receipt & Payment report as CSV"""
    
    service = FinancialStatementService(church_id)
    data = service.get_receipt_payment_account(start_date.date(), end_date.date())
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['Receipt & Payment Account'])
    writer.writerow([f"Period: {start_date.date()} to {end_date.date()}"])
    writer.writerow([])
    
    # Opening Balances
    writer.writerow(['OPENING BALANCES'])
    writer.writerow(['Account', 'Amount (GHS)'])
    
    for acc in data['opening_balances']['cash_accounts']:
        writer.writerow([f"Cash - {acc['name']}", f"{acc['opening_balance']:,.2f}"])
    for acc in data['opening_balances']['bank_accounts']:
        writer.writerow([f"Bank - {acc['name']}", f"{acc['opening_balance']:,.2f}"])
    writer.writerow(['Total Opening Balance', f"{data['opening_balances']['total']:,.2f}"])
    writer.writerow([])
    
    # Receipts
    writer.writerow(['RECEIPTS'])
    writer.writerow(['Category/Account', 'Amount (GHS)'])
    
    for category, cat_data in data['receipts']['categories'].items():
        writer.writerow([category, ''])
        for item in cat_data['items']:
            writer.writerow([f"  {item['date']} - {item['description']}", f"{item['amount']:,.2f}"])
        writer.writerow([f"Total {category}", f"{cat_data['total']:,.2f}"])
        writer.writerow([])
    
    writer.writerow(['Total Receipts', f"{data['receipts']['total']:,.2f}"])
    writer.writerow([])
    
    # Payments
    writer.writerow(['PAYMENTS'])
    writer.writerow(['Category/Account', 'Amount (GHS)'])
    
    for category, cat_data in data['payments']['categories'].items():
        writer.writerow([category, ''])
        for item in cat_data['items']:
            writer.writerow([f"  {item['date']} - {item['description']}", f"{item['amount']:,.2f}"])
        writer.writerow([f"Total {category}", f"{cat_data['total']:,.2f}"])
        writer.writerow([])
    
    writer.writerow(['Total Payments', f"{data['payments']['total']:,.2f}"])
    writer.writerow([])
    
    # Closing Balances
    writer.writerow(['CLOSING BALANCES'])
    writer.writerow(['Account', 'Amount (GHS)'])
    
    for acc in data['closing_balances']['cash_accounts']:
        writer.writerow([f"Cash - {acc['name']}", f"{acc['closing_balance']:,.2f}"])
    for acc in data['closing_balances']['bank_accounts']:
        writer.writerow([f"Bank - {acc['name']}", f"{acc['closing_balance']:,.2f}"])
    writer.writerow(['Total Closing Balance', f"{data['closing_balances']['total']:,.2f}"])
    writer.writerow([])
    
    # Summary
    net_position = data['receipts']['total'] - data['payments']['total']
    writer.writerow(['SUMMARY'])
    writer.writerow(['Net Position (Receipts - Payments)', f"{net_position:,.2f}"])
    writer.writerow(['Opening Balance + Net Position', f"{data['opening_balances']['total'] + net_position:,.2f}"])
    writer.writerow(['Closing Balance', f"{data['closing_balances']['total']:,.2f}"])
    
    output.seek(0)
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=receipt_payment_{start_date.date()}_to_{end_date.date()}.csv'
    
    return response


def export_cash_flow_csv(church_id, start_date, end_date):
    """Export cash flow statement as CSV"""
    
    # Get cash flow data
    response = get_cash_flow_report(church_id, start_date, end_date)
    data = response[0].json if hasattr(response[0], 'json') else {}
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['Cash Flow Statement'])
    writer.writerow([f"Period: {start_date.date()} to {end_date.date()}"])
    writer.writerow([])
    
    # Operating activities
    writer.writerow(['OPERATING ACTIVITIES'])
    writer.writerow(['Date', 'Description', 'Amount (GHS)'])
    
    operating_net = 0
    for item in data.get('operating', {}).get('items', []):
        writer.writerow([
            item.get('date', ''),
            item.get('description', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
        operating_net += item.get('amount', 0)
    
    writer.writerow(['', 'Net Cash from Operating Activities', f"{operating_net:,.2f}"])
    writer.writerow([])
    
    # Investing activities
    writer.writerow(['INVESTING ACTIVITIES'])
    writer.writerow(['Date', 'Description', 'Amount (GHS)'])
    
    investing_net = 0
    for item in data.get('investing', {}).get('items', []):
        writer.writerow([
            item.get('date', ''),
            item.get('description', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
        investing_net += item.get('amount', 0)
    
    writer.writerow(['', 'Net Cash from Investing Activities', f"{investing_net:,.2f}"])
    writer.writerow([])
    
    # Financing activities
    writer.writerow(['FINANCING ACTIVITIES'])
    writer.writerow(['Date', 'Description', 'Amount (GHS)'])
    
    financing_net = 0
    for item in data.get('financing', {}).get('items', []):
        writer.writerow([
            item.get('date', ''),
            item.get('description', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
        financing_net += item.get('amount', 0)
    
    writer.writerow(['', 'Net Cash from Financing Activities', f"{financing_net:,.2f}"])
    writer.writerow([])
    
    # Summary
    writer.writerow(['CASH SUMMARY'])
    writer.writerow(['Beginning Cash Balance', f"{data.get('beginningCash', 0):,.2f}"])
    writer.writerow(['Net Increase/(Decrease)', f"{data.get('netCashFlow', 0):,.2f}"])
    writer.writerow(['Ending Cash Balance', f"{data.get('endingCash', 0):,.2f}"])
    
    output.seek(0)
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=cash_flow_{start_date.date()}_to_{end_date.date()}.csv'
    
    return response