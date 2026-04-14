# app/routes/accounting_routes.py
from flask import Blueprint, request, jsonify, g, make_response
from datetime import datetime, timedelta, date
from flask_jwt_extended import get_jwt_identity
import logging
import traceback
import os
from sqlalchemy import func, or_

from app.models import User, Account, Church, JournalEntry, JournalLine, Employee
from app.models.leave import LeaveRequest, LeaveBalance, LeaveType
from app.extensions import db
from app.routes.auth_routes import token_required
# from sqlalchemy import func, or_, and_
# from datetime import datetime, timedelta, date

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
        
        # Get date parameters
        month = request.args.get('month', type=int)
        year = request.args.get('year', type=int)
        
        # Set date range
        if month and year:
            start_datetime = datetime(year, month, 1, 0, 0, 0)
            if month == 12:
                end_datetime = datetime(year + 1, 1, 1, 0, 0, 0) - timedelta(seconds=1)
            else:
                end_datetime = datetime(year, month + 1, 1, 0, 0, 0) - timedelta(seconds=1)
        else:
            # Default to current month
            now = datetime.utcnow()
            year = now.year
            month = now.month
            start_datetime = datetime(year, month, 1, 0, 0, 0)
            if month == 12:
                end_datetime = datetime(year + 1, 1, 1, 0, 0, 0) - timedelta(seconds=1)
            else:
                end_datetime = datetime(year, month + 1, 1, 0, 0, 0) - timedelta(seconds=1)
        
        # Calculate total income from POSTED journal entries for revenue accounts
        total_income = db.session.query(
            func.sum(JournalLine.credit)
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).join(
            Account, Account.id == JournalLine.account_id
        ).filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= start_datetime,
            JournalEntry.entry_date <= end_datetime,
            JournalEntry.status == 'POSTED',
            Account.account_type == 'REVENUE'
        ).scalar() or 0
        
        # Calculate total expenses from POSTED journal entries for expense accounts
        total_expenses = db.session.query(
            func.sum(JournalLine.debit)
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).join(
            Account, Account.id == JournalLine.account_id
        ).filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= start_datetime,
            JournalEntry.entry_date <= end_datetime,
            JournalEntry.status == 'POSTED',
            Account.account_type == 'EXPENSE'
        ).scalar() or 0
        
        # Get income by category
        income_by_category = db.session.query(
            Account.category,
            func.sum(JournalLine.credit).label('total')
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).join(
            Account, Account.id == JournalLine.account_id
        ).filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= start_datetime,
            JournalEntry.entry_date <= end_datetime,
            JournalEntry.status == 'POSTED',
            Account.account_type == 'REVENUE'
        ).group_by(Account.category).all()
        
        # Get expenses by category
        expense_by_category = db.session.query(
            Account.category,
            func.sum(JournalLine.debit).label('total')
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).join(
            Account, Account.id == JournalLine.account_id
        ).filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= start_datetime,
            JournalEntry.entry_date <= end_datetime,
            JournalEntry.status == 'POSTED',
            Account.account_type == 'EXPENSE'
        ).group_by(Account.category).all()
        
        # Format category data
        income_categories = []
        for cat in income_by_category:
            if cat.category:
                income_categories.append({
                    'category': cat.category,
                    'total': float(cat.total) if cat.total else 0
                })
        
        expense_categories = []
        for cat in expense_by_category:
            if cat.category:
                expense_categories.append({
                    'category': cat.category,
                    'total': float(cat.total) if cat.total else 0
                })
        
        # Get account balances by type
        account_balances = db.session.query(
            Account.account_type,
            func.sum(Account.current_balance).label('total')
        ).filter(
            Account.church_id == church_id,
            Account.is_active == True
        ).group_by(Account.account_type).all()
        
        balances_dict = {'ASSET': 0, 'LIABILITY': 0, 'EQUITY': 0, 'REVENUE': 0, 'EXPENSE': 0}
        for acc_type, total in account_balances:
            if acc_type in balances_dict:
                balances_dict[acc_type] = float(total) if total else 0
        
        # Get cash and bank balances
        cash_balance = db.session.query(
            func.sum(Account.current_balance)
        ).filter(
            Account.church_id == church_id,
            Account.is_active == True,
            Account.account_type == 'ASSET',
            Account.account_code.like('1010%')
        ).scalar() or 0
        
        bank_balance = db.session.query(
            func.sum(Account.current_balance)
        ).filter(
            Account.church_id == church_id,
            Account.is_active == True,
            Account.account_type == 'ASSET',
            Account.account_code.like('1020%')
        ).scalar() or 0
        
        # Get account counts
        account_counts = db.session.query(
            Account.account_type,
            func.count(Account.id).label('count')
        ).filter(
            Account.church_id == church_id,
            Account.is_active == True
        ).group_by(Account.account_type).all()
        
        counts_dict = {acc_type: count for acc_type, count in account_counts}
        
        # Get journal entry stats
        entry_counts = db.session.query(
            JournalEntry.status,
            func.count(JournalEntry.id).label('count')
        ).filter(
            JournalEntry.church_id == church_id
        ).group_by(JournalEntry.status).all()
        
        entry_dict = {status: count for status, count in entry_counts}
        
        # Count recent entries (this month)
        recent_count = JournalEntry.query.filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= start_datetime
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
            'incomeByCategory': income_categories,
            'expenseByCategory': expense_categories,
            # Add these for the other cards
            'cashBalance': float(cash_balance),
            'bankBalance': float(bank_balance),
            'assetBalance': balances_dict.get('ASSET', 0),
            'liabilityBalance': balances_dict.get('LIABILITY', 0),
            'equityBalance': balances_dict.get('EQUITY', 0),
            'revenueBalance': balances_dict.get('REVENUE', 0),
            'expenseBalance': balances_dict.get('EXPENSE', 0)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@accounting_bp.route('/dashboard-ytd', methods=['GET'])
@token_required
def get_dashboard_ytd():
    """Get year-to-date dashboard statistics"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Get year parameter
        year = request.args.get('year', type=int, default=datetime.utcnow().year)
        
        # Set date range to full year
        start_datetime = datetime(year, 1, 1, 0, 0, 0)
        end_datetime = datetime(year, 12, 31, 23, 59, 59)
        
        # Calculate YTD income
        total_income = db.session.query(
            func.sum(JournalLine.credit)
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).join(
            Account, Account.id == JournalLine.account_id
        ).filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= start_datetime,
            JournalEntry.entry_date <= end_datetime,
            JournalEntry.status == 'POSTED',
            Account.account_type == 'REVENUE'
        ).scalar() or 0
        
        # Calculate YTD expenses
        total_expenses = db.session.query(
            func.sum(JournalLine.debit)
        ).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).join(
            Account, Account.id == JournalLine.account_id
        ).filter(
            JournalEntry.church_id == church_id,
            JournalEntry.entry_date >= start_datetime,
            JournalEntry.entry_date <= end_datetime,
            JournalEntry.status == 'POSTED',
            Account.account_type == 'EXPENSE'
        ).scalar() or 0
        
        return jsonify({
            'year': year,
            'totalIncome': float(total_income),
            'totalExpenses': float(total_expenses),
            'netIncome': float(total_income - total_expenses)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting YTD stats: {str(e)}")
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


@accounting_bp.route('/financial-statements-with-budget', methods=['GET'])
@token_required
def get_financial_statements_with_budget():
    """Get financial statements with budget variance analysis"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Get date parameters
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
        
        # Get actual income statement data
        income_statement = _get_income_statement_data(church_id, start_date, end_date)
        
        # Get budget data
        budget_data = _get_budget_data_for_period(church_id, year, start_date, end_date)
        
        # Calculate variances
        revenue_variance = income_statement['revenue']['total'] - budget_data['revenue_budget']
        expense_variance = income_statement['expenses']['total'] - budget_data['expense_budget']
        net_variance = income_statement['net_income'] - (budget_data['revenue_budget'] - budget_data['expense_budget'])
        
        return jsonify({
            'income_statement': income_statement,
            'budget_comparison': {
                'revenue': {
                    'budget': round(budget_data['revenue_budget'], 2),
                    'actual': round(income_statement['revenue']['total'], 2),
                    'variance': round(revenue_variance, 2),
                    'variance_percentage': round((revenue_variance / budget_data['revenue_budget'] * 100) if budget_data['revenue_budget'] > 0 else 0, 2),
                    'favorable': revenue_variance > 0
                },
                'expenses': {
                    'budget': round(budget_data['expense_budget'], 2),
                    'actual': round(income_statement['expenses']['total'], 2),
                    'variance': round(expense_variance, 2),
                    'variance_percentage': round((expense_variance / budget_data['expense_budget'] * 100) if budget_data['expense_budget'] > 0 else 0, 2),
                    'favorable': expense_variance < 0
                },
                'net': {
                    'budget': round(budget_data['revenue_budget'] - budget_data['expense_budget'], 2),
                    'actual': round(income_statement['net_income'], 2),
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


def _get_budget_data_for_period(church_id, year, start_date, end_date):
    """Helper to get budget data for a period"""
    try:
        from app.models import Budget
        
        # Get approved budgets for the year
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
        # Fallback: Use previous year's actuals with growth
        prev_year_start = date(start_date.year - 1, start_date.month, start_date.day)
        prev_year_end = date(end_date.year - 1, end_date.month, end_date.day)
        
        prev_income = _get_income_statement_data(church_id, prev_year_start, prev_year_end)
        total_revenue_budget = prev_income['revenue']['total'] * 1.05  # 5% growth
        total_expense_budget = prev_income['expenses']['total'] * 1.03  # 3% growth
    
    return {
        'revenue_budget': total_revenue_budget,
        'expense_budget': total_expense_budget
    }

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


# Add after your existing imports
from sqlalchemy import func, or_, and_
from datetime import datetime, timedelta, date

# ==================== BALANCE SHEET ENDPOINT ====================

@accounting_bp.route('/balance-sheet', methods=['GET'])
@token_required
def get_balance_sheet_data():
    """Get balance sheet data"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        as_at_str = request.args.get('asAt')
        if not as_at_str:
            as_at_str = datetime.utcnow().date().isoformat()
        
        try:
            as_at = datetime.fromisoformat(as_at_str.replace('Z', '+00:00')).date()
        except:
            as_at = datetime.utcnow().date()
        
        # Get asset accounts
        asset_accounts = Account.query.filter_by(
            church_id=church_id, account_type='ASSET', is_active=True
        ).order_by(Account.account_code).all()
        
        assets = []
        total_assets = 0
        for acc in asset_accounts:
            balance = get_account_balance(acc.id, None, as_at)
            assets.append({
                'id': acc.id,
                'code': acc.account_code,
                'name': acc.name,
                'category': acc.category or 'Assets',
                'amount': float(balance)
            })
            total_assets += balance
        
        # Get liability accounts
        liability_accounts = Account.query.filter_by(
            church_id=church_id, account_type='LIABILITY', is_active=True
        ).order_by(Account.account_code).all()
        
        liabilities = []
        total_liabilities = 0
        for acc in liability_accounts:
            balance = get_account_balance(acc.id, None, as_at)
            liabilities.append({
                'id': acc.id,
                'code': acc.account_code,
                'name': acc.name,
                'category': acc.category or 'Liabilities',
                'amount': float(balance)
            })
            total_liabilities += balance
        
        # Get equity accounts
        equity_accounts = Account.query.filter_by(
            church_id=church_id, account_type='EQUITY', is_active=True
        ).order_by(Account.account_code).all()
        
        equity = []
        total_equity = 0
        for acc in equity_accounts:
            balance = get_account_balance(acc.id, None, as_at)
            equity.append({
                'id': acc.id,
                'code': acc.account_code,
                'name': acc.name,
                'category': acc.category or 'Equity',
                'amount': float(balance)
            })
            total_equity += balance
        
        return jsonify({
            'assets': {
                'items': assets,
                'total': float(total_assets)
            },
            'liabilities': {
                'items': liabilities,
                'total': float(total_liabilities)
            },
            'equity': {
                'items': equity,
                'total': float(total_equity)
            },
            'asAt': as_at.isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting balance sheet: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== INCOME VS EXPENSES ENDPOINT ====================

@accounting_bp.route('/income-vs-expenses', methods=['GET'])
@token_required
def get_income_vs_expenses():
    """Get income vs expenses comparison for charts"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Get parameters
        period = request.args.get('period', 'month')
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')
        
        # Set date range
        end_date = datetime.utcnow().date()
        if start_date_str and end_date_str:
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
        elif period == 'month':
            start_date = end_date.replace(day=1)
        elif period == 'quarter':
            quarter = (end_date.month - 1) // 3
            start_date = date(end_date.year, quarter * 3 + 1, 1)
        elif period == 'year':
            start_date = date(end_date.year, 1, 1)
        else:
            start_date = end_date - timedelta(days=30)
        
        # Get revenue accounts
        revenue_accounts = Account.query.filter_by(
            church_id=church_id, account_type='REVENUE', is_active=True
        ).all()
        
        total_income = 0
        for acc in revenue_accounts:
            balance = get_account_balance(acc.id, start_date, end_date)
            if balance > 0:
                total_income += balance
        
        # Get expense accounts
        expense_accounts = Account.query.filter_by(
            church_id=church_id, account_type='EXPENSE', is_active=True
        ).all()
        
        total_expenses = 0
        for acc in expense_accounts:
            balance = get_account_balance(acc.id, start_date, end_date)
            if balance > 0:
                total_expenses += balance
        
        # Calculate previous period for comparison
        days_diff = (end_date - start_date).days
        prev_end_date = start_date - timedelta(days=1)
        prev_start_date = prev_end_date - timedelta(days=days_diff)
        
        prev_income = 0
        for acc in revenue_accounts:
            balance = get_account_balance(acc.id, prev_start_date, prev_end_date)
            if balance > 0:
                prev_income += balance
        
        prev_expenses = 0
        for acc in expense_accounts:
            balance = get_account_balance(acc.id, prev_start_date, prev_end_date)
            if balance > 0:
                prev_expenses += balance
        
        income_change = ((total_income - prev_income) / prev_income * 100) if prev_income > 0 else 0
        expense_change = ((total_expenses - prev_expenses) / prev_expenses * 100) if prev_expenses > 0 else 0
        
        # Generate monthly data for chart
        monthly_data = []
        current = start_date
        while current <= end_date:
            if current.month == 12:
                month_end = date(current.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(current.year, current.month + 1, 1) - timedelta(days=1)
            month_end = min(month_end, end_date)
            
            month_income = 0
            for acc in revenue_accounts:
                balance = get_account_balance(acc.id, current, month_end)
                if balance > 0:
                    month_income += balance
            
            month_expenses = 0
            for acc in expense_accounts:
                balance = get_account_balance(acc.id, current, month_end)
                if balance > 0:
                    month_expenses += balance
            
            monthly_data.append({
                'month': current.strftime('%b'),
                'income': float(month_income),
                'expenses': float(month_expenses),
                'net': float(month_income - month_expenses)
            })
            
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)
        
        return jsonify({
            'income': float(total_income),
            'expenses': float(total_expenses),
            'net': float(total_income - total_expenses),
            'incomeChange': round(income_change, 1),
            'expenseChange': round(expense_change, 1),
            'data': monthly_data
        }), 200
        
    except Exception as e:
        logger.error(f"Error in income-vs-expenses endpoint: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== CATEGORY BREAKDOWN ENDPOINT ====================

@accounting_bp.route('/category-breakdown', methods=['GET'])
@token_required
def get_category_breakdown_data():
    """Get income and expense breakdown by category"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        period = request.args.get('period', 'month')
        
        # Set date range
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
        
        # Get income by category
        revenue_accounts = Account.query.filter_by(
            church_id=church_id, account_type='REVENUE', is_active=True
        ).all()
        
        income_categories = []
        for acc in revenue_accounts:
            balance = get_account_balance(acc.id, start_date, end_date)
            if balance > 0:
                income_categories.append({
                    'name': acc.category or 'Other Income',
                    'value': float(balance)
                })
        
        # Get expenses by category
        expense_accounts = Account.query.filter_by(
            church_id=church_id, account_type='EXPENSE', is_active=True
        ).all()
        
        expense_categories = []
        for acc in expense_accounts:
            balance = get_account_balance(acc.id, start_date, end_date)
            if balance > 0:
                expense_categories.append({
                    'name': acc.category or 'Other Expenses',
                    'value': float(balance)
                })
        
        return jsonify({
            'income': income_categories,
            'expenses': expense_categories
        }), 200
        
    except Exception as e:
        logger.error(f"Error in category-breakdown endpoint: {str(e)}")
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


# ==================== ACCOUNTS ====================

@accounting_bp.route('/accounts', methods=['GET'])
@token_required
def get_accounts():
    """Get all accounts for the church"""
    try:
        church_id = ensure_user_church(g.current_user)
        per_page = request.args.get('perPage', 100, type=int)
        page = request.args.get('page', 1, type=int)
        
        query = Account.query.filter_by(church_id=church_id, is_active=True)
        
        accounts = query.order_by(Account.account_type, Account.account_code).all()
        
        result = []
        for acc in accounts:
            result.append({
                'id': acc.id,
                'account_code': acc.account_code,
                'name': acc.name,
                'account_type': acc.account_type,
                'category': acc.category,
                'normal_balance': acc.normal_balance,
                'current_balance': float(acc.current_balance) if acc.current_balance else 0,
                'is_active': acc.is_active
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error getting accounts: {str(e)}")
        return jsonify({'error': str(e)}), 500


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
            tax_due = max(0.0, estimated_tax - taxes_paid)
            
            quarters = []
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
                
                quarters.append({
                    'quarter': f'Q{q}',
                    'income': float(q_income),
                    'estimatedTax': float(q_income) * 0.05,
                    'paid': float(q_tax_paid)
                })
            
            return jsonify({
                'summary': {
                    'totalIncome': float(total_income),
                    'taxableIncome': float(taxable_income),
                    'taxExemptIncome': float(tax_exempt),
                    'estimatedTax': float(estimated_tax),
                    'paidTaxes': float(taxes_paid),
                    'taxDue': float(tax_due),
                    'quarters': quarters
                }
            }), 200
        
        elif report_type == 'withholding':
            return jsonify({'withholdings': []}), 200
        elif report_type == 'donor':
            return jsonify({'donors': []}), 200
        elif report_type == '1099':
            return jsonify({'contractors': []}), 200
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
        
        if format_type != 'csv':
            return jsonify({'error': 'Only CSV export is currently supported'}), 400
        
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)
        
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
        
        taxable_income = float(total_income) - float(tax_exempt)
        estimated_tax = taxable_income * 0.05
        tax_due = max(0.0, estimated_tax - float(taxes_paid))
        
        writer.writerow(['Tax Summary Report'])
        writer.writerow([f'Year: {year}'])
        writer.writerow([])
        writer.writerow(['INCOME STATEMENT SUMMARY'])
        writer.writerow(['Description', 'Amount (GHS)'])
        writer.writerow(['Total Revenue', f"{float(total_income):,.2f}"])
        writer.writerow(['Total Expenses', f"{float(total_expenses):,.2f}"])
        writer.writerow(['Net Income', f"{float(total_income) - float(total_expenses):,.2f}"])
        writer.writerow([])
        writer.writerow(['TAX CALCULATION'])
        writer.writerow(['Description', 'Amount (GHS)'])
        writer.writerow(['Total Income', f"{float(total_income):,.2f}"])
        writer.writerow(['Tax-Exempt Income', f"{float(tax_exempt):,.2f}"])
        writer.writerow(['Taxable Income', f"{taxable_income:,.2f}"])
        writer.writerow(['Estimated Tax (5%)', f"{estimated_tax:,.2f}"])
        writer.writerow(['Taxes Paid', f"{float(taxes_paid):,.2f}"])
        writer.writerow(['Tax Due', f"{tax_due:,.2f}"])
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=tax_report_{report_type}_{year}.csv'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting tax report: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== LEAVE ROUTES ====================

@accounting_bp.route('/leave/balances', methods=['GET'])
@token_required
def get_leave_balances():
    """Get leave balances"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        year = request.args.get('year', type=int, default=datetime.now().year)
        employee_id = request.args.get('employee_id', type=int)
        leave_type = request.args.get('leave_type')
        
        query = LeaveBalance.query.join(Employee).filter(
            Employee.church_id == church_id,
            LeaveBalance.year == year
        )
        
        if employee_id:
            query = query.filter(LeaveBalance.employee_id == employee_id)
        
        if leave_type:
            leave_type_obj = LeaveType.query.filter_by(code=leave_type).first()
            if leave_type_obj:
                query = query.filter(LeaveBalance.leave_type_id == leave_type_obj.id)
        
        balances = query.all()
        
        result = []
        for balance in balances:
            # Safely get employee name
            employee_name = None
            if balance.employee:
                try:
                    # Try to get full name safely
                    if hasattr(balance.employee, 'full_name'):
                        if callable(balance.employee.full_name):
                            employee_name = balance.employee.full_name()
                        else:
                            employee_name = balance.employee.full_name
                    else:
                        # Fallback to first_name + last_name
                        first = getattr(balance.employee, 'first_name', '')
                        last = getattr(balance.employee, 'last_name', '')
                        employee_name = f"{first} {last}".strip() or f"Employee {balance.employee.id}"
                except Exception as e:
                    logger.warning(f"Error getting employee name: {e}")
                    employee_name = f"Employee {balance.employee.id}"
            
            # Get leave type name safely
            leave_type_name = None
            if balance.leave_type:
                leave_type_name = balance.leave_type.code if hasattr(balance.leave_type, 'code') else str(balance.leave_type)
            
            balance_dict = {
                'id': balance.id,
                'employee_id': balance.employee_id,
                'employee_name': employee_name,
                'leave_type': leave_type_name,
                'year': balance.year,
                'annual_entitlement': balance.total_days,
                'used': balance.used_days,
                'remaining': balance.remaining_days
            }
            result.append(balance_dict)
        
        return jsonify({'balances': result}), 200
        
    except Exception as e:
        logger.error(f"Error fetching leave balances: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@accounting_bp.route('/leave/requests', methods=['GET'])
@token_required
def get_leave_requests():
    """Get leave requests"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        status = request.args.get('status')
        stage = request.args.get('stage')
        employee_id = request.args.get('employee_id', type=int)
        
        query = LeaveRequest.query.join(Employee).filter(
            Employee.church_id == church_id
        )
        
        if stage == 'pending_pastor':
            query = query.filter(LeaveRequest.status == 'PENDING_PASTOR')
        elif stage == 'pending_allowance':
            query = query.filter(
                LeaveRequest.status == 'APPROVED',
                LeaveRequest.allowance_processed == False
            )
        elif stage == 'pending_treasurer':
            query = query.filter(
                LeaveRequest.allowance_processed == True,
                LeaveRequest.allowance_approved == False
            )
        elif stage == 'pending_payment':
            query = query.filter(
                LeaveRequest.allowance_approved == True,
                LeaveRequest.posted_to_ledger == False
            )
        elif status and status != 'all':
            query = query.filter(LeaveRequest.status == status.upper())
        
        if employee_id:
            query = query.filter(LeaveRequest.employee_id == employee_id)
        
        requests = query.order_by(LeaveRequest.created_at.desc()).all()
        
        result = []
        for req in requests:
            # Safely get employee name
            employee_name = None
            employee_data = None
            if req.employee:
                try:
                    # Try to get full name safely
                    if hasattr(req.employee, 'full_name'):
                        if callable(req.employee.full_name):
                            employee_name = req.employee.full_name()
                        else:
                            employee_name = req.employee.full_name
                    else:
                        # Fallback to first_name + last_name
                        first = getattr(req.employee, 'first_name', '')
                        last = getattr(req.employee, 'last_name', '')
                        employee_name = f"{first} {last}".strip() or f"Employee {req.employee.id}"
                    
                    employee_data = {
                        'id': req.employee.id,
                        'name': employee_name,
                        'position': getattr(req.employee, 'position', None),
                        'department': getattr(req.employee, 'department', None)
                    }
                except Exception as e:
                    logger.warning(f"Error getting employee name: {e}")
                    employee_name = f"Employee {req.employee.id}"
                    employee_data = {
                        'id': req.employee.id,
                        'name': employee_name,
                        'position': None,
                        'department': None
                    }
            
            # Safely get leave type
            leave_type_name = None
            if req.leave_type:
                leave_type_name = req.leave_type.code if hasattr(req.leave_type, 'code') else str(req.leave_type)
            
            req_dict = {
                'id': req.id,
                'employee_id': req.employee_id,
                'employee': employee_data,
                'employee_name': employee_name,
                'leave_type': leave_type_name,
                'start_date': req.start_date.isoformat() if req.start_date else None,
                'end_date': req.end_date.isoformat() if req.end_date else None,
                'days_requested': req.days_requested,
                'reason': req.reason,
                'status': req.status,
                'allowance_processed': req.allowance_processed,
                'allowance_amount': float(req.allowance_amount) if req.allowance_amount else 0,
                'allowance_approved': req.allowance_approved,
                'posted_to_ledger': req.posted_to_ledger,
                'created_at': req.created_at.isoformat() if req.created_at else None,
                'pastor_at': req.pastor_at.isoformat() if req.pastor_at else None,
                'allowance_processed_at': req.allowance_processed_at.isoformat() if req.allowance_processed_at else None,
                'allowance_approved_at': req.allowance_approved_at.isoformat() if req.allowance_approved_at else None,
                'posted_at': req.posted_at.isoformat() if req.posted_at else None,
            }
            result.append(req_dict)
        
        return jsonify({'requests': result}), 200
        
    except Exception as e:
        logger.error(f"Error fetching leave requests: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@accounting_bp.route('/leave/requests/<int:request_id>', methods=['GET'])
@token_required
def get_leave_request(request_id):
    """Get single leave request"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if leave_request.employee and leave_request.employee.church_id != church_id:
            return jsonify({'error': 'Access denied'}), 403
        
        # Safely get employee name
        employee_name = None
        employee_data = None
        if leave_request.employee:
            try:
                if hasattr(leave_request.employee, 'full_name'):
                    if callable(leave_request.employee.full_name):
                        employee_name = leave_request.employee.full_name()
                    else:
                        employee_name = leave_request.employee.full_name
                else:
                    first = getattr(leave_request.employee, 'first_name', '')
                    last = getattr(leave_request.employee, 'last_name', '')
                    employee_name = f"{first} {last}".strip() or f"Employee {leave_request.employee.id}"
                
                employee_data = {
                    'id': leave_request.employee.id,
                    'name': employee_name,
                    'position': getattr(leave_request.employee, 'position', None),
                    'department': getattr(leave_request.employee, 'department', None)
                }
            except Exception as e:
                logger.warning(f"Error getting employee name: {e}")
                employee_name = f"Employee {leave_request.employee.id}"
                employee_data = {
                    'id': leave_request.employee.id,
                    'name': employee_name,
                    'position': None,
                    'department': None
                }
        
        result = {
            'id': leave_request.id,
            'employee_id': leave_request.employee_id,
            'employee': employee_data,
            'employee_name': employee_name,
            'leave_type': leave_request.leave_type.code if leave_request.leave_type else None,
            'start_date': leave_request.start_date.isoformat() if leave_request.start_date else None,
            'end_date': leave_request.end_date.isoformat() if leave_request.end_date else None,
            'days_requested': leave_request.days_requested,
            'reason': leave_request.reason,
            'status': leave_request.status,
            'allowance_processed': leave_request.allowance_processed,
            'allowance_amount': float(leave_request.allowance_amount) if leave_request.allowance_amount else 0,
            'allowance_approved': leave_request.allowance_approved,
            'posted_to_ledger': leave_request.posted_to_ledger,
            'journal_entry_id': leave_request.journal_entry_id,
            'created_at': leave_request.created_at.isoformat() if leave_request.created_at else None,
            'admin_at': leave_request.admin_at.isoformat() if leave_request.admin_at else None,
            'admin_comments': leave_request.admin_comments,
            'pastor_at': leave_request.pastor_at.isoformat() if leave_request.pastor_at else None,
            'pastor_comments': leave_request.pastor_comments,
            'allowance_processed_at': leave_request.allowance_processed_at.isoformat() if leave_request.allowance_processed_at else None,
            'accountant_comments': leave_request.accountant_comments,
            'allowance_approved_at': leave_request.allowance_approved_at.isoformat() if leave_request.allowance_approved_at else None,
            'treasurer_comments': leave_request.treasurer_comments,
            'posted_at': leave_request.posted_at.isoformat() if leave_request.posted_at else None,
            'rejection_reason': leave_request.rejection_reason,
            'rejection_stage': leave_request.rejection_stage,
        }
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error fetching leave request: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
# Add this to your accounting_routes.py file (around the other leave endpoints)

@accounting_bp.route('/leave/types', methods=['GET'])
@token_required
def get_leave_types():
    """Get all leave types"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Get leave types
        leave_types = LeaveType.query.filter_by(is_active=True).order_by(LeaveType.code).all()
        
        result = []
        for lt in leave_types:
            result.append({
                'id': lt.id,
                'code': lt.code,
                'name': lt.name,
                'description': lt.description,
                'default_days': lt.default_days,
                'is_paid': lt.is_paid,
                'requires_approval': lt.requires_approval,
                'allowance_rate': float(lt.allowance_rate) if lt.allowance_rate else 0,
                'allowance_type': lt.allowance_type,
                'is_active': lt.is_active
            })
        
        return jsonify({'leave_types': result}), 200
        
    except Exception as e:
        logger.error(f"Error fetching leave types: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@accounting_bp.route('/leave/balances/initialize', methods=['POST'])
@token_required
def initialize_leave_balances():
    """Initialize leave balances for a year"""
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = g.current_user
        
        data = request.get_json() or {}
        year = data.get('year', datetime.now().year)
        
        # Get all active employees
        employees = Employee.query.filter_by(
            church_id=church_id,
            is_active=True
        ).all()
        
        # Get all leave types
        leave_types = LeaveType.query.filter_by(is_active=True).all()
        
        created_count = 0
        existing_count = 0
        
        for employee in employees:
            for leave_type in leave_types:
                # Check if balance already exists
                existing = LeaveBalance.query.filter_by(
                    employee_id=employee.id,
                    leave_type_id=leave_type.id,
                    year=year
                ).first()
                
                if not existing:
                    balance = LeaveBalance(
                        employee_id=employee.id,
                        leave_type_id=leave_type.id,
                        year=year,
                        total_days=leave_type.default_days,
                        used_days=0,
                        remaining_days=leave_type.default_days
                    )
                    db.session.add(balance)
                    created_count += 1
                else:
                    existing_count += 1
        
        db.session.commit()
        
        return jsonify({
            'message': f'Leave balances initialized for year {year}',
            'created': created_count,
            'existing': existing_count,
            'total': created_count + existing_count
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error initializing leave balances: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    

@accounting_bp.route('/leave/requests', methods=['POST'])
@token_required
def create_leave_request():
    """Create leave request (Admin/HR creates from printed form)"""
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = g.current_user
        
        data = request.get_json()
        
        required_fields = ['employee_id', 'leave_type', 'start_date', 'end_date']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing field: {field}'}), 400
        
        start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00')).date()
        end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00')).date()
        
        days_requested = (end_date - start_date).days + 1
        
        if days_requested <= 0:
            return jsonify({'error': 'End date must be after start date'}), 400
        
        leave_type = LeaveType.query.filter_by(code=data['leave_type']).first()
        if not leave_type:
            return jsonify({'error': 'Invalid leave type'}), 400
        
        if leave_type.is_paid:
            balance = LeaveBalance.query.filter_by(
                employee_id=data['employee_id'],
                leave_type_id=leave_type.id,
                year=start_date.year
            ).first()
            
            if not balance:
                return jsonify({'error': 'Leave balance not found for this employee'}), 404
            
            if balance.remaining_days < days_requested:
                return jsonify({
                    'error': 'Insufficient leave balance',
                    'available': balance.remaining_days,
                    'requested': days_requested
                }), 400
        
        leave_request = LeaveRequest(
            employee_id=data['employee_id'],
            leave_type_id=leave_type.id,
            start_date=start_date,
            end_date=end_date,
            days_requested=days_requested,
            reason=data.get('reason', ''),
            status='PENDING_PASTOR',
            admin_id=current_user.id,
            admin_at=datetime.utcnow(),
            admin_comments=data.get('admin_comments', '')
        )
        
        db.session.add(leave_request)
        db.session.commit()
        
        return jsonify({
            'message': 'Leave request created successfully and sent to Pastor for approval',
            'request': {'id': leave_request.id}
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating leave request: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/leave/requests/<int:request_id>/pastor-approve', methods=['POST'])
@token_required
def pastor_approve_leave(request_id):
    """Pastor approve leave request"""
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = g.current_user
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if leave_request.employee and leave_request.employee.church_id != church_id:
            return jsonify({'error': 'Access denied'}), 403
        
        if leave_request.status != 'PENDING_PASTOR':
            return jsonify({'error': f'Cannot approve at current status: {leave_request.status}'}), 400
        
        data = request.get_json() or {}
        
        leave_request.status = 'APPROVED'
        leave_request.pastor_id = current_user.id
        leave_request.pastor_at = datetime.utcnow()
        leave_request.pastor_comments = data.get('comments', '')
        
        balance = LeaveBalance.query.filter_by(
            employee_id=leave_request.employee_id,
            leave_type_id=leave_request.leave_type_id,
            year=leave_request.start_date.year
        ).first()
        
        if balance:
            balance.used_days += leave_request.days_requested
            balance.remaining_days -= leave_request.days_requested
        
        db.session.commit()
        
        return jsonify({'message': 'Leave request approved by Pastor'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving leave: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/leave/requests/<int:request_id>/process-allowance', methods=['POST'])
@token_required
def process_leave_allowance(request_id):
    """Accountant processes leave allowance"""
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = g.current_user
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if leave_request.employee and leave_request.employee.church_id != church_id:
            return jsonify({'error': 'Access denied'}), 403
        
        if leave_request.status != 'APPROVED':
            return jsonify({'error': 'Request must be approved first'}), 400
        
        if leave_request.allowance_processed:
            return jsonify({'error': 'Allowance already processed'}), 400
        
        data = request.get_json() or {}
        
        leave_request.allowance_processed = True
        leave_request.allowance_processed_at = datetime.utcnow()
        leave_request.accountant_id = current_user.id
        leave_request.accountant_comments = data.get('comments', '')
        
        if data.get('allowance_amount'):
            leave_request.allowance_amount = data['allowance_amount']
        
        db.session.commit()
        
        return jsonify({'message': 'Leave allowance processed and sent to Treasurer'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing allowance: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/leave/requests/<int:request_id>/treasurer-approve', methods=['POST'])
@token_required
def treasurer_approve_allowance(request_id):
    """Treasurer approves leave allowance"""
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = g.current_user
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if leave_request.employee and leave_request.employee.church_id != church_id:
            return jsonify({'error': 'Access denied'}), 403
        
        if not leave_request.allowance_processed:
            return jsonify({'error': 'Allowance not processed yet'}), 400
        
        if leave_request.allowance_approved:
            return jsonify({'error': 'Allowance already approved'}), 400
        
        data = request.get_json() or {}
        
        leave_request.allowance_approved = True
        leave_request.allowance_approved_at = datetime.utcnow()
        leave_request.treasurer_id = current_user.id
        leave_request.treasurer_comments = data.get('comments', '')
        
        db.session.commit()
        
        return jsonify({'message': 'Allowance approved by Treasurer'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving allowance: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500



@accounting_bp.route('/leave/requests/<int:request_id>/post-to-ledger', methods=['POST'])
@token_required
def post_leave_to_ledger(request_id):
    """Accountant posts leave payment to ledger"""
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = g.current_user
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if leave_request.employee and leave_request.employee.church_id != church_id:
            return jsonify({'error': 'Access denied'}), 403
        
        if not leave_request.allowance_approved:
            return jsonify({'error': 'Allowance not approved yet'}), 400
        
        if leave_request.posted_to_ledger:
            return jsonify({'error': 'Already posted to ledger'}), 400
        
        # Generate entry number
        today = datetime.utcnow()
        date_prefix = today.strftime('%Y%m%d')
        
        last_entry = JournalEntry.query.filter(
            JournalEntry.entry_number.like(f'JE-{date_prefix}-%'),
            JournalEntry.church_id == church_id
        ).order_by(JournalEntry.entry_number.desc()).first()
        
        if last_entry:
            seq = int(last_entry.entry_number.split('-')[-1]) + 1
        else:
            seq = 1
        
        entry_number = f"JE-{date_prefix}-{seq:03d}"
        
        # Create journal entry
        journal_entry = JournalEntry(
            church_id=church_id,
            entry_number=entry_number,
            entry_date=today.date(),
            description=f"Leave payment - {leave_request.employee.first_name} {leave_request.employee.last_name}",
            reference=f"LEAVE-{leave_request.id}",
            status='POSTED',
            created_by=current_user.id,
            created_at=today
        )
        db.session.add(journal_entry)
        db.session.flush()
        
        # Get or create leave expense account
        expense_account = Account.query.filter_by(
            church_id=church_id,
            account_type='EXPENSE',
            name='Leave Allowance Expense'
        ).first()
        
        if not expense_account:
            expense_account = Account(
                church_id=church_id,
                account_code='LEAVE_EXP',
                name='Leave Allowance Expense',
                account_type='EXPENSE',
                category='Staff Costs',
                normal_balance='debit',
                is_active=True
            )
            db.session.add(expense_account)
            db.session.flush()
        
        # Get or create bank account
        bank_account = Account.query.filter_by(
            church_id=church_id,
            account_type='ASSET',
            category='Bank'
        ).first()
        
        if not bank_account:
            bank_account = Account(
                church_id=church_id,
                account_code='BANK',
                name='Bank Account',
                account_type='ASSET',
                category='Bank',
                normal_balance='debit',
                is_active=True
            )
            db.session.add(bank_account)
            db.session.flush()
        
        # Create journal lines - REMOVE account_code and account_name
        debit_line = JournalLine(
            journal_entry_id=journal_entry.id,
            account_id=expense_account.id,
            debit=float(leave_request.allowance_amount),
            credit=0
        )
        db.session.add(debit_line)
        
        credit_line = JournalLine(
            journal_entry_id=journal_entry.id,
            account_id=bank_account.id,
            debit=0,
            credit=float(leave_request.allowance_amount)
        )
        db.session.add(credit_line)
        
        leave_request.posted_to_ledger = True
        leave_request.posted_at = datetime.utcnow()
        leave_request.posted_by = current_user.id
        leave_request.journal_entry_id = journal_entry.id
        leave_request.status = 'PAID'
        
        db.session.commit()
        
        return jsonify({
            'message': 'Posted to ledger',
            'journal_entry_id': journal_entry.id,
            'entry_number': entry_number
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error posting to ledger: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@accounting_bp.route('/leave/requests/<int:request_id>/reject', methods=['POST'])
@token_required
def reject_leave_request(request_id):
    """Reject leave request at current stage"""
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = g.current_user
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if leave_request.employee and leave_request.employee.church_id != church_id:
            return jsonify({'error': 'Access denied'}), 403
        
        data = request.get_json() or {}
        reason = data.get('reason', 'No reason provided')
        
        if leave_request.status == 'PENDING_PASTOR':
            leave_request.status = 'REJECTED'
            leave_request.rejection_stage = 'pastor'
        elif leave_request.allowance_processed and not leave_request.allowance_approved:
            leave_request.status = 'REJECTED'
            leave_request.rejection_stage = 'treasurer'
        else:
            return jsonify({'error': 'Cannot reject at this stage'}), 400
        
        leave_request.rejected_by = current_user.id
        leave_request.rejected_at = datetime.utcnow()
        leave_request.rejection_reason = reason
        
        db.session.commit()
        
        return jsonify({'message': 'Leave request rejected'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting leave: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@accounting_bp.route('/leave/calendar', methods=['GET'])
@token_required
def get_leave_calendar():
    """Get leave calendar events - shows approved and paid leaves"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        
        # Show both APPROVED and PAID leaves
        query = LeaveRequest.query.join(Employee).filter(
            Employee.church_id == church_id,
            LeaveRequest.status.in_(['APPROVED', 'PAID'])
        )
        
        if month and year:
            start_date = datetime(year, month, 1).date()
            if month == 12:
                end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
            else:
                end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
            
            query = query.filter(
                LeaveRequest.start_date <= end_date,
                LeaveRequest.end_date >= start_date
            )
        elif year:
            start_date = datetime(year, 1, 1).date()
            end_date = datetime(year, 12, 31).date()
            query = query.filter(
                LeaveRequest.start_date <= end_date,
                LeaveRequest.end_date >= start_date
            )
        
        requests = query.all()
        
        events = []
        for req in requests:
            # Get employee name - handle both property and method
            employee_name = None
            if req.employee:
                if hasattr(req.employee, 'full_name'):
                    if callable(req.employee.full_name):
                        employee_name = req.employee.full_name()
                    else:
                        employee_name = req.employee.full_name
                else:
                    employee_name = f"{req.employee.first_name} {req.employee.last_name}"
            
            # Get leave type code
            leave_type_code = req.leave_type.code if req.leave_type else 'unknown'
            
            events.append({
                'id': req.id,
                'title': f"{employee_name} - {leave_type_code}",
                'start': req.start_date.isoformat(),
                'end': (req.end_date + timedelta(days=1)).isoformat(),
                'extendedProps': {
                    'employee_id': req.employee_id,
                    'employee_name': employee_name,
                    'leave_type': leave_type_code,
                    'days': req.days_requested,
                    'status': req.status,
                    'allowance_amount': float(req.allowance_amount) if req.allowance_amount else 0
                }
            })
        
        return jsonify(events), 200
        
    except Exception as e:
        logger.error(f"Error fetching calendar: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@accounting_bp.route('/leave/workflow-summary', methods=['GET'])
@token_required
def get_workflow_summary():
    """Get workflow summary counts for leave management dashboard"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        summary = {
            'pending_pastor': LeaveRequest.query.join(Employee).filter(
                Employee.church_id == church_id,
                LeaveRequest.status == 'PENDING_PASTOR'
            ).count(),
            'pending_allowance': LeaveRequest.query.join(Employee).filter(
                Employee.church_id == church_id,
                LeaveRequest.status == 'APPROVED',
                LeaveRequest.allowance_processed == False
            ).count(),
            'pending_treasurer': LeaveRequest.query.join(Employee).filter(
                Employee.church_id == church_id,
                LeaveRequest.allowance_processed == True,
                LeaveRequest.allowance_approved == False
            ).count(),
            'pending_payment': LeaveRequest.query.join(Employee).filter(
                Employee.church_id == church_id,
                LeaveRequest.allowance_approved == True,
                LeaveRequest.posted_to_ledger == False
            ).count(),
            'completed': LeaveRequest.query.join(Employee).filter(
                Employee.church_id == church_id,
                LeaveRequest.status == 'PAID'
            ).count(),
            'total_requests': LeaveRequest.query.join(Employee).filter(
                Employee.church_id == church_id
            ).count()
        }
        
        return jsonify(summary), 200
        
    except Exception as e:
        logger.error(f"Error getting workflow summary: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== DEBUG ENDPOINTS ====================

@accounting_bp.route('/test', methods=['GET'])
def test():
    """Simple test endpoint"""
    return jsonify({
        'status': 'ok',
        'message': 'Accounting blueprint is working!'
    }), 200