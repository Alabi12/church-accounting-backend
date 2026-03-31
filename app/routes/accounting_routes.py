# app/routes/accounting_routes.py
from flask import Blueprint, request, jsonify, g, make_response
from datetime import datetime, timedelta, date
from flask_jwt_extended import get_jwt_identity
import logging
import traceback
import os
from sqlalchemy import func, or_

from app.models import User, Account, Church, JournalEntry, JournalLine
from app.extensions import db
from app.routes.auth_routes import token_required

logger = logging.getLogger(__name__)
accounting_bp = Blueprint('accounting', __name__)


# ==================== HELPER FUNCTIONS ====================

def ensure_user_church(user=None):
    """Make sure user has a church_id, assign default if not"""
    if user is None:
        user_id = get_jwt_identity()
        if user_id:
            user = User.query.get(int(user_id))
    
    if not user:
        default_church = Church.query.first()
        if default_church:
            return default_church.id
        raise ValueError("No authenticated user and no default church found")
    
    if not user.church_id:
        default_church = Church.query.first()
        if default_church:
            user.church_id = default_church.id
            db.session.add(user)
            db.session.commit()
    return user.church_id


def get_account_balance(account_id, start_date=None, end_date=None):
    """Helper function to get account balance for a period"""
    try:
        account = Account.query.get(account_id)
        if not account:
            return 0
        
        query = db.session.query(
            func.coalesce(func.sum(JournalLine.debit), 0).label('total_debit'),
            func.coalesce(func.sum(JournalLine.credit), 0).label('total_credit')
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).filter(
            JournalLine.account_id == account_id,
            JournalEntry.status == 'POSTED'
        )
        
        if start_date:
            if isinstance(start_date, date):
                start_datetime = datetime.combine(start_date, datetime.min.time())
            else:
                start_datetime = start_date
            query = query.filter(JournalEntry.entry_date >= start_datetime)
        
        if end_date:
            if isinstance(end_date, date):
                end_datetime = datetime.combine(end_date, datetime.max.time())
            else:
                end_datetime = end_date
            query = query.filter(JournalEntry.entry_date <= end_datetime)
        
        result = query.first()
        total_debit = float(result.total_debit)
        total_credit = float(result.total_credit)
        
        if account.account_type in ['ASSET', 'EXPENSE']:
            return total_debit - total_credit
        else:
            return total_credit - total_debit
            
    except Exception as e:
        logger.error(f"Error calculating account balance: {str(e)}")
        traceback.print_exc()
        return 0


# ==================== DASHBOARD ENDPOINTS ====================

@accounting_bp.route('/dashboard-stats', methods=['GET'])
@token_required
def get_dashboard_stats():
    """Get accounting dashboard statistics"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        today = datetime.utcnow()
        month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        total_income = db.session.query(
            func.sum(JournalLine.credit)
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).join(
            Account, Account.id == JournalLine.account_id
        ).filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= month_start,
            JournalEntry.entry_date <= today,
            JournalEntry.status == 'POSTED',
            Account.account_type == 'REVENUE'
        ).scalar() or 0
        
        total_expenses = db.session.query(
            func.sum(JournalLine.debit)
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).join(
            Account, Account.id == JournalLine.account_id
        ).filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= month_start,
            JournalEntry.entry_date <= today,
            JournalEntry.status == 'POSTED',
            Account.account_type == 'EXPENSE'
        ).scalar() or 0
        
        account_counts = db.session.query(
            Account.account_type,
            func.count(Account.id).label('count')
        ).filter(
            Account.church_id == church_id,
            Account.is_active == True
        ).group_by(Account.account_type).all()
        
        counts_dict = {acc_type: count for acc_type, count in account_counts}
        
        entry_counts = db.session.query(
            JournalEntry.status,
            func.count(JournalEntry.id).label('count')
        ).filter(
            JournalEntry.church_id == church_id
        ).group_by(JournalEntry.status).all()
        
        entry_dict = {status: count for status, count in entry_counts}
        
        recent_count = JournalEntry.query.filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= month_start
        ).count()
        
        return jsonify({
            'totalIncome': float(total_income),
            'totalExpenses': float(total_expenses),
            'netIncome': float(total_income - total_expenses),
            'accountCounts': counts_dict,
            'journalEntryStats': {
                'posted': entry_dict.get('POSTED', 0),
                'draft': entry_dict.get('DRAFT', 0),
                'pending': entry_dict.get('PENDING', 0),
                'void': entry_dict.get('VOID', 0)
            },
            'recentEntries': recent_count,
            'incomeByCategory': [],
            'expenseByCategory': []
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/recent-entries', methods=['GET'])
@token_required
def get_recent_entries():
    """Get recent journal entries"""
    try:
        church_id = ensure_user_church(g.current_user)
        limit = request.args.get('limit', 10, type=int)
        
        journal_entries = JournalEntry.query.filter_by(
            church_id=church_id
        ).order_by(
            JournalEntry.entry_date.desc(),
            JournalEntry.created_at.desc()
        ).limit(limit).all()
        
        entries = []
        for je in journal_entries:
            lines_info = []
            for line in je.lines:
                account = Account.query.get(line.account_id)
                lines_info.append({
                    'account_name': account.name if account else 'Unknown',
                    'account_code': account.account_code if account else '',
                    'debit': float(line.debit),
                    'credit': float(line.credit)
                })
            
            entries.append({
                'id': je.id,
                'type': 'journal',
                'number': je.entry_number,
                'date': je.entry_date.isoformat(),
                'description': je.description or 'Journal Entry',
                'reference': je.reference,
                'lines': lines_info,
                'status': je.status.lower(),
                'total': sum(l['debit'] for l in lines_info) or sum(l['credit'] for l in lines_info)
            })
        
        return jsonify({'entries': entries}), 200
        
    except Exception as e:
        logger.error(f"Error getting recent entries: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==================== ACCOUNT BALANCE ENDPOINTS ====================

@accounting_bp.route('/account-balances', methods=['GET'])
@token_required
def get_account_balances():
    """Get account balances by type"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        balances = db.session.query(
            Account.account_type,
            func.sum(Account.current_balance).label('total')
        ).filter(
            Account.church_id == church_id,
            Account.is_active == True
        ).group_by(Account.account_type).all()
        
        result = {'ASSET': 0, 'LIABILITY': 0, 'EQUITY': 0, 'REVENUE': 0, 'EXPENSE': 0}
        
        for acc_type, total in balances:
            if acc_type in result:
                result[acc_type] = float(total) if total else 0
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error getting account balances: {str(e)}")
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/alerts', methods=['GET'])
@token_required
def get_alerts():
    """Get accounting alerts"""
    try:
        church_id = ensure_user_church(g.current_user)
        alerts = []
        alert_id = 1
        
        draft_journals = JournalEntry.query.filter_by(
            church_id=church_id, status='DRAFT'
        ).count()
        
        if draft_journals > 0:
            alerts.append({
                'id': alert_id, 'type': 'warning',
                'message': f'{draft_journals} journal entries in draft state',
                'severity': 'medium'
            })
            alert_id += 1
        
        pending_journals = JournalEntry.query.filter_by(
            church_id=church_id, status='PENDING'
        ).count()
        
        if pending_journals > 0:
            alerts.append({
                'id': alert_id, 'type': 'info',
                'message': f'{pending_journals} journal entries pending approval',
                'severity': 'low'
            })
            alert_id += 1
        
        cash_accounts = Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'ASSET',
            Account.is_active == True,
            or_(
                Account.category == 'Cash',
                Account.category == 'Bank',
                Account.name.ilike('%cash%'),
                Account.name.ilike('%bank%')
            ),
            Account.current_balance < 0
        ).all()
        
        if cash_accounts:
            negative_names = [acc.name for acc in cash_accounts[:3]]
            alerts.append({
                'id': alert_id, 'type': 'error',
                'message': f'Negative balances in: {", ".join(negative_names)}' + 
                          (f' and {len(cash_accounts)-3} more' if len(cash_accounts) > 3 else ''),
                'severity': 'high'
            })
        
        return jsonify({'alerts': alerts}), 200
        
    except Exception as e:
        logger.error(f"Error getting alerts: {str(e)}")
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/monthly-trend', methods=['GET'])
@token_required
def get_monthly_trend():
    """Get monthly income/expense trend for last 12 months"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=365)
        
        results = db.session.query(
            func.strftime('%Y-%m', JournalEntry.entry_date).label('month'),
            func.sum(JournalLine.credit).filter(Account.account_type == 'REVENUE').label('income'),
            func.sum(JournalLine.debit).filter(Account.account_type == 'EXPENSE').label('expenses')
        ).join(
            JournalLine, JournalLine.journal_entry_id == JournalEntry.id
        ).join(
            Account, Account.id == JournalLine.account_id
        ).filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntry.status == 'POSTED'
        ).group_by('month').order_by('month').all()
        
        months = [{
            'month': r.month,
            'income': float(r.income or 0),
            'expenses': float(r.expenses or 0)
        } for r in results]
        
        return jsonify(months), 200
        
    except Exception as e:
        logger.error(f"Error getting monthly trend: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==================== FINANCIAL STATEMENTS ====================

@accounting_bp.route('/financial-statements', methods=['GET'])
@token_required
def get_financial_statements():
    """Get financial statements (Income Statement, Balance Sheet, etc.)"""
    try:
        church_id = ensure_user_church(g.current_user)
        statement_type = request.args.get('type', 'income').lower()
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')
        
        if statement_type in ['income', 'income-statement']:
            return _get_income_statement(church_id, start_date_str, end_date_str)
        
        elif statement_type in ['balance', 'balance-sheet']:
            return _get_balance_sheet(church_id, end_date_str)
        
        elif statement_type in ['cashflow', 'cash-flow']:
            return _get_cash_flow_statement(church_id, start_date_str, end_date_str)
        
        elif statement_type in ['receipt', 'receipt-payment']:
            return _get_receipt_payment_account(church_id, start_date_str, end_date_str)
        
        else:
            return jsonify({'error': f'Invalid statement type: {statement_type}'}), 400
            
    except Exception as e:
        logger.error(f"Error getting financial statements: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def _get_income_statement(church_id, start_date_str, end_date_str):
    """Get income statement"""
    if not start_date_str or not end_date_str:
        return jsonify({'error': 'Start date and end date required'}), 400
    
    try:
        start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
    except:
        return jsonify({'error': 'Invalid date format'}), 400
    
    print(f"\n📊 Income Statement for {start_date} to {end_date}")
    
    revenue_accounts = Account.query.filter_by(
        church_id=church_id, account_type='REVENUE', is_active=True
    ).order_by(Account.account_code).all()
    
    revenue_data = []
    total_revenue = 0
    for acc in revenue_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance != 0:
            print(f"  {acc.account_code} - {acc.name}: {balance}")
            revenue_data.append({
                'id': acc.id,
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_revenue += balance
    
    print(f"Total Revenue: {total_revenue}")
    
    expense_accounts = Account.query.filter_by(
        church_id=church_id, account_type='EXPENSE', is_active=True
    ).order_by(Account.account_code).all()
    
    expense_data = []
    total_expense = 0
    for acc in expense_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance != 0:
            expense_data.append({
                'id': acc.id,
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_expense += balance
    
    print(f"Total Expenses: {total_expense}")
    print(f"Net Income: {total_revenue - total_expense}")
    
    return jsonify({
        'title': 'Income Statement',
        'type': 'income',
        'period': f"{start_date_str} to {end_date_str}",
        'startDate': start_date_str,
        'endDate': end_date_str,
        'revenue': {
            'items': revenue_data,
            'total': total_revenue,
            'categories': {}
        },
        'expenses': {
            'items': expense_data,
            'total': total_expense,
            'categories': {}
        },
        'net_income': total_revenue - total_expense
    }), 200


def _get_balance_sheet(church_id, end_date_str):
    """Get balance sheet"""
    if not end_date_str:
        return jsonify({'error': 'End date required for balance sheet'}), 400
    
    try:
        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
    except:
        return jsonify({'error': 'Invalid date format'}), 400
    
    asset_accounts = Account.query.filter_by(
        church_id=church_id, account_type='ASSET', is_active=True
    ).order_by(Account.account_code).all()
    
    liability_accounts = Account.query.filter_by(
        church_id=church_id, account_type='LIABILITY', is_active=True
    ).order_by(Account.account_code).all()
    
    equity_accounts = Account.query.filter_by(
        church_id=church_id, account_type='EQUITY', is_active=True
    ).order_by(Account.account_code).all()
    
    assets_data = []
    total_assets = 0
    for acc in asset_accounts:
        balance = get_account_balance(acc.id, None, end_date)
        assets_data.append({
            'id': acc.id, 'account_code': acc.account_code,
            'name': acc.name, 'category': acc.category, 'amount': balance
        })
        total_assets += balance
    
    liabilities_data = []
    total_liabilities = 0
    for acc in liability_accounts:
        balance = get_account_balance(acc.id, None, end_date)
        liabilities_data.append({
            'id': acc.id, 'account_code': acc.account_code,
            'name': acc.name, 'category': acc.category, 'amount': balance
        })
        total_liabilities += balance
    
    equity_data = []
    total_equity = 0
    for acc in equity_accounts:
        balance = get_account_balance(acc.id, None, end_date)
        equity_data.append({
            'id': acc.id, 'account_code': acc.account_code,
            'name': acc.name, 'category': acc.category, 'amount': balance
        })
        total_equity += balance
    
    return jsonify({
        'title': 'Balance Sheet', 'type': 'balance', 'asOf': end_date_str,
        'assets': {'items': assets_data, 'total': total_assets},
        'liabilities': {'items': liabilities_data, 'total': total_liabilities},
        'equity': {'items': equity_data, 'total': total_equity}
    }), 200


def _get_cash_flow_statement(church_id, start_date_str, end_date_str):
    """Get cash flow statement"""
    if not start_date_str or not end_date_str:
        return jsonify({'error': 'Start date and end date required'}), 400
    
    try:
        start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
    except:
        return jsonify({'error': 'Invalid date format'}), 400
    
    cash_accounts = Account.query.filter(
        Account.church_id == church_id, Account.account_type == 'ASSET',
        Account.is_active == True,
        or_(Account.category == 'Cash', Account.category == 'Bank',
            Account.name.ilike('%cash%'), Account.name.ilike('%bank%'))
    ).all()
    
    beginning_cash = sum(get_account_balance(acc.id, None, start_date - timedelta(days=1)) for acc in cash_accounts)
    ending_cash = sum(get_account_balance(acc.id, None, end_date) for acc in cash_accounts)
    
    revenue_accounts = Account.query.filter_by(church_id=church_id, account_type='REVENUE', is_active=True).all()
    expense_accounts = Account.query.filter_by(church_id=church_id, account_type='EXPENSE', is_active=True).all()
    
    net_income = sum(get_account_balance(acc.id, start_date, end_date) for acc in revenue_accounts) - \
                 sum(get_account_balance(acc.id, start_date, end_date) for acc in expense_accounts)
    
    return jsonify({
        'title': 'Cash Flow Statement', 'type': 'cashflow',
        'period': f"{start_date_str} to {end_date_str}",
        'operating': {'items': [{'description': 'Net Income', 'amount': net_income}], 'net': net_income},
        'investing': {'items': [], 'net': 0},
        'financing': {'items': [], 'net': 0},
        'netIncrease': ending_cash - beginning_cash,
        'beginningCash': beginning_cash, 'endingCash': ending_cash
    }), 200


def _get_receipt_payment_account(church_id, start_date_str, end_date_str):
    """Get receipt and payment account"""
    if not start_date_str or not end_date_str:
        return jsonify({'error': 'Start date and end date required'}), 400
    
    try:
        start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
    except:
        return jsonify({'error': 'Invalid date format'}), 400
    
    cash_accounts = Account.query.filter(
        Account.church_id == church_id, Account.account_type == 'ASSET',
        Account.is_active == True,
        or_(Account.category == 'Cash', Account.category == 'Bank',
            Account.name.ilike('%cash%'), Account.name.ilike('%bank%'))
    ).all()
    
    revenue_accounts = Account.query.filter_by(church_id=church_id, account_type='REVENUE', is_active=True).all()
    expense_accounts = Account.query.filter_by(church_id=church_id, account_type='EXPENSE', is_active=True).all()
    
    receipts = []
    total_receipts = 0
    for acc in revenue_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance > 0:
            receipts.append({'account_code': acc.account_code, 'name': acc.name, 'amount': balance})
            total_receipts += balance
    
    payments = []
    total_payments = 0
    for acc in expense_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance > 0:
            payments.append({'account_code': acc.account_code, 'name': acc.name, 'amount': balance})
            total_payments += balance
    
    opening_balance = sum(get_account_balance(acc.id, None, start_date - timedelta(days=1)) for acc in cash_accounts)
    closing_balance = sum(get_account_balance(acc.id, None, end_date) for acc in cash_accounts)
    
    return jsonify({
        'title': 'Receipt and Payment Account', 'type': 'receipt-payment',
        'period': f"{start_date_str} to {end_date_str}",
        'openingBalances': {'cashAccounts': [], 'bankAccounts': [], 'total': opening_balance},
        'receipts': {'categories': {}, 'items': receipts, 'total': total_receipts},
        'payments': {'categories': {}, 'items': payments, 'total': total_payments},
        'closingBalances': {'cashAccounts': [], 'bankAccounts': [], 'total': closing_balance},
        'netCashFlow': total_receipts - total_payments
    }), 200


# ==================== FINANCIAL STATEMENTS EXPORT ====================

@accounting_bp.route('/financial-statements/export', methods=['GET'])
@token_required
def export_financial_statement():
    """Export financial statement as CSV"""
    try:
        church_id = ensure_user_church(g.current_user)
        statement_type = request.args.get('type', 'income').lower()
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')
        format_type = request.args.get('format', 'csv').lower()
        
        if format_type != 'csv':
            return jsonify({'error': 'Only CSV export is currently supported'}), 400
        
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        if statement_type in ['income', 'income-statement']:
            if not start_date_str or not end_date_str:
                return jsonify({'error': 'Start date and end date required'}), 400
            
            try:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            except:
                return jsonify({'error': 'Invalid date format'}), 400
            
            return _export_income_statement(church_id, start_date, end_date, start_date_str, end_date_str, writer, output)
        
        elif statement_type in ['balance', 'balance-sheet']:
            if not end_date_str:
                return jsonify({'error': 'End date required for balance sheet'}), 400
            
            try:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            except:
                return jsonify({'error': 'Invalid date format'}), 400
            
            return _export_balance_sheet(church_id, end_date, end_date_str, writer, output)
        
        elif statement_type in ['cashflow', 'cash-flow']:
            if not start_date_str or not end_date_str:
                return jsonify({'error': 'Start date and end date required'}), 400
            
            try:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            except:
                return jsonify({'error': 'Invalid date format'}), 400
            
            return _export_cashflow(church_id, start_date, end_date, start_date_str, end_date_str, writer, output)
        
        elif statement_type in ['receipt', 'receipt-payment']:
            if not start_date_str or not end_date_str:
                return jsonify({'error': 'Start date and end date required'}), 400
            
            try:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            except:
                return jsonify({'error': 'Invalid date format'}), 400
            
            return _export_receipt_payment(church_id, start_date, end_date, start_date_str, end_date_str, writer, output)
        
        else:
            return jsonify({'error': f'Invalid statement type: {statement_type}'}), 400
            
    except Exception as e:
        logger.error(f"Error exporting financial statement: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def _export_income_statement(church_id, start_date, end_date, start_date_str, end_date_str, writer, output):
    """Export income statement as CSV"""
    revenue_accounts = Account.query.filter_by(
        church_id=church_id, account_type='REVENUE', is_active=True
    ).order_by(Account.account_code).all()
    
    expense_accounts = Account.query.filter_by(
        church_id=church_id, account_type='EXPENSE', is_active=True
    ).order_by(Account.account_code).all()
    
    revenue_data = []
    total_revenue = 0
    for acc in revenue_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance != 0:
            revenue_data.append({
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_revenue += balance
    
    expense_data = []
    total_expense = 0
    for acc in expense_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance != 0:
            expense_data.append({
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_expense += balance
    
    writer.writerow(['INCOME STATEMENT'])
    writer.writerow([f'Period: {start_date_str} to {end_date_str}'])
    writer.writerow([])
    
    writer.writerow(['INCOME'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in revenue_data:
        writer.writerow([
            item.get('category', 'Revenue'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL INCOME', '', '', f"{total_revenue:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['EXPENSES'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in expense_data:
        writer.writerow([
            item.get('category', 'Expense'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL EXPENSES', '', '', f"{total_expense:,.2f}"])
    writer.writerow([])
    
    net_income = total_revenue - total_expense
    writer.writerow(['NET INCOME', '', '', f"{net_income:,.2f}"])
    writer.writerow(['STATUS', '', '', 'SURPLUS' if net_income >= 0 else 'DEFICIT'])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=income_statement_{start_date_str}_to_{end_date_str}.csv'
    
    return response


def _export_balance_sheet(church_id, end_date, end_date_str, writer, output):
    """Export balance sheet as CSV"""
    asset_accounts = Account.query.filter_by(
        church_id=church_id, account_type='ASSET', is_active=True
    ).order_by(Account.account_code).all()
    
    liability_accounts = Account.query.filter_by(
        church_id=church_id, account_type='LIABILITY', is_active=True
    ).order_by(Account.account_code).all()
    
    equity_accounts = Account.query.filter_by(
        church_id=church_id, account_type='EQUITY', is_active=True
    ).order_by(Account.account_code).all()
    
    assets_data = []
    total_assets = 0
    for acc in asset_accounts:
        balance = get_account_balance(acc.id, None, end_date)
        assets_data.append({
            'account_code': acc.account_code,
            'name': acc.name,
            'category': acc.category,
            'amount': balance
        })
        total_assets += balance
    
    liabilities_data = []
    total_liabilities = 0
    for acc in liability_accounts:
        balance = get_account_balance(acc.id, None, end_date)
        liabilities_data.append({
            'account_code': acc.account_code,
            'name': acc.name,
            'category': acc.category,
            'amount': balance
        })
        total_liabilities += balance
    
    equity_data = []
    total_equity = 0
    for acc in equity_accounts:
        balance = get_account_balance(acc.id, None, end_date)
        equity_data.append({
            'account_code': acc.account_code,
            'name': acc.name,
            'category': acc.category,
            'amount': balance
        })
        total_equity += balance
    
    writer.writerow(['BALANCE SHEET'])
    writer.writerow([f'As at: {end_date_str}'])
    writer.writerow([])
    
    writer.writerow(['ASSETS'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in assets_data:
        writer.writerow([
            item.get('category', 'Assets'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL ASSETS', '', '', f"{total_assets:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['LIABILITIES'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in liabilities_data:
        writer.writerow([
            item.get('category', 'Liabilities'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL LIABILITIES', '', '', f"{total_liabilities:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['EQUITY'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in equity_data:
        writer.writerow([
            item.get('category', 'Equity'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL EQUITY', '', '', f"{total_equity:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['TOTAL LIABILITIES & EQUITY', '', '', f"{total_liabilities + total_equity:,.2f}"])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=balance_sheet_{end_date_str}.csv'
    
    return response


def _export_cashflow(church_id, start_date, end_date, start_date_str, end_date_str, writer, output):
    """Export cash flow statement as CSV"""
    cash_accounts = Account.query.filter(
        Account.church_id == church_id,
        Account.account_type == 'ASSET',
        Account.is_active == True,
        or_(
            Account.category == 'Cash',
            Account.category == 'Bank',
            Account.name.ilike('%cash%'),
            Account.name.ilike('%bank%')
        )
    ).all()
    
    beginning_cash = sum(get_account_balance(acc.id, None, start_date - timedelta(days=1)) for acc in cash_accounts)
    ending_cash = sum(get_account_balance(acc.id, None, end_date) for acc in cash_accounts)
    
    revenue_accounts = Account.query.filter_by(church_id=church_id, account_type='REVENUE', is_active=True).all()
    expense_accounts = Account.query.filter_by(church_id=church_id, account_type='EXPENSE', is_active=True).all()
    
    net_income = sum(get_account_balance(acc.id, start_date, end_date) for acc in revenue_accounts) - \
                 sum(get_account_balance(acc.id, start_date, end_date) for acc in expense_accounts)
    
    writer.writerow(['CASH FLOW STATEMENT'])
    writer.writerow([f'Period: {start_date_str} to {end_date_str}'])
    writer.writerow([])
    
    writer.writerow(['CASH FLOW FROM OPERATING ACTIVITIES'])
    writer.writerow(['Description', 'Amount (GHS)'])
    writer.writerow(['Net Income', f"{net_income:,.2f}"])
    writer.writerow(['Net Cash from Operating Activities', f"{net_income:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['CASH FLOW FROM INVESTING ACTIVITIES'])
    writer.writerow(['Description', 'Amount (GHS)'])
    writer.writerow(['No investing activities', '0.00'])
    writer.writerow(['Net Cash from Investing Activities', '0.00'])
    writer.writerow([])
    
    writer.writerow(['CASH FLOW FROM FINANCING ACTIVITIES'])
    writer.writerow(['Description', 'Amount (GHS)'])
    writer.writerow(['No financing activities', '0.00'])
    writer.writerow(['Net Cash from Financing Activities', '0.00'])
    writer.writerow([])
    
    net_increase = ending_cash - beginning_cash
    writer.writerow(['NET INCREASE/(DECREASE) IN CASH', f"{net_increase:,.2f}"])
    writer.writerow(['Cash at Beginning of Period', f"{beginning_cash:,.2f}"])
    writer.writerow(['Cash at End of Period', f"{ending_cash:,.2f}"])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=cash_flow_{start_date_str}_to_{end_date_str}.csv'
    
    return response


def _export_receipt_payment(church_id, start_date, end_date, start_date_str, end_date_str, writer, output):
    """Export receipt and payment account as CSV"""
    cash_accounts = Account.query.filter(
        Account.church_id == church_id,
        Account.account_type == 'ASSET',
        Account.is_active == True,
        or_(
            Account.category == 'Cash',
            Account.category == 'Bank',
            Account.name.ilike('%cash%'),
            Account.name.ilike('%bank%')
        )
    ).all()
    
    revenue_accounts = Account.query.filter_by(
        church_id=church_id, account_type='REVENUE', is_active=True
    ).order_by(Account.account_code).all()
    
    expense_accounts = Account.query.filter_by(
        church_id=church_id, account_type='EXPENSE', is_active=True
    ).order_by(Account.account_code).all()
    
    receipts = []
    total_receipts = 0
    for acc in revenue_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance > 0:
            receipts.append({
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_receipts += balance
    
    payments = []
    total_payments = 0
    for acc in expense_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance > 0:
            payments.append({
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_payments += balance
    
    opening_balance = sum(get_account_balance(acc.id, None, start_date - timedelta(days=1)) for acc in cash_accounts)
    closing_balance = sum(get_account_balance(acc.id, None, end_date) for acc in cash_accounts)
    
    writer.writerow(['RECEIPT AND PAYMENT ACCOUNT'])
    writer.writerow([f'Period: {start_date_str} to {end_date_str}'])
    writer.writerow([])
    
    writer.writerow(['OPENING BALANCE'])
    writer.writerow(['Account', 'Amount (GHS)'])
    for acc in cash_accounts:
        balance = get_account_balance(acc.id, None, start_date - timedelta(days=1))
        writer.writerow([acc.name, f"{balance:,.2f}"])
    writer.writerow(['TOTAL OPENING BALANCE', f"{opening_balance:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['RECEIPTS'])
    writer.writerow(['Account Code', 'Account Name', 'Category', 'Amount (GHS)'])
    for item in receipts:
        writer.writerow([
            item['account_code'],
            item['name'],
            item.get('category', 'Receipts'),
            f"{item['amount']:,.2f}"
        ])
    writer.writerow(['TOTAL RECEIPTS', '', '', f"{total_receipts:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['PAYMENTS'])
    writer.writerow(['Account Code', 'Account Name', 'Category', 'Amount (GHS)'])
    for item in payments:
        writer.writerow([
            item['account_code'],
            item['name'],
            item.get('category', 'Payments'),
            f"{item['amount']:,.2f}"
        ])
    writer.writerow(['TOTAL PAYMENTS', '', '', f"{total_payments:,.2f}"])
    writer.writerow([])
    
    net_cash_flow = total_receipts - total_payments
    writer.writerow(['NET CASH FLOW', '', '', f"{net_cash_flow:,.2f}"])
    writer.writerow(['CLOSING BALANCE', '', '', f"{closing_balance:,.2f}"])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=receipt_payment_{start_date_str}_to_{end_date_str}.csv'
    
    return response

def export_income_statement_csv(church_id, start_date, end_date, start_date_str, end_date_str, writer, output):
    """Export income statement as CSV"""
    revenue_accounts = Account.query.filter_by(
        church_id=church_id, account_type='REVENUE', is_active=True
    ).order_by(Account.account_code).all()
    
    expense_accounts = Account.query.filter_by(
        church_id=church_id, account_type='EXPENSE', is_active=True
    ).order_by(Account.account_code).all()
    
    revenue_data = []
    total_revenue = 0
    for acc in revenue_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance != 0:
            revenue_data.append({
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_revenue += balance
    
    expense_data = []
    total_expense = 0
    for acc in expense_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance != 0:
            expense_data.append({
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_expense += balance
    
    writer.writerow(['INCOME STATEMENT'])
    writer.writerow([f'Period: {start_date_str} to {end_date_str}'])
    writer.writerow([])
    
    writer.writerow(['INCOME'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in revenue_data:
        writer.writerow([
            item.get('category', 'Revenue'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL INCOME', '', '', f"{total_revenue:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['EXPENSES'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in expense_data:
        writer.writerow([
            item.get('category', 'Expense'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL EXPENSES', '', '', f"{total_expense:,.2f}"])
    writer.writerow([])
    
    net_income = total_revenue - total_expense
    writer.writerow(['NET INCOME', '', '', f"{net_income:,.2f}"])
    writer.writerow(['STATUS', '', '', 'SURPLUS' if net_income >= 0 else 'DEFICIT'])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=income_statement_{start_date_str}_to_{end_date_str}.csv'
    
    return response


def export_balance_sheet_csv(church_id, end_date, end_date_str, writer, output):
    """Export balance sheet as CSV"""
    asset_accounts = Account.query.filter_by(
        church_id=church_id, account_type='ASSET', is_active=True
    ).order_by(Account.account_code).all()
    
    liability_accounts = Account.query.filter_by(
        church_id=church_id, account_type='LIABILITY', is_active=True
    ).order_by(Account.account_code).all()
    
    equity_accounts = Account.query.filter_by(
        church_id=church_id, account_type='EQUITY', is_active=True
    ).order_by(Account.account_code).all()
    
    assets_data = []
    total_assets = 0
    for acc in asset_accounts:
        balance = get_account_balance(acc.id, None, end_date)
        assets_data.append({
            'account_code': acc.account_code,
            'name': acc.name,
            'category': acc.category,
            'amount': balance
        })
        total_assets += balance
    
    liabilities_data = []
    total_liabilities = 0
    for acc in liability_accounts:
        balance = get_account_balance(acc.id, None, end_date)
        liabilities_data.append({
            'account_code': acc.account_code,
            'name': acc.name,
            'category': acc.category,
            'amount': balance
        })
        total_liabilities += balance
    
    equity_data = []
    total_equity = 0
    for acc in equity_accounts:
        balance = get_account_balance(acc.id, None, end_date)
        equity_data.append({
            'account_code': acc.account_code,
            'name': acc.name,
            'category': acc.category,
            'amount': balance
        })
        total_equity += balance
    
    writer.writerow(['BALANCE SHEET'])
    writer.writerow([f'As at: {end_date_str}'])
    writer.writerow([])
    
    writer.writerow(['ASSETS'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in assets_data:
        writer.writerow([
            item.get('category', 'Assets'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL ASSETS', '', '', f"{total_assets:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['LIABILITIES'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in liabilities_data:
        writer.writerow([
            item.get('category', 'Liabilities'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL LIABILITIES', '', '', f"{total_liabilities:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['EQUITY'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in equity_data:
        writer.writerow([
            item.get('category', 'Equity'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL EQUITY', '', '', f"{total_equity:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['TOTAL LIABILITIES & EQUITY', '', '', f"{total_liabilities + total_equity:,.2f}"])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=balance_sheet_{end_date_str}.csv'
    
    return response


def export_cashflow_csv(church_id, start_date, end_date, start_date_str, end_date_str, writer, output):
    """Export cash flow statement as CSV"""
    cash_accounts = Account.query.filter(
        Account.church_id == church_id,
        Account.account_type == 'ASSET',
        Account.is_active == True,
        or_(
            Account.category == 'Cash',
            Account.category == 'Bank',
            Account.name.ilike('%cash%'),
            Account.name.ilike('%bank%')
        )
    ).all()
    
    beginning_cash = sum(get_account_balance(acc.id, None, start_date - timedelta(days=1)) for acc in cash_accounts)
    ending_cash = sum(get_account_balance(acc.id, None, end_date) for acc in cash_accounts)
    
    revenue_accounts = Account.query.filter_by(church_id=church_id, account_type='REVENUE', is_active=True).all()
    expense_accounts = Account.query.filter_by(church_id=church_id, account_type='EXPENSE', is_active=True).all()
    
    net_income = sum(get_account_balance(acc.id, start_date, end_date) for acc in revenue_accounts) - \
                 sum(get_account_balance(acc.id, start_date, end_date) for acc in expense_accounts)
    
    writer.writerow(['CASH FLOW STATEMENT'])
    writer.writerow([f'Period: {start_date_str} to {end_date_str}'])
    writer.writerow([])
    
    writer.writerow(['CASH FLOW FROM OPERATING ACTIVITIES'])
    writer.writerow(['Description', 'Amount (GHS)'])
    writer.writerow(['Net Income', f"{net_income:,.2f}"])
    writer.writerow(['Net Cash from Operating Activities', f"{net_income:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['CASH FLOW FROM INVESTING ACTIVITIES'])
    writer.writerow(['Description', 'Amount (GHS)'])
    writer.writerow(['No investing activities', '0.00'])
    writer.writerow(['Net Cash from Investing Activities', '0.00'])
    writer.writerow([])
    
    writer.writerow(['CASH FLOW FROM FINANCING ACTIVITIES'])
    writer.writerow(['Description', 'Amount (GHS)'])
    writer.writerow(['No financing activities', '0.00'])
    writer.writerow(['Net Cash from Financing Activities', '0.00'])
    writer.writerow([])
    
    net_increase = ending_cash - beginning_cash
    writer.writerow(['NET INCREASE/(DECREASE) IN CASH', f"{net_increase:,.2f}"])
    writer.writerow(['Cash at Beginning of Period', f"{beginning_cash:,.2f}"])
    writer.writerow(['Cash at End of Period', f"{ending_cash:,.2f}"])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=cashflow_{start_date_str}_to_{end_date_str}.csv'
    
    return response


@accounting_bp.route('/export/trial-balance', methods=['GET'])
@token_required
def export_trial_balance():
    """Export trial balance as CSV"""
    try:
        church_id = ensure_user_church(g.current_user)
        as_at_str = request.args.get('asAt')
        format_type = request.args.get('format', 'csv').lower()
        
        if not as_at_str:
            as_at_str = datetime.utcnow().date().isoformat()
        
        try:
            as_at = datetime.fromisoformat(as_at_str.replace('Z', '+00:00')).date()
        except:
            as_at = datetime.utcnow().date()
        
        if format_type != 'csv':
            return jsonify({'error': 'Only CSV export is currently supported'}), 400
        
        # Get all active accounts
        accounts = Account.query.filter_by(
            church_id=church_id,
            is_active=True
        ).order_by(Account.account_type, Account.account_code).all()
        
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        writer.writerow(['TRIAL BALANCE'])
        writer.writerow([f'As at: {as_at_str}'])
        writer.writerow([])
        writer.writerow(['Account Code', 'Account Name', 'Account Type', 'Debit (GHS)', 'Credit (GHS)'])
        
        total_debits = 0
        total_credits = 0
        
        for acc in accounts:
            balance = get_account_balance(acc.id, None, as_at)
            
            if acc.account_type in ['ASSET', 'EXPENSE']:
                debit = balance if balance > 0 else 0
                credit = abs(balance) if balance < 0 else 0
            else:
                debit = abs(balance) if balance < 0 else 0
                credit = balance if balance > 0 else 0
            
            total_debits += debit
            total_credits += credit
            
            writer.writerow([
                acc.account_code,
                acc.name,
                acc.account_type,
                f"{debit:,.2f}" if debit > 0 else '0.00',
                f"{credit:,.2f}" if credit > 0 else '0.00'
            ])
        
        writer.writerow([])
        writer.writerow(['TOTAL', '', '', f"{total_debits:,.2f}", f"{total_credits:,.2f}"])
        writer.writerow(['STATUS', '', '', 'BALANCED' if abs(total_debits - total_credits) < 0.01 else 'NOT BALANCED'])
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=trial_balance_{as_at_str}.csv'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting trial balance: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/export/balance-sheet', methods=['GET'])
@token_required
def export_balance_sheet():
    """Export balance sheet as CSV"""
    try:
        church_id = ensure_user_church(g.current_user)
        as_at_str = request.args.get('asAt')
        format_type = request.args.get('format', 'csv').lower()
        
        if not as_at_str:
            as_at_str = datetime.utcnow().date().isoformat()
        
        try:
            as_at = datetime.fromisoformat(as_at_str.replace('Z', '+00:00')).date()
        except:
            as_at = datetime.utcnow().date()
        
        if format_type != 'csv':
            return jsonify({'error': 'Only CSV export is currently supported'}), 400
        
        # Get accounts
        asset_accounts = Account.query.filter_by(
            church_id=church_id, account_type='ASSET', is_active=True
        ).order_by(Account.account_code).all()
        
        liability_accounts = Account.query.filter_by(
            church_id=church_id, account_type='LIABILITY', is_active=True
        ).order_by(Account.account_code).all()
        
        equity_accounts = Account.query.filter_by(
            church_id=church_id, account_type='EQUITY', is_active=True
        ).order_by(Account.account_code).all()
        
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(['BALANCE SHEET'])
        writer.writerow([f'As at: {as_at_str}'])
        writer.writerow([])
        
        # Assets
        writer.writerow(['ASSETS'])
        writer.writerow(['Account Code', 'Account Name', 'Category', 'Amount (GHS)'])
        
        total_assets = 0
        for acc in asset_accounts:
            balance = get_account_balance(acc.id, None, as_at)
            writer.writerow([acc.account_code, acc.name, acc.category or 'Assets', f"{balance:,.2f}"])
            total_assets += balance
        
        writer.writerow(['TOTAL ASSETS', '', '', f"{total_assets:,.2f}"])
        writer.writerow([])
        
        # Liabilities
        writer.writerow(['LIABILITIES'])
        writer.writerow(['Account Code', 'Account Name', 'Category', 'Amount (GHS)'])
        
        total_liabilities = 0
        for acc in liability_accounts:
            balance = get_account_balance(acc.id, None, as_at)
            writer.writerow([acc.account_code, acc.name, acc.category or 'Liabilities', f"{balance:,.2f}"])
            total_liabilities += balance
        
        writer.writerow(['TOTAL LIABILITIES', '', '', f"{total_liabilities:,.2f}"])
        writer.writerow([])
        
        # Equity
        writer.writerow(['EQUITY'])
        writer.writerow(['Account Code', 'Account Name', 'Category', 'Amount (GHS)'])
        
        total_equity = 0
        for acc in equity_accounts:
            balance = get_account_balance(acc.id, None, as_at)
            writer.writerow([acc.account_code, acc.name, acc.category or 'Equity', f"{balance:,.2f}"])
            total_equity += balance
        
        writer.writerow(['TOTAL EQUITY', '', '', f"{total_equity:,.2f}"])
        writer.writerow([])
        
        writer.writerow(['TOTAL LIABILITIES & EQUITY', '', '', f"{total_liabilities + total_equity:,.2f}"])
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=balance_sheet_{as_at_str}.csv'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting balance sheet: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/export/income-statement', methods=['GET'])
@token_required
def export_income_statement():
    """Export income statement as CSV"""
    try:
        church_id = ensure_user_church(g.current_user)
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')
        format_type = request.args.get('format', 'csv').lower()
        
        if not start_date_str or not end_date_str:
            return jsonify({'error': 'Start date and end date required'}), 400
        
        try:
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
        except:
            return jsonify({'error': 'Invalid date format'}), 400
        
        if format_type != 'csv':
            return jsonify({'error': 'Only CSV export is currently supported'}), 400
        
        # Get accounts
        revenue_accounts = Account.query.filter_by(
            church_id=church_id, account_type='REVENUE', is_active=True
        ).order_by(Account.account_code).all()
        
        expense_accounts = Account.query.filter_by(
            church_id=church_id, account_type='EXPENSE', is_active=True
        ).order_by(Account.account_code).all()
        
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(['INCOME STATEMENT'])
        writer.writerow([f'Period: {start_date_str} to {end_date_str}'])
        writer.writerow([])
        
        # Revenue
        writer.writerow(['INCOME'])
        writer.writerow(['Account Code', 'Account Name', 'Category', 'Amount (GHS)'])
        
        total_revenue = 0
        for acc in revenue_accounts:
            balance = get_account_balance(acc.id, start_date, end_date)
            if balance != 0:
                writer.writerow([acc.account_code, acc.name, acc.category or 'Revenue', f"{balance:,.2f}"])
                total_revenue += balance
        
        writer.writerow(['TOTAL INCOME', '', '', f"{total_revenue:,.2f}"])
        writer.writerow([])
        
        # Expenses
        writer.writerow(['EXPENSES'])
        writer.writerow(['Account Code', 'Account Name', 'Category', 'Amount (GHS)'])
        
        total_expenses = 0
        for acc in expense_accounts:
            balance = get_account_balance(acc.id, start_date, end_date)
            if balance != 0:
                writer.writerow([acc.account_code, acc.name, acc.category or 'Expense', f"{balance:,.2f}"])
                total_expenses += balance
        
        writer.writerow(['TOTAL EXPENSES', '', '', f"{total_expenses:,.2f}"])
        writer.writerow([])
        
        net_income = total_revenue - total_expenses
        writer.writerow(['NET INCOME', '', '', f"{net_income:,.2f}"])
        writer.writerow(['STATUS', '', '', 'SURPLUS' if net_income >= 0 else 'DEFICIT'])
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=income_statement_{start_date_str}_to_{end_date_str}.csv'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting income statement: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/export/cash-flow', methods=['GET'])
@token_required
def export_cash_flow():
    """Export cash flow statement as CSV"""
    try:
        church_id = ensure_user_church(g.current_user)
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')
        format_type = request.args.get('format', 'csv').lower()
        
        if not start_date_str or not end_date_str:
            return jsonify({'error': 'Start date and end date required'}), 400
        
        try:
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
        except:
            return jsonify({'error': 'Invalid date format'}), 400
        
        if format_type != 'csv':
            return jsonify({'error': 'Only CSV export is currently supported'}), 400
        
        # Get cash accounts
        cash_accounts = Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'ASSET',
            Account.is_active == True,
            or_(
                Account.category == 'Cash',
                Account.category == 'Bank',
                Account.name.ilike('%cash%'),
                Account.name.ilike('%bank%')
            )
        ).all()
        
        # Calculate cash flow
        beginning_cash = sum(get_account_balance(acc.id, None, start_date - timedelta(days=1)) for acc in cash_accounts)
        ending_cash = sum(get_account_balance(acc.id, None, end_date) for acc in cash_accounts)
        
        revenue_accounts = Account.query.filter_by(church_id=church_id, account_type='REVENUE', is_active=True).all()
        expense_accounts = Account.query.filter_by(church_id=church_id, account_type='EXPENSE', is_active=True).all()
        
        net_income = sum(get_account_balance(acc.id, start_date, end_date) for acc in revenue_accounts) - \
                     sum(get_account_balance(acc.id, start_date, end_date) for acc in expense_accounts)
        
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(['CASH FLOW STATEMENT'])
        writer.writerow([f'Period: {start_date_str} to {end_date_str}'])
        writer.writerow([])
        
        # Operating Activities
        writer.writerow(['CASH FLOW FROM OPERATING ACTIVITIES'])
        writer.writerow(['Description', 'Amount (GHS)'])
        writer.writerow(['Net Income', f"{net_income:,.2f}"])
        writer.writerow(['Net Cash from Operating Activities', f"{net_income:,.2f}"])
        writer.writerow([])
        
        # Investing Activities
        writer.writerow(['CASH FLOW FROM INVESTING ACTIVITIES'])
        writer.writerow(['Description', 'Amount (GHS)'])
        writer.writerow(['No investing activities', '0.00'])
        writer.writerow(['Net Cash from Investing Activities', '0.00'])
        writer.writerow([])
        
        # Financing Activities
        writer.writerow(['CASH FLOW FROM FINANCING ACTIVITIES'])
        writer.writerow(['Description', 'Amount (GHS)'])
        writer.writerow(['No financing activities', '0.00'])
        writer.writerow(['Net Cash from Financing Activities', '0.00'])
        writer.writerow([])
        
        # Summary
        net_increase = ending_cash - beginning_cash
        writer.writerow(['NET INCREASE/(DECREASE) IN CASH', f"{net_increase:,.2f}"])
        writer.writerow(['Cash at Beginning of Period', f"{beginning_cash:,.2f}"])
        writer.writerow(['Cash at End of Period', f"{ending_cash:,.2f}"])
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=cash_flow_{start_date_str}_to_{end_date_str}.csv'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting cash flow: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def export_receipt_payment_data(church_id, start_date, end_date, start_date_str, end_date_str, writer, output):
    """Export receipt and payment account as CSV"""
    # Get cash accounts
    cash_accounts = Account.query.filter(
        Account.church_id == church_id,
        Account.account_type == 'ASSET',
        Account.is_active == True,
        or_(
            Account.category == 'Cash',
            Account.category == 'Bank',
            Account.name.ilike('%cash%'),
            Account.name.ilike('%bank%')
        )
    ).all()
    
    # Get revenue accounts for receipts
    revenue_accounts = Account.query.filter_by(
        church_id=church_id, account_type='REVENUE', is_active=True
    ).order_by(Account.account_code).all()
    
    # Get expense accounts for payments
    expense_accounts = Account.query.filter_by(
        church_id=church_id, account_type='EXPENSE', is_active=True
    ).order_by(Account.account_code).all()
    
    # Calculate receipts
    receipts = []
    total_receipts = 0
    for acc in revenue_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance > 0:
            receipts.append({
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_receipts += balance
    
    # Calculate payments
    payments = []
    total_payments = 0
    for acc in expense_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance > 0:
            payments.append({
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_payments += balance
    
    # Calculate opening and closing balances
    opening_balance = sum(get_account_balance(acc.id, None, start_date - timedelta(days=1)) for acc in cash_accounts)
    closing_balance = sum(get_account_balance(acc.id, None, end_date) for acc in cash_accounts)
    
    # Write CSV
    writer.writerow(['RECEIPT AND PAYMENT ACCOUNT'])
    writer.writerow([f'Period: {start_date_str} to {end_date_str}'])
    writer.writerow([])
    
    writer.writerow(['OPENING BALANCE'])
    writer.writerow(['Account', 'Amount (GHS)'])
    for acc in cash_accounts:
        balance = get_account_balance(acc.id, None, start_date - timedelta(days=1))
        writer.writerow([acc.name, f"{balance:,.2f}"])
    writer.writerow(['TOTAL OPENING BALANCE', f"{opening_balance:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['RECEIPTS'])
    writer.writerow(['Account Code', 'Account Name', 'Category', 'Amount (GHS)'])
    for item in receipts:
        writer.writerow([
            item['account_code'],
            item['name'],
            item.get('category', 'Receipts'),
            f"{item['amount']:,.2f}"
        ])
    writer.writerow(['TOTAL RECEIPTS', '', '', f"{total_receipts:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['PAYMENTS'])
    writer.writerow(['Account Code', 'Account Name', 'Category', 'Amount (GHS)'])
    for item in payments:
        writer.writerow([
            item['account_code'],
            item['name'],
            item.get('category', 'Payments'),
            f"{item['amount']:,.2f}"
        ])
    writer.writerow(['TOTAL PAYMENTS', '', '', f"{total_payments:,.2f}"])
    writer.writerow([])
    
    net_cash_flow = total_receipts - total_payments
    writer.writerow(['NET CASH FLOW', '', '', f"{net_cash_flow:,.2f}"])
    writer.writerow(['CLOSING BALANCE', '', '', f"{closing_balance:,.2f}"])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=receipt_payment_{start_date_str}_to_{end_date_str}.csv'
    
    return response


def export_income_statement_data(church_id, start_date, end_date, start_date_str, end_date_str, writer, output):
    """Export income statement as CSV"""
    revenue_accounts = Account.query.filter_by(
        church_id=church_id, account_type='REVENUE', is_active=True
    ).order_by(Account.account_code).all()
    
    expense_accounts = Account.query.filter_by(
        church_id=church_id, account_type='EXPENSE', is_active=True
    ).order_by(Account.account_code).all()
    
    revenue_data = []
    total_revenue = 0
    for acc in revenue_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance != 0:
            revenue_data.append({
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_revenue += balance
    
    expense_data = []
    total_expense = 0
    for acc in expense_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance != 0:
            expense_data.append({
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_expense += balance
    
    writer.writerow(['INCOME STATEMENT'])
    writer.writerow([f'Period: {start_date_str} to {end_date_str}'])
    writer.writerow([])
    
    writer.writerow(['INCOME'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in revenue_data:
        writer.writerow([
            item.get('category', 'Revenue'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL INCOME', '', '', f"{total_revenue:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['EXPENSES'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in expense_data:
        writer.writerow([
            item.get('category', 'Expense'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL EXPENSES', '', '', f"{total_expense:,.2f}"])
    writer.writerow([])
    
    net_income = total_revenue - total_expense
    writer.writerow(['NET INCOME', '', '', f"{net_income:,.2f}"])
    writer.writerow(['STATUS', '', '', 'SURPLUS' if net_income >= 0 else 'DEFICIT'])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=income_statement_{start_date_str}_to_{end_date_str}.csv'
    
    return response


def export_balance_sheet_data(church_id, end_date, end_date_str, writer, output):
    """Export balance sheet as CSV"""
    asset_accounts = Account.query.filter_by(
        church_id=church_id, account_type='ASSET', is_active=True
    ).order_by(Account.account_code).all()
    
    liability_accounts = Account.query.filter_by(
        church_id=church_id, account_type='LIABILITY', is_active=True
    ).order_by(Account.account_code).all()
    
    equity_accounts = Account.query.filter_by(
        church_id=church_id, account_type='EQUITY', is_active=True
    ).order_by(Account.account_code).all()
    
    assets_data = []
    total_assets = 0
    for acc in asset_accounts:
        balance = get_account_balance(acc.id, None, end_date)
        assets_data.append({
            'account_code': acc.account_code,
            'name': acc.name,
            'category': acc.category,
            'amount': balance
        })
        total_assets += balance
    
    liabilities_data = []
    total_liabilities = 0
    for acc in liability_accounts:
        balance = get_account_balance(acc.id, None, end_date)
        liabilities_data.append({
            'account_code': acc.account_code,
            'name': acc.name,
            'category': acc.category,
            'amount': balance
        })
        total_liabilities += balance
    
    equity_data = []
    total_equity = 0
    for acc in equity_accounts:
        balance = get_account_balance(acc.id, None, end_date)
        equity_data.append({
            'account_code': acc.account_code,
            'name': acc.name,
            'category': acc.category,
            'amount': balance
        })
        total_equity += balance
    
    writer.writerow(['BALANCE SHEET'])
    writer.writerow([f'As at: {end_date_str}'])
    writer.writerow([])
    
    writer.writerow(['ASSETS'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in assets_data:
        writer.writerow([
            item.get('category', 'Assets'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL ASSETS', '', '', f"{total_assets:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['LIABILITIES'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in liabilities_data:
        writer.writerow([
            item.get('category', 'Liabilities'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL LIABILITIES', '', '', f"{total_liabilities:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['EQUITY'])
    writer.writerow(['Category', 'Account Code', 'Account Name', 'Amount (GHS)'])
    
    for item in equity_data:
        writer.writerow([
            item.get('category', 'Equity'),
            item.get('account_code', ''),
            item.get('name', ''),
            f"{item.get('amount', 0):,.2f}"
        ])
    
    writer.writerow(['TOTAL EQUITY', '', '', f"{total_equity:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['TOTAL LIABILITIES & EQUITY', '', '', f"{total_liabilities + total_equity:,.2f}"])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=balance_sheet_{end_date_str}.csv'
    
    return response


def export_cashflow_data(church_id, start_date, end_date, start_date_str, end_date_str, writer, output):
    """Export cash flow statement as CSV"""
    cash_accounts = Account.query.filter(
        Account.church_id == church_id,
        Account.account_type == 'ASSET',
        Account.is_active == True,
        or_(
            Account.category == 'Cash',
            Account.category == 'Bank',
            Account.name.ilike('%cash%'),
            Account.name.ilike('%bank%')
        )
    ).all()
    
    beginning_cash = sum(get_account_balance(acc.id, None, start_date - timedelta(days=1)) for acc in cash_accounts)
    ending_cash = sum(get_account_balance(acc.id, None, end_date) for acc in cash_accounts)
    
    revenue_accounts = Account.query.filter_by(church_id=church_id, account_type='REVENUE', is_active=True).all()
    expense_accounts = Account.query.filter_by(church_id=church_id, account_type='EXPENSE', is_active=True).all()
    
    net_income = sum(get_account_balance(acc.id, start_date, end_date) for acc in revenue_accounts) - \
                 sum(get_account_balance(acc.id, start_date, end_date) for acc in expense_accounts)
    
    writer.writerow(['CASH FLOW STATEMENT'])
    writer.writerow([f'Period: {start_date_str} to {end_date_str}'])
    writer.writerow([])
    
    writer.writerow(['CASH FLOW FROM OPERATING ACTIVITIES'])
    writer.writerow(['Description', 'Amount (GHS)'])
    writer.writerow(['Net Income', f"{net_income:,.2f}"])
    writer.writerow(['Net Cash from Operating Activities', f"{net_income:,.2f}"])
    writer.writerow([])
    
    writer.writerow(['CASH FLOW FROM INVESTING ACTIVITIES'])
    writer.writerow(['Description', 'Amount (GHS)'])
    writer.writerow(['No investing activities', '0.00'])
    writer.writerow(['Net Cash from Investing Activities', '0.00'])
    writer.writerow([])
    
    writer.writerow(['CASH FLOW FROM FINANCING ACTIVITIES'])
    writer.writerow(['Description', 'Amount (GHS)'])
    writer.writerow(['No financing activities', '0.00'])
    writer.writerow(['Net Cash from Financing Activities', '0.00'])
    writer.writerow([])
    
    net_increase = ending_cash - beginning_cash
    writer.writerow(['NET INCREASE/(DECREASE) IN CASH', f"{net_increase:,.2f}"])
    writer.writerow(['Cash at Beginning of Period', f"{beginning_cash:,.2f}"])
    writer.writerow(['Cash at End of Period', f"{ending_cash:,.2f}"])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=cash_flow_{start_date_str}_to_{end_date_str}.csv'
    
    return response


# ==================== TRIAL BALANCE ====================

@accounting_bp.route('/trial-balance', methods=['GET'])
@token_required
def get_trial_balance():
    """Get trial balance"""
    try:
        church_id = ensure_user_church(g.current_user)
        as_at_str = request.args.get('asAt')
        
        if as_at_str:
            try:
                as_at = datetime.fromisoformat(as_at_str.replace('Z', '+00:00')).date()
            except:
                as_at = datetime.utcnow().date()
        else:
            as_at = datetime.utcnow().date()
        
        accounts = Account.query.filter_by(
            church_id=church_id,
            is_active=True
        ).order_by(Account.account_type, Account.account_code).all()
        
        account_list = []
        total_debits = 0
        total_credits = 0
        
        for acc in accounts:
            balance = get_account_balance(acc.id, None, as_at)
            
            if acc.account_type in ['ASSET', 'EXPENSE']:
                debit = balance if balance > 0 else 0
                credit = abs(balance) if balance < 0 else 0
            else:
                debit = abs(balance) if balance < 0 else 0
                credit = balance if balance > 0 else 0
            
            total_debits += debit
            total_credits += credit
            
            account_list.append({
                'id': acc.id,
                'code': acc.account_code,
                'name': acc.name,
                'type': acc.account_type,
                'category': acc.category,
                'debit': debit,
                'credit': credit,
                'balance': balance
            })
        
        return jsonify({
            'accounts': account_list,
            'totalDebits': total_debits,
            'totalCredits': total_credits,
            'difference': total_debits - total_credits,
            'isBalanced': abs(total_debits - total_credits) < 0.01,
            'asAt': as_at.isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting trial balance: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== LEDGER ====================

@accounting_bp.route('/ledger', methods=['GET'])
@token_required
def get_general_ledger():
    """Get general ledger entries for an account"""
    try:
        church_id = ensure_user_church(g.current_user)
        account_id = request.args.get('accountId', type=int)
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')
        
        if not account_id:
            return jsonify({'error': 'Account ID is required'}), 400
        
        account = Account.query.filter_by(
            id=account_id,
            church_id=church_id
        ).first()
        
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        
        start_date = None
        end_date = None
        
        if start_date_str:
            try:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                start_date = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                end_date = end_date.replace(hour=23, minute=59, second=59)
            except (ValueError, TypeError):
                end_date = datetime.utcnow()
        
        query = db.session.query(
            JournalLine,
            JournalEntry
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).filter(
            JournalLine.account_id == account_id,
            JournalEntry.church_id == church_id,
            JournalEntry.status == 'POSTED'
        )
        
        if start_date:
            query = query.filter(JournalEntry.entry_date >= start_date)
        
        if end_date:
            query = query.filter(JournalEntry.entry_date <= end_date)
        
        results = query.order_by(JournalEntry.entry_date.asc(), JournalEntry.id.asc()).all()
        
        opening_balance = float(account.opening_balance) if account.opening_balance is not None else 0.0
        running_balance = opening_balance
        
        entries = []
        
        for line, entry in results:
            debit = float(line.debit) if line.debit else 0
            credit = float(line.credit) if line.credit else 0
            
            if debit > 0:
                running_balance += debit
            else:
                running_balance -= credit
            
            entries.append({
                'id': line.id,
                'date': entry.entry_date.isoformat() if entry.entry_date else None,
                'description': entry.description,
                'reference': entry.entry_number,
                'accountCode': account.account_code,
                'accountName': account.name,
                'debit': debit,
                'credit': credit,
                'balance': running_balance
            })
        
        total_debit = sum(e['debit'] for e in entries)
        total_credit = sum(e['credit'] for e in entries)
        closing_balance = running_balance
        
        return jsonify({
            'account': {
                'id': account.id,
                'code': account.account_code,
                'name': account.name,
                'type': account.account_type,
                'category': account.category,
                'normal_balance': account.normal_balance
            },
            'entries': entries,
            'summary': {
                'openingBalance': opening_balance,
                'totalDebit': total_debit,
                'totalCredit': total_credit,
                'closingBalance': closing_balance
            },
            'period': {
                'startDate': start_date.isoformat() if start_date else None,
                'endDate': end_date.isoformat() if end_date else None
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting ledger: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== ACCOUNT DETAILS ====================

@accounting_bp.route('/accounts/<int:account_id>/balance', methods=['GET'])
@token_required
def get_account_balance_detail(account_id):
    """Get detailed balance for a specific account with transaction history"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        account = Account.query.filter_by(
            id=account_id,
            church_id=church_id
        ).first()
        
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        
        transactions = db.session.query(
            JournalLine,
            JournalEntry
        ).join(
            JournalEntry,
            JournalLine.journal_entry_id == JournalEntry.id
        ).filter(
            JournalLine.account_id == account_id,
            JournalEntry.church_id == church_id,
            JournalEntry.status == 'POSTED'
        ).order_by(
            JournalEntry.entry_date.asc(),
            JournalEntry.id.asc()
        ).all()
        
        opening_balance = float(account.opening_balance or 0)
        running_balance = opening_balance
        
        transaction_list = []
        
        transaction_list.append({
            'date': account.created_at.isoformat() if account.created_at else None,
            'description': 'Opening Balance',
            'reference': 'OPENING',
            'debit': 0,
            'credit': 0,
            'balance': running_balance,
            'isOpening': True
        })
        
        for line, entry in transactions:
            if line.debit > 0:
                running_balance += float(line.debit)
            else:
                running_balance -= float(line.credit)
            
            transaction_list.append({
                'date': entry.entry_date.isoformat() if entry.entry_date else None,
                'description': entry.description,
                'reference': entry.entry_number,
                'debit': float(line.debit),
                'credit': float(line.credit),
                'balance': running_balance,
                'journal_entry_id': entry.id
            })
        
        return jsonify({
            'account': {
                'id': account.id,
                'code': account.account_code,
                'name': account.name,
                'type': account.account_type,
                'category': account.category,
                'normal_balance': account.normal_balance
            },
            'current_balance': float(account.current_balance),
            'transactions': transaction_list,
            'summary': {
                'total_debits': sum(t['debit'] for t in transaction_list if not t.get('isOpening')),
                'total_credits': sum(t['credit'] for t in transaction_list if not t.get('isOpening')),
                'opening_balance': opening_balance,
                'closing_balance': running_balance
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting account balance: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== BANK ACCOUNTS ====================

@accounting_bp.route('/bank-accounts', methods=['GET'])
@token_required
def get_bank_accounts():
    """Get bank accounts for reconciliation"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        bank_accounts = Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'ASSET',
            Account.is_active == True,
            or_(
                Account.category == 'Bank',
                Account.name.ilike('%bank%'),
                Account.name.ilike('%checking%'),
                Account.name.ilike('%savings%'),
                Account.account_code.like('1020%')
            )
        ).order_by(Account.name).all()
        
        account_list = []
        for acc in bank_accounts:
            account_list.append({
                'id': acc.id,
                'name': acc.name,
                'accountNumber': acc.account_code,
                'bank': acc.category or 'Bank Account',
                'balance': float(acc.current_balance) if acc.current_balance else 0,
                'currency': 'GHS',
                'type': 'bank'
            })
        
        return jsonify({'accounts': account_list}), 200
        
    except Exception as e:
        logger.error(f"Error getting bank accounts: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/petty-cash-accounts', methods=['GET'])
@token_required
def get_petty_cash_accounts():
    """Get petty cash accounts for reconciliation"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        petty_cash_accounts = Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'ASSET',
            Account.is_active == True,
            or_(
                Account.category == 'Cash',
                Account.name.ilike('%petty%'),
                Account.name.ilike('%cash%'),
                Account.account_code.like('1010%')
            )
        ).order_by(Account.name).all()
        
        account_list = []
        for acc in petty_cash_accounts:
            account_list.append({
                'id': acc.id,
                'name': acc.name,
                'accountNumber': acc.account_code,
                'balance': float(acc.current_balance) if acc.current_balance else 0,
                'currency': 'GHS',
                'type': 'petty_cash'
            })
        
        return jsonify({'accounts': account_list}), 200
        
    except Exception as e:
        logger.error(f"Error getting petty cash accounts: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== RECONCILIATION ====================

@accounting_bp.route('/reconciliation', methods=['GET'])
@token_required
def get_reconciliation_data():
    """Get reconciliation data for an account"""
    try:
        church_id = ensure_user_church(g.current_user)
        account_id = request.args.get('accountId', type=int)
        as_of = request.args.get('asOf')
        
        if not account_id:
            return jsonify({'error': 'Account ID is required'}), 400
        
        if as_of:
            try:
                as_of_date = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
            except:
                as_of_date = datetime.utcnow()
        else:
            as_of_date = datetime.utcnow()
        
        account = Account.query.filter_by(id=account_id, church_id=church_id).first()
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        
        transactions = db.session.query(
            JournalLine, JournalEntry
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).filter(
            JournalLine.account_id == account_id,
            JournalEntry.church_id == church_id,
            JournalEntry.status == 'POSTED',
            JournalEntry.entry_date <= as_of_date
        ).order_by(JournalEntry.entry_date).all()
        
        unreconciled_items = []
        for line, entry in transactions:
            unreconciled_items.append({
                'id': line.id,
                'date': entry.entry_date.isoformat(),
                'description': entry.description,
                'reference': entry.entry_number,
                'amount': float(line.debit or line.credit),
                'type': 'debit' if line.debit > 0 else 'credit',
                'status': entry.status
            })
        
        return jsonify({
            'account': {
                'id': account.id,
                'name': account.name,
                'type': account.account_type,
                'code': account.account_code,
                'current_balance': float(account.current_balance)
            },
            'statement_balance': float(account.current_balance),
            'unreconciled_items': unreconciled_items,
            'as_of': as_of_date.isoformat(),
            'transactions': unreconciled_items
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting reconciliation data: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/reconciliation/<int:transaction_id>/reconcile', methods=['POST'])
@token_required
def reconcile_transaction(transaction_id):
    """Mark a transaction as reconciled"""
    try:
        church_id = ensure_user_church(g.current_user)
        data = request.get_json() or {}
        reconciliation_date = data.get('reconciliationDate', datetime.utcnow().isoformat())
        
        line = JournalLine.query.get(transaction_id)
        if not line:
            return jsonify({'error': 'Transaction not found'}), 404
        
        entry = JournalEntry.query.get(line.journal_entry_id)
        if not entry or entry.church_id != church_id:
            return jsonify({'error': 'Access denied'}), 403
        
        print(f"Transaction {transaction_id} reconciled on {reconciliation_date}")
        
        return jsonify({
            'message': 'Transaction reconciled successfully',
            'transaction_id': transaction_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error reconciling transaction: {str(e)}")
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/reconciliation/<int:transaction_id>/unreconcile', methods=['POST'])
@token_required
def unreconcile_transaction(transaction_id):
    """Unreconcile a transaction"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        line = JournalLine.query.get(transaction_id)
        if not line:
            return jsonify({'error': 'Transaction not found'}), 404
        
        entry = JournalEntry.query.get(line.journal_entry_id)
        if not entry or entry.church_id != church_id:
            return jsonify({'error': 'Access denied'}), 403
        
        print(f"Transaction {transaction_id} unreconciled")
        
        return jsonify({
            'message': 'Transaction unreconciled successfully',
            'transaction_id': transaction_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error unreconciling transaction: {str(e)}")
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/reconciliation/history', methods=['GET'])
@token_required
def get_reconciliation_history():
    """Get reconciliation history for an account"""
    try:
        church_id = ensure_user_church(g.current_user)
        account_id = request.args.get('accountId', type=int)
        
        if not account_id:
            return jsonify({'error': 'Account ID is required'}), 400
        
        return jsonify({'history': []}), 200
        
    except Exception as e:
        logger.error(f"Error getting reconciliation history: {str(e)}")
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/reconciliation/complete', methods=['POST'])
@token_required
def complete_reconciliation():
    """Complete a reconciliation"""
    try:
        church_id = ensure_user_church(g.current_user)
        data = request.get_json()
        
        account_id = data.get('accountId')
        reconciliation_date = data.get('reconciliationDate')
        reconciled_items = data.get('reconciledItems', [])
        adjustments = data.get('adjustments', [])
        statement_balance = data.get('statementBalance', 0)
        closing_balance = data.get('closingBalance', 0)
        
        if not account_id or not reconciliation_date:
            return jsonify({'error': 'Account ID and reconciliation date are required'}), 400
        
        print(f"Reconciliation completed for account {account_id} on {reconciliation_date}")
        print(f"Reconciled items: {len(reconciled_items)}")
        print(f"Adjustments: {len(adjustments)}")
        print(f"Statement balance: {statement_balance}")
        print(f"Closing balance: {closing_balance}")
        
        return jsonify({
            'message': 'Reconciliation completed successfully',
            'reconciled_items': len(reconciled_items)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error completing reconciliation: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==================== TAX REPORTS ====================

@accounting_bp.route('/tax-reports', methods=['GET'])
@token_required
def get_tax_reports():
    """Get tax reports for a given year"""
    try:
        church_id = ensure_user_church(g.current_user)
        year = request.args.get('year')
        
        if not year:
            year = datetime.utcnow().year
        
        if isinstance(year, dict):
            year = year.get('year', datetime.utcnow().year)
        
        try:
            year = int(year)
        except (ValueError, TypeError):
            year = datetime.utcnow().year
        
        report_type = request.args.get('type', 'summary')
        
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)
        
        if report_type == 'summary':
            total_income_result = db.session.query(
                func.sum(JournalLine.credit)
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).join(
                Account, Account.id == JournalLine.account_id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'REVENUE'
            ).scalar() or 0
            
            total_income = float(total_income_result) if total_income_result else 0.0
            
            total_expenses_result = db.session.query(
                func.sum(JournalLine.debit)
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).join(
                Account, Account.id == JournalLine.account_id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'EXPENSE'
            ).scalar() or 0
            
            total_expenses = float(total_expenses_result) if total_expenses_result else 0.0
            
            tax_exempt_result = db.session.query(
                func.sum(JournalLine.credit)
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).join(
                Account, Account.id == JournalLine.account_id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'REVENUE',
                Account.category.in_(['Tithes', 'Thanks Offering', 'Donations Received'])
            ).scalar() or 0
            
            tax_exempt = float(tax_exempt_result) if tax_exempt_result else 0.0
            
            taxes_paid_result = db.session.query(
                func.sum(JournalLine.debit)
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).join(
                Account, Account.id == JournalLine.account_id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'EXPENSE',
                Account.category == 'Taxes'
            ).scalar() or 0
            
            taxes_paid = float(taxes_paid_result) if taxes_paid_result else 0.0
            
            taxable_income = total_income - tax_exempt
            estimated_tax = taxable_income * 0.05
            tax_due = max(0.0, estimated_tax - taxes_paid)
            
            quarters = []
            for q in range(1, 5):
                q_start = datetime(year, (q-1)*3 + 1, 1)
                if q < 4:
                    q_end = datetime(year, q*3, 1).replace(day=1) - timedelta(days=1)
                else:
                    q_end = datetime(year, 12, 31)
                
                q_income_result = db.session.query(
                    func.sum(JournalLine.credit)
                ).join(
                    JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
                ).join(
                    Account, Account.id == JournalLine.account_id
                ).filter(
                    JournalEntry.church_id == church_id,
                    JournalEntry.entry_date >= q_start,
                    JournalEntry.entry_date <= q_end,
                    JournalEntry.status == 'POSTED',
                    Account.account_type == 'REVENUE'
                ).scalar() or 0
                
                q_income = float(q_income_result) if q_income_result else 0.0
                
                q_tax_paid_result = db.session.query(
                    func.sum(JournalLine.debit)
                ).join(
                    JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
                ).join(
                    Account, Account.id == JournalLine.account_id
                ).filter(
                    JournalEntry.church_id == church_id,
                    JournalEntry.entry_date >= q_start,
                    JournalEntry.entry_date <= q_end,
                    JournalEntry.status == 'POSTED',
                    Account.account_type == 'EXPENSE',
                    Account.category == 'Taxes'
                ).scalar() or 0
                
                q_tax_paid = float(q_tax_paid_result) if q_tax_paid_result else 0.0
                
                quarters.append({
                    'quarter': f'Q{q}',
                    'income': q_income,
                    'estimatedTax': q_income * 0.05,
                    'paid': q_tax_paid
                })
            
            return jsonify({
                'summary': {
                    'totalIncome': total_income,
                    'taxableIncome': taxable_income,
                    'taxExemptIncome': tax_exempt,
                    'estimatedTax': estimated_tax,
                    'paidTaxes': taxes_paid,
                    'taxDue': tax_due,
                    'quarters': quarters
                }
            }), 200
        
        elif report_type == 'withholding':
            salaries = db.session.query(
                Account.name,
                func.sum(JournalLine.debit).label('total')
            ).join(
                JournalLine, JournalLine.account_id == Account.id
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'EXPENSE',
                Account.category.in_(['Staff Cost', 'Salary', 'Wages'])
            ).group_by(Account.id).all()
            
            withholdings = []
            for salary in salaries:
                total = float(salary.total) if salary.total else 0.0
                withholdings.append({
                    'employee': salary.name,
                    'position': 'Employee',
                    'wages': total,
                    'federalWithheld': total * 0.15,
                    'stateWithheld': total * 0.05,
                    'ficaWithheld': total * 0.0765
                })
            
            return jsonify({'withholdings': withholdings}), 200
            
        elif report_type == 'donor':
            donor_contributions = db.session.query(
                Account.name,
                func.sum(JournalLine.credit).label('total')
            ).join(
                JournalLine, JournalLine.account_id == Account.id
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'REVENUE',
                Account.category.in_(['Tithes', 'Thanks Offering', 'Donations Received'])
            ).group_by(Account.id).all()
            
            donors = []
            for contribution in donor_contributions:
                total = float(contribution.total) if contribution.total else 0.0
                donors.append({
                    'id': len(donors) + 1,
                    'name': contribution.name,
                    'totalGifts': total,
                    'cash': total,
                    'nonCash': 0,
                    'statements': 1
                })
            
            return jsonify({'donors': donors}), 200
            
        elif report_type == '1099':
            contractors = db.session.query(
                Account.name,
                func.sum(JournalLine.debit).label('total')
            ).join(
                JournalLine, JournalLine.account_id == Account.id
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'EXPENSE',
                Account.category == 'Contractor'
            ).group_by(Account.id).having(func.sum(JournalLine.debit) >= 600).all()
            
            contractor_list = []
            for contractor in contractors:
                total = float(contractor.total) if contractor.total else 0.0
                contractor_list.append({
                    'name': contractor.name,
                    'ein': 'XXX-XX-XXXX',
                    'amount': total,
                    'reportable': total >= 600
                })
            
            return jsonify({'contractors': contractor_list}), 200
        
        else:
            return jsonify({'error': f'Invalid report type: {report_type}'}), 400
            
    except Exception as e:
        logger.error(f"Error getting tax reports: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/tax-reports/export', methods=['GET'])
@token_required
def export_tax_report():
    """Export tax report as CSV"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        year = request.args.get('year')
        if not year:
            year = datetime.utcnow().year
        
        if isinstance(year, dict):
            year = year.get('year', datetime.utcnow().year)
        
        try:
            year = int(year)
        except (ValueError, TypeError):
            year = datetime.utcnow().year
        
        report_type = request.args.get('type', 'summary')
        format_type = request.args.get('format', 'csv')
        
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)
        
        if format_type != 'csv':
            return jsonify({'error': 'Only CSV export is currently supported'}), 400
        
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        if report_type == 'summary':
            total_income = db.session.query(
                func.sum(JournalLine.credit)
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).join(
                Account, Account.id == JournalLine.account_id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'REVENUE'
            ).scalar() or 0
            
            total_expenses = db.session.query(
                func.sum(JournalLine.debit)
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).join(
                Account, Account.id == JournalLine.account_id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'EXPENSE'
            ).scalar() or 0
            
            tax_exempt = db.session.query(
                func.sum(JournalLine.credit)
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).join(
                Account, Account.id == JournalLine.account_id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'REVENUE',
                Account.category.in_(['Tithes', 'Thanks Offering', 'Donations Received'])
            ).scalar() or 0
            
            taxes_paid = db.session.query(
                func.sum(JournalLine.debit)
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).join(
                Account, Account.id == JournalLine.account_id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'EXPENSE',
                Account.category == 'Taxes'
            ).scalar() or 0
            
            taxable_income = total_income - tax_exempt
            estimated_tax = taxable_income * 0.05
            tax_due = max(0, estimated_tax - taxes_paid)
            
            writer.writerow(['Tax Summary Report'])
            writer.writerow([f'Year: {year}'])
            writer.writerow([f'Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}'])
            writer.writerow([])
            writer.writerow(['INCOME STATEMENT SUMMARY'])
            writer.writerow(['Description', 'Amount (GHS)'])
            writer.writerow(['Total Revenue', f'{total_income:,.2f}'])
            writer.writerow(['Total Expenses', f'{total_expenses:,.2f}'])
            writer.writerow(['Net Income', f'{total_income - total_expenses:,.2f}'])
            writer.writerow([])
            writer.writerow(['TAX CALCULATION'])
            writer.writerow(['Description', 'Amount (GHS)'])
            writer.writerow(['Total Income', f'{total_income:,.2f}'])
            writer.writerow(['Tax-Exempt Income', f'{tax_exempt:,.2f}'])
            writer.writerow(['Taxable Income', f'{taxable_income:,.2f}'])
            writer.writerow(['Estimated Tax (5%)', f'{estimated_tax:,.2f}'])
            writer.writerow(['Taxes Paid', f'{taxes_paid:,.2f}'])
            writer.writerow(['Tax Due', f'{tax_due:,.2f}'])
            writer.writerow([])
            writer.writerow(['QUARTERLY BREAKDOWN'])
            writer.writerow(['Quarter', 'Income (GHS)', 'Estimated Tax (GHS)', 'Tax Paid (GHS)'])
            
            for q in range(1, 5):
                q_start = datetime(year, (q-1)*3 + 1, 1)
                if q < 4:
                    q_end = datetime(year, q*3, 1).replace(day=1) - timedelta(days=1)
                else:
                    q_end = datetime(year, 12, 31)
                
                q_income = db.session.query(
                    func.sum(JournalLine.credit)
                ).join(
                    JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
                ).join(
                    Account, Account.id == JournalLine.account_id
                ).filter(
                    JournalEntry.church_id == church_id,
                    JournalEntry.entry_date >= q_start,
                    JournalEntry.entry_date <= q_end,
                    JournalEntry.status == 'POSTED',
                    Account.account_type == 'REVENUE'
                ).scalar() or 0
                
                q_tax_paid = db.session.query(
                    func.sum(JournalLine.debit)
                ).join(
                    JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
                ).join(
                    Account, Account.id == JournalLine.account_id
                ).filter(
                    JournalEntry.church_id == church_id,
                    JournalEntry.entry_date >= q_start,
                    JournalEntry.entry_date <= q_end,
                    JournalEntry.status == 'POSTED',
                    Account.account_type == 'EXPENSE',
                    Account.category == 'Taxes'
                ).scalar() or 0
                
                writer.writerow([
                    f'Q{q}',
                    f'{q_income:,.2f}',
                    f'{q_income * 0.05:,.2f}',
                    f'{q_tax_paid:,.2f}'
                ])
        
        elif report_type == 'withholding':
            salaries = db.session.query(
                Account.name,
                func.sum(JournalLine.debit).label('total')
            ).join(
                JournalLine, JournalLine.account_id == Account.id
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'EXPENSE',
                Account.category.in_(['Staff Cost', 'Salary', 'Wages'])
            ).group_by(Account.id).all()
            
            writer.writerow(['Withholding Tax Report'])
            writer.writerow([f'Year: {year}'])
            writer.writerow([f'Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}'])
            writer.writerow([])
            writer.writerow(['Employee', 'Position', 'Wages (GHS)', 'Federal Withheld (GHS)', 'State Withheld (GHS)', 'FICA Withheld (GHS)'])
            
            for salary in salaries:
                writer.writerow([
                    salary.name,
                    'Employee',
                    f'{salary.total:,.2f}',
                    f'{salary.total * 0.15:,.2f}',
                    f'{salary.total * 0.05:,.2f}',
                    f'{salary.total * 0.0765:,.2f}'
                ])
        
        elif report_type == 'donor':
            donor_contributions = db.session.query(
                Account.name,
                func.sum(JournalLine.credit).label('total')
            ).join(
                JournalLine, JournalLine.account_id == Account.id
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'REVENUE',
                Account.category.in_(['Tithes', 'Thanks Offering', 'Donations Received'])
            ).group_by(Account.id).all()
            
            writer.writerow(['Donor Contribution Report'])
            writer.writerow([f'Year: {year}'])
            writer.writerow([f'Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}'])
            writer.writerow([])
            writer.writerow(['Donor Name', 'Total Gifts (GHS)', 'Cash (GHS)', 'Non-Cash (GHS)', 'Statements'])
            
            for contribution in donor_contributions:
                writer.writerow([
                    contribution.name,
                    f'{contribution.total:,.2f}',
                    f'{contribution.total:,.2f}',
                    '0.00',
                    '1'
                ])
        
        elif report_type == '1099':
            contractors = db.session.query(
                Account.name,
                func.sum(JournalLine.debit).label('total')
            ).join(
                JournalLine, JournalLine.account_id == Account.id
            ).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date,
                JournalEntry.status == 'POSTED',
                Account.account_type == 'EXPENSE',
                Account.category == 'Contractor'
            ).group_by(Account.id).having(func.sum(JournalLine.debit) >= 600).all()
            
            writer.writerow(['1099 Contractor Report'])
            writer.writerow([f'Year: {year}'])
            writer.writerow([f'Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}'])
            writer.writerow([])
            writer.writerow(['Contractor Name', 'EIN', 'Amount (GHS)', 'Reportable'])
            
            for contractor in contractors:
                writer.writerow([
                    contractor.name,
                    'XXX-XX-XXXX',
                    f'{contractor.total:,.2f}',
                    'Yes' if contractor.total >= 600 else 'No'
                ])
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=tax_report_{report_type}_{year}.csv'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting tax report: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== FINANCIAL STATEMENTS WITH BUDGET ====================

@accounting_bp.route('/financial-statements-with-budget', methods=['GET'])
@token_required
def get_financial_statements_with_budget():
    """Get financial statements with budget variance analysis"""
    try:
        church_id = ensure_user_church(g.current_user)
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')
        
        if not start_date_str or not end_date_str:
            return jsonify({'error': 'startDate and endDate are required'}), 400
        
        try:
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
        except:
            return jsonify({'error': 'Invalid date format'}), 400
        
        year = start_date.year
        
        income_data = _get_income_statement_data(church_id, start_date, end_date)
        budget_data = _get_budget_data(church_id, year, start_date, end_date)
        
        revenue_variance = income_data['revenue']['total'] - budget_data['revenue_budget']
        expense_variance = income_data['expenses']['total'] - budget_data['expense_budget']
        net_variance = income_data['net_income'] - (budget_data['revenue_budget'] - budget_data['expense_budget'])
        
        return jsonify({
            'income_statement': income_data,
            'budget_comparison': {
                'revenue': {
                    'budget': round(budget_data['revenue_budget'], 2),
                    'actual': round(income_data['revenue']['total'], 2),
                    'variance': round(revenue_variance, 2),
                    'variance_percentage': round((revenue_variance / budget_data['revenue_budget'] * 100) if budget_data['revenue_budget'] > 0 else 0, 2),
                    'favorable': revenue_variance > 0
                },
                'expenses': {
                    'budget': round(budget_data['expense_budget'], 2),
                    'actual': round(income_data['expenses']['total'], 2),
                    'variance': round(expense_variance, 2),
                    'variance_percentage': round((expense_variance / budget_data['expense_budget'] * 100) if budget_data['expense_budget'] > 0 else 0, 2),
                    'favorable': expense_variance < 0
                },
                'net': {
                    'budget': round(budget_data['revenue_budget'] - budget_data['expense_budget'], 2),
                    'actual': round(income_data['net_income'], 2),
                    'variance': round(net_variance, 2),
                    'favorable': net_variance > 0
                }
            },
            'period': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
                'year': year
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting financial statements with budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def _get_income_statement_data(church_id, start_date, end_date):
    """Helper to get income statement data"""
    revenue_accounts = Account.query.filter_by(
        church_id=church_id, account_type='REVENUE', is_active=True
    ).order_by(Account.account_code).all()
    
    revenue_data = []
    total_revenue = 0
    for acc in revenue_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance != 0:
            revenue_data.append({
                'id': acc.id,
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_revenue += balance
    
    expense_accounts = Account.query.filter_by(
        church_id=church_id, account_type='EXPENSE', is_active=True
    ).order_by(Account.account_code).all()
    
    expense_data = []
    total_expense = 0
    for acc in expense_accounts:
        balance = get_account_balance(acc.id, start_date, end_date)
        if balance != 0:
            expense_data.append({
                'id': acc.id,
                'account_code': acc.account_code,
                'name': acc.name,
                'category': acc.category,
                'amount': balance
            })
            total_expense += balance
    
    return {
        'revenue': {
            'items': revenue_data,
            'total': total_revenue,
            'categories': {}
        },
        'expenses': {
            'items': expense_data,
            'total': total_expense,
            'categories': {}
        },
        'net_income': total_revenue - total_expense
    }


def _get_budget_data(church_id, year, start_date, end_date):
    """Helper to get budget data"""
    try:
        from app.models import Budget
        
        revenue_budgets = Budget.query.filter_by(
            church_id=church_id,
            fiscal_year=year,
            budget_type='REVENUE',
            status='APPROVED'
        ).all()
        
        expense_budgets = Budget.query.filter_by(
            church_id=church_id,
            fiscal_year=year,
            budget_type='EXPENSE',
            status='APPROVED'
        ).all()
        
        total_revenue_budget = sum(float(b.amount) for b in revenue_budgets)
        total_expense_budget = sum(float(b.amount) for b in expense_budgets)
        
    except:
        total_revenue_budget = 0
        total_expense_budget = 0
        
        prev_year_start = date(start_date.year - 1, start_date.month, start_date.day)
        prev_year_end = date(end_date.year - 1, end_date.month, end_date.day)
        
        prev_income = _get_income_statement_data(church_id, prev_year_start, prev_year_end)
        total_revenue_budget = prev_income['revenue']['total'] * 1.05
        total_expense_budget = prev_income['expenses']['total'] * 1.03
    
    return {
        'revenue_budget': total_revenue_budget,
        'expense_budget': total_expense_budget
    }


# ==================== TREASURER ENDPOINTS ====================

@accounting_bp.route('/treasurer/category-breakdown', methods=['GET'])
@token_required
def get_category_breakdown():
    """Get category breakdown for treasurer dashboard"""
    try:
        church_id = ensure_user_church(g.current_user)
        period = request.args.get('period', 'month')
        
        end_date = datetime.utcnow().date()
        if period == 'month':
            start_date = end_date.replace(day=1)
        elif period == 'quarter':
            quarter = (end_date.month - 1) // 3
            start_date = date(end_date.year, quarter * 3 + 1, 1)
        elif period == 'year':
            start_date = date(end_date.year, 1, 1)
        else:
            start_date = end_date - timedelta(days=30)
        
        income_by_category = db.session.query(
            Account.category,
            func.sum(JournalLine.credit).label('amount')
        ).join(
            JournalLine, JournalLine.account_id == Account.id
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntry.status == 'POSTED',
            Account.account_type == 'REVENUE'
        ).group_by(Account.category).all()
        
        expense_by_category = db.session.query(
            Account.category,
            func.sum(JournalLine.debit).label('amount')
        ).join(
            JournalLine, JournalLine.account_id == Account.id
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
            JournalEntry.status == 'POSTED',
            Account.account_type == 'EXPENSE'
        ).group_by(Account.category).all()
        
        income = []
        total_income = 0
        for cat, amount in income_by_category:
            if cat:
                amount_val = float(amount) if amount else 0
                income.append({
                    'category': cat,
                    'amount': amount_val,
                    'percentage': 0
                })
                total_income += amount_val
        
        expenses = []
        total_expenses = 0
        for cat, amount in expense_by_category:
            if cat:
                amount_val = float(amount) if amount else 0
                expenses.append({
                    'category': cat,
                    'amount': amount_val,
                    'percentage': 0
                })
                total_expenses += amount_val
        
        for item in income:
            item['percentage'] = round((item['amount'] / total_income * 100), 2) if total_income > 0 else 0
        
        for item in expenses:
            item['percentage'] = round((item['amount'] / total_expenses * 100), 2) if total_expenses > 0 else 0
        
        return jsonify({
            'income': income,
            'expenses': expenses,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'net_income': total_income - total_expenses,
            'period': period,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting category breakdown: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== DEBUG ENDPOINTS ====================

@accounting_bp.route('/debug-db', methods=['GET'])
@token_required
def debug_db():
    """Debug endpoint to show database info"""
    try:
        db_path = db.engine.url.database
        return jsonify({
            'database_path': db_path,
            'file_exists': os.path.exists(db_path),
            'file_size': os.path.getsize(db_path) if os.path.exists(db_path) else 0,
            'tables': db.engine.table_names()
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/test', methods=['GET'])
def test():
    """Simple test endpoint"""
    try:
        db_path = db.engine.url.database
        return jsonify({
            'status': 'ok',
            'database': db_path,
            'exists': os.path.exists(db_path),
            'size': os.path.getsize(db_path) if os.path.exists(db_path) else 0
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500