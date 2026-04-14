# app/routes/treasurer_routes.py
from flask import Blueprint, request, jsonify, g, make_response
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import Budget, Transaction, Account, User, AuditLog, Church, JournalEntry, JournalLine
from app.routes.accounting_routes import get_account_balance, ensure_user_church  # Add this import
from app.extensions import db
from datetime import datetime, timedelta, date
from sqlalchemy import func, and_, or_, desc, extract
import traceback
import logging

logger = logging.getLogger(__name__)
# treasurer_bp = Blueprint('treasurer', __name__)
treasurer_bp = Blueprint('treasurer', __name__, url_prefix='/api/treasurer')

# Import token_required from auth_routes
from app.routes.auth_routes import token_required

@treasurer_bp.route('/financial-overview', methods=['GET'])
@token_required
def get_financial_overview():
    """Get financial overview for dashboard"""
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
        
        # Calculate totals
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
        
        # Get asset accounts for balance sheet
        asset_accounts = Account.query.filter_by(
            church_id=church_id, account_type='ASSET', is_active=True
        ).all()
        
        total_assets = 0
        for acc in asset_accounts:
            total_assets += acc.current_balance or 0
        
        # Get liability accounts
        liability_accounts = Account.query.filter_by(
            church_id=church_id, account_type='LIABILITY', is_active=True
        ).all()
        
        total_liabilities = 0
        for acc in liability_accounts:
            total_liabilities += acc.current_balance or 0
        
        # Get equity accounts
        equity_accounts = Account.query.filter_by(
            church_id=church_id, account_type='EQUITY', is_active=True
        ).all()
        
        total_equity = 0
        for acc in equity_accounts:
            total_equity += acc.current_balance or 0
        
        # Get income by category
        income_by_category = []
        for acc in revenue_accounts:
            balance = get_account_balance(acc.id, start_date, end_date)
            if balance > 0:
                income_by_category.append({
                    'category': acc.category or 'Other',
                    'amount': float(balance)
                })
        
        # Get expenses by category
        expenses_by_category = []
        for acc in expense_accounts:
            balance = get_account_balance(acc.id, start_date, end_date)
            if balance > 0:
                expenses_by_category.append({
                    'category': acc.category or 'Other',
                    'amount': float(balance)
                })
        
        # Calculate percentage changes
        # Get previous period for comparison
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
        
        return jsonify({
            'success': True,
            'period': {
                'startDate': start_date.isoformat(),
                'endDate': end_date.isoformat(),
                'period': period
            },
            'summary': {
                'totalIncome': float(total_income),
                'totalExpenses': float(total_expenses),
                'netIncome': float(total_income - total_expenses),
                'incomeChange': round(income_change, 1),
                'expenseChange': round(expense_change, 1)
            },
            'balanceSheet': {
                'totalAssets': float(total_assets),
                'totalLiabilities': float(total_liabilities),
                'totalEquity': float(total_equity)
            },
            'incomeByCategory': income_by_category,
            'expensesByCategory': expenses_by_category
        }), 200
        
    except Exception as e:
        logger.error(f"Error in financial-overview endpoint: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
@treasurer_bp.route('/income-vs-expenses', methods=['GET'])
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

    

@treasurer_bp.route('/category-breakdown', methods=['GET'])
@token_required
def get_category_breakdown():
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
                    'value': float(balance),
                    'color': '#10b981'
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
                    'value': float(balance),
                    'color': '#ef4444'
                })
        
        return jsonify({
            'income': income_categories,
            'expenses': expense_categories
        }), 200
        
    except Exception as e:
        logger.error(f"Error in category-breakdown endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
        
@treasurer_bp.route('/income-expense-trends', methods=['GET'])
@token_required
def get_income_expense_trends():
    """Get income and expense trends over time"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        months = request.args.get('months', 6, type=int)
        
        # Get revenue and expense accounts
        revenue_accounts = Account.query.filter_by(
            church_id=church_id, account_type='REVENUE', is_active=True
        ).all()
        
        expense_accounts = Account.query.filter_by(
            church_id=church_id, account_type='EXPENSE', is_active=True
        ).all()
        
        # Generate monthly data
        trends = []
        end_date = datetime.utcnow().date()
        
        for i in range(months - 1, -1, -1):
            # Calculate month start and end
            month_date = date(end_date.year, end_date.month, 1) - timedelta(days=i * 30)
            month_start = date(month_date.year, month_date.month, 1)
            
            if month_date.month == 12:
                month_end = date(month_date.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(month_date.year, month_date.month + 1, 1) - timedelta(days=1)
            
            # Calculate monthly income
            monthly_income = 0
            for acc in revenue_accounts:
                balance = get_account_balance(acc.id, month_start, month_end)
                if balance > 0:
                    monthly_income += balance
            
            # Calculate monthly expenses
            monthly_expenses = 0
            for acc in expense_accounts:
                balance = get_account_balance(acc.id, month_start, month_end)
                if balance > 0:
                    monthly_expenses += balance
            
            trends.append({
                'month': month_start.strftime('%b'),
                'income': float(monthly_income),
                'expenses': float(monthly_expenses),
                'net': float(monthly_income - monthly_expenses)
            })
        
        return jsonify(trends), 200
        
    except Exception as e:
        logger.error(f"Error in trends endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500

@treasurer_bp.route('/recent-transactions', methods=['GET'])
@token_required
def get_recent_transactions():
    """Get recent transactions for the dashboard"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        limit = request.args.get('limit', 10, type=int)
        
        # Get recent journal entries
        journal_entries = JournalEntry.query.filter_by(
            church_id=church_id,
            status='POSTED'
        ).order_by(
            JournalEntry.entry_date.desc(),
            JournalEntry.created_at.desc()
        ).limit(limit).all()
        
        transactions = []
        for je in journal_entries:
            transactions.append({
                'id': je.id,
                'date': je.entry_date.isoformat(),
                'description': je.description or 'Journal Entry',
                'reference': je.entry_number,
                'amount': float(sum(line.debit for line in je.lines) or sum(line.credit for line in je.lines)),
                'type': 'journal'
            })
        
        return jsonify({'transactions': transactions}), 200
        
    except Exception as e:
        logger.error(f"Error fetching recent transactions: {str(e)}")
        return jsonify({'error': str(e)}), 500


@treasurer_bp.route('/alerts', methods=['GET'])
@token_required
def get_treasurer_alerts():
    """Get alerts for the treasurer dashboard"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        alerts = []
        
        # Check for pending budgets
        pending_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).count()
        
        if pending_budgets > 0:
            alerts.append({
                'id': 1,
                'type': 'warning',
                'message': f'{pending_budgets} budget(s) pending approval',
                'severity': 'medium'
            })
        
        # Check for negative cash balance
        cash_accounts = Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'ASSET',
            Account.category == 'Cash'
        ).all()
        
        negative_cash = any(acc.current_balance < 0 for acc in cash_accounts)
        if negative_cash:
            alerts.append({
                'id': 2,
                'type': 'critical',
                'message': 'Negative cash balance detected',
                'severity': 'high'
            })
        
        return jsonify({'alerts': alerts}), 200
        
    except Exception as e:
        logger.error(f"Error fetching alerts: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
# ==================== HELPER FUNCTIONS ====================

def get_current_user():
    """Get current user from JWT token"""
    try:
        user_id = get_jwt_identity()
        if user_id:
            return User.query.get(int(user_id))
    except Exception as e:
        logger.warning(f"Error getting user from JWT: {e}")
    return None


def ensure_user_church(user=None):
    """Make sure user has a church_id, assign default if not"""
    if user is None:
        user = get_current_user()
    
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
            logger.info(f"Assigned user {user.id} to default church {default_church.id}")
    return user.church_id


@treasurer_bp.route('/cash-flow', methods=['GET'])
@token_required
def get_cash_flow():
    """Get cash flow statement for a period"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Get parameters
        period = request.args.get('period', 'month')  # month, quarter, year
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')
        account_id = request.args.get('accountId', type=int)
        
        # Set date range
        end_date = datetime.utcnow().date()
        if period == 'month':
            start_date = end_date.replace(day=1)
        elif period == 'quarter':
            quarter = (end_date.month - 1) // 3
            start_date = date(end_date.year, quarter * 3 + 1, 1)
        elif period == 'year':
            start_date = date(end_date.year, 1, 1)
        elif start_date_str and end_date_str:
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
        else:
            start_date = end_date - timedelta(days=30)
        
        # Get cash accounts
        if account_id:
            cash_accounts = Account.query.filter_by(id=account_id, church_id=church_id, is_active=True).all()
        else:
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
        
        # Calculate cash flow components
        operating_cash_flow = 0
        investing_cash_flow = 0
        financing_cash_flow = 0
        
        # Get revenue (operating inflow)
        revenue_accounts = Account.query.filter_by(
            church_id=church_id, account_type='REVENUE', is_active=True
        ).all()
        
        for acc in revenue_accounts:
            balance = get_account_balance(acc.id, start_date, end_date)
            if balance > 0:
                operating_cash_flow += balance
        
        # Get expenses (operating outflow)
        expense_accounts = Account.query.filter_by(
            church_id=church_id, account_type='EXPENSE', is_active=True
        ).all()
        
        for acc in expense_accounts:
            balance = get_account_balance(acc.id, start_date, end_date)
            if balance > 0:
                operating_cash_flow -= balance
        
        # Get asset purchases (investing outflow)
        asset_accounts = Account.query.filter_by(
            church_id=church_id, account_type='ASSET', is_active=True
        ).filter(
            ~Account.category.in_(['Cash', 'Bank'])
        ).all()
        
        for acc in asset_accounts:
            balance = get_account_balance(acc.id, start_date, end_date)
            if balance > 0:
                investing_cash_flow -= balance
        
        # Get loans/equity (financing inflow/outflow)
        liability_accounts = Account.query.filter_by(
            church_id=church_id, account_type='LIABILITY', is_active=True
        ).all()
        
        for acc in liability_accounts:
            balance = get_account_balance(acc.id, start_date, end_date)
            if balance > 0:
                financing_cash_flow += balance
            elif balance < 0:
                financing_cash_flow -= abs(balance)
        
        # Get beginning and ending cash balances
        beginning_cash = sum(get_account_balance(acc.id, None, start_date - timedelta(days=1)) for acc in cash_accounts)
        ending_cash = sum(get_account_balance(acc.id, None, end_date) for acc in cash_accounts)
        net_cash_flow = ending_cash - beginning_cash
        
        # Get monthly breakdown for chart
        monthly_data = []
        current_date = start_date
        while current_date <= end_date:
            month_start = current_date
            if current_date.month == 12:
                month_end = date(current_date.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(current_date.year, current_date.month + 1, 1) - timedelta(days=1)
            
            month_operating = 0
            for acc in revenue_accounts:
                balance = get_account_balance(acc.id, month_start, month_end)
                if balance > 0:
                    month_operating += balance
            for acc in expense_accounts:
                balance = get_account_balance(acc.id, month_start, month_end)
                if balance > 0:
                    month_operating -= balance
            
            monthly_data.append({
                'month': month_start.strftime('%b'),
                'operating': month_operating,
                'net': month_operating
            })
            
            current_date = month_end + timedelta(days=1)
        
        return jsonify({
            'period': {
                'startDate': start_date.isoformat(),
                'endDate': end_date.isoformat(),
                'period': period
            },
            'cashAccounts': [{
                'id': acc.id,
                'name': acc.name,
                'balance': float(acc.current_balance) if acc.current_balance else 0
            } for acc in cash_accounts],
            'operatingCashFlow': float(operating_cash_flow),
            'investingCashFlow': float(investing_cash_flow),
            'financingCashFlow': float(financing_cash_flow),
            'netCashFlow': float(net_cash_flow),
            'beginningCash': float(beginning_cash),
            'endingCash': float(ending_cash),
            'monthlyData': monthly_data,
            'transactions': []
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting cash flow: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
# ==================== DASHBOARD STATS ====================

@treasurer_bp.route('/dashboard-stats', methods=['GET', 'OPTIONS'])
@token_required
def get_dashboard_stats():
    """Get treasurer dashboard statistics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Get current month date range
        today = datetime.utcnow()
        first_day = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Calculate total income (all posted income transactions)
        total_income = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        # Calculate total expenses (all posted expense transactions)
        total_expenses = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'EXPENSE',
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        # Calculate net balance (assets - liabilities)
        assets = db.session.query(func.sum(Account.current_balance)).filter(
            Account.church_id == church_id,
            Account.account_type == 'ASSET',
            Account.is_active == True
        ).scalar() or 0
        
        liabilities = db.session.query(func.sum(Account.current_balance)).filter(
            Account.church_id == church_id,
            Account.account_type == 'LIABILITY',
            Account.is_active == True
        ).scalar() or 0
        
        net_balance = assets - liabilities
        
        # Count pending approvals (budgets and transactions)
        pending_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).count()
        
        pending_transactions = Transaction.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).count()
        
        pending_approvals = pending_budgets + pending_transactions
        
        # Get total account balance
        account_balance = db.session.query(func.sum(Account.current_balance)).filter(
            Account.church_id == church_id,
            Account.is_active == True
        ).scalar() or 0
        
        return jsonify({
            'totalIncome': float(total_income),
            'totalExpenses': float(total_expenses),
            'netBalance': float(net_balance),
            'pendingApprovals': pending_approvals,
            'pendingTransactions': pending_transactions,
            'accountBalance': float(account_balance),
            'pendingBudgets': pending_budgets
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting treasurer dashboard stats: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get dashboard stats: {str(e)}'}), 500


# ==================== BUDGET ENDPOINTS ====================

@treasurer_bp.route('/budgets', methods=['POST', 'OPTIONS'])
@token_required
def create_budget():
    """Create a new budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = get_current_user()
        data = request.get_json()
        
        print(f"📝 Creating budget with data: {data}")
        
        # Create new budget
        budget = Budget(
            church_id=church_id,
            name=data.get('name'),
            description=data.get('description', ''),
            department=data.get('department'),
            fiscal_year=data.get('fiscal_year', datetime.now().year),
            period=data.get('period', 'annual'),
            amount=data.get('amount', 0),
            priority=data.get('priority', 'MEDIUM'),
            budget_type=data.get('budget_type', 'EXPENSE'),
            justification=data.get('justification', ''),
            status='DRAFT',
            created_by=current_user.id if current_user else None,
            account_id=data.get('account_id'),
            account_code=data.get('account_code'),
            # Initialize monthly amounts
            january=data.get('monthly', {}).get('january', 0),
            february=data.get('monthly', {}).get('february', 0),
            march=data.get('monthly', {}).get('march', 0),
            april=data.get('monthly', {}).get('april', 0),
            may=data.get('monthly', {}).get('may', 0),
            june=data.get('monthly', {}).get('june', 0),
            july=data.get('monthly', {}).get('july', 0),
            august=data.get('monthly', {}).get('august', 0),
            september=data.get('monthly', {}).get('september', 0),
            october=data.get('monthly', {}).get('october', 0),
            november=data.get('monthly', {}).get('november', 0),
            december=data.get('monthly', {}).get('december', 0)
        )
        
        # Add optional dates if provided
        if data.get('start_date'):
            budget.start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00')).date()
        if data.get('end_date'):
            budget.end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00')).date()
        
        db.session.add(budget)
        db.session.commit()
        
        print(f"✅ Budget created with ID: {budget.id}")
        
        return jsonify({
            'message': 'Budget created successfully',
            'budget': budget.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to create budget: {str(e)}'}), 500


@treasurer_bp.route('/budgets', methods=['GET', 'OPTIONS'])
@token_required
def get_budgets():
    """Get budgets with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Build query
        query = Budget.query.filter_by(church_id=church_id)
        
        # Apply filters
        status = request.args.get('status')
        if status and status != 'all':
            query = query.filter_by(status=status.upper())
        
        department = request.args.get('department')
        if department and department != 'all':
            query = query.filter_by(department=department)
        
        search = request.args.get('search')
        if search:
            query = query.filter(
                or_(
                    Budget.name.ilike(f'%{search}%'),
                    Budget.description.ilike(f'%{search}%')
                )
            )
        
        # Get paginated results
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        paginated = query.order_by(
            Budget.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        # Format budgets
        budget_list = []
        for budget in paginated.items:
            budget_dict = budget.to_dict()
            submitter = User.query.get(budget.created_by)
            if submitter:
                budget_dict['submitted_by_name'] = submitter.full_name if submitter else 'Unknown'
            budget_list.append(budget_dict)
        
        # Calculate stats
        all_budgets = Budget.query.filter_by(church_id=church_id).all()
        stats = {
            'total': len(all_budgets),
            'pending': len([b for b in all_budgets if b.status == 'PENDING']),
            'approved': len([b for b in all_budgets if b.status == 'APPROVED']),
            'rejected': len([b for b in all_budgets if b.status == 'REJECTED']),
            'totalAmount': sum(float(b.amount) for b in all_budgets)
        }
        
        return jsonify({
            'budgets': budget_list,
            'stats': stats,
            'total': paginated.total,
            'pages': paginated.pages,
            'currentPage': paginated.page
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting budgets: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get budgets: {str(e)}'}), 500


@treasurer_bp.route('/budgets/<int:budget_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_budget(budget_id):
    """Get a single budget by ID"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        budget = Budget.query.filter_by(
            id=budget_id,
            church_id=church_id
        ).first()
        
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        return jsonify(budget.to_dict()), 200
        
    except Exception as e:
        logger.error(f"Error fetching budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@treasurer_bp.route('/budgets/<int:budget_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_budget(budget_id):
    """Update a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = get_current_user()
        data = request.get_json()
        
        budget = Budget.query.filter_by(
            id=budget_id,
            church_id=church_id
        ).first()
        
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        # Update fields
        if 'name' in data:
            budget.name = data['name']
        if 'description' in data:
            budget.description = data['description']
        if 'department' in data:
            budget.department = data['department']
        if 'fiscal_year' in data:
            budget.fiscal_year = data['fiscal_year']
        if 'amount' in data:
            budget.amount = data['amount']
        if 'priority' in data:
            budget.priority = data['priority']
        if 'budget_type' in data:
            budget.budget_type = data['budget_type']
        if 'justification' in data:
            budget.justification = data['justification']
        
        # If submitting for approval, change status to PENDING
        if data.get('submit_for_approval', False):
            budget.status = 'PENDING'
            budget.submitted_by = current_user.id if current_user else None
            budget.submitted_at = datetime.utcnow()
        
        budget.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Budget updated successfully',
            'budget': budget.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@treasurer_bp.route('/budgets/<int:budget_id>/submit', methods=['POST', 'OPTIONS'])
@token_required
def submit_budget_for_approval(budget_id):
    """Submit a budget for approval"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = get_current_user()
        
        budget = Budget.query.filter_by(
            id=budget_id,
            church_id=church_id
        ).first()
        
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        if budget.status != 'DRAFT':
            return jsonify({'error': f'Budget is already {budget.status.lower()}'}), 400
        
        budget.status = 'PENDING'
        budget.submitted_by = current_user.id if current_user else None
        budget.submitted_at = datetime.utcnow()
        budget.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Budget submitted for approval successfully',
            'budget': budget.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@treasurer_bp.route('/budgets/<int:budget_id>/delete', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_budget(budget_id):
    """Delete a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        budget = Budget.query.filter_by(
            id=budget_id,
            church_id=church_id
        ).first()
        
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        if budget.status != 'DRAFT':
            return jsonify({'error': 'Only draft budgets can be deleted'}), 400
        
        db.session.delete(budget)
        db.session.commit()
        
        return jsonify({'message': 'Budget deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting budget: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==================== BUDGET VARIANCE ANALYSIS ====================

@treasurer_bp.route('/budget-variance', methods=['GET', 'OPTIONS'])
@token_required
def get_budget_variance():
    """Get budget vs actual variance analysis"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        year = request.args.get('year', datetime.now().year, type=int)
        month = request.args.get('month', type=int)
        budget_type = request.args.get('type', 'all')
        department = request.args.get('department')
        
        # Query approved budgets
        query = Budget.query.filter_by(
            church_id=church_id,
            fiscal_year=year,
            status='APPROVED'
        )
        
        if budget_type != 'all':
            query = query.filter_by(budget_type=budget_type.upper())
        
        if department:
            query = query.filter_by(department=department)
        
        budgets = query.all()
        
        # Get actuals from journal entries
        from app.models import JournalEntry, JournalLine
        from decimal import Decimal
        
        variance_data = []
        total_budget = Decimal('0')
        total_actual = Decimal('0')
        total_variance = Decimal('0')
        
        for budget in budgets:
            # Build actual query
            actual_query = db.session.query(func.sum(JournalLine.debit - JournalLine.credit)).join(
                JournalEntry
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.status == 'POSTED',
                extract('year', JournalEntry.entry_date) == year
            )
            
            # Filter by month if specified
            if month:
                actual_query = actual_query.filter(extract('month', JournalEntry.entry_date) == month)
            
            # Filter by account if budget has account association
            if budget.account_id:
                actual_query = actual_query.filter(JournalLine.account_id == budget.account_id)
            elif budget.account_code:
                account = Account.query.filter_by(
                    account_code=budget.account_code,
                    church_id=church_id
                ).first()
                if account:
                    actual_query = actual_query.filter(JournalLine.account_id == account.id)
            
            actual_result = actual_query.scalar()
            actual = Decimal(str(actual_result)) if actual_result is not None else Decimal('0')
            
            # Convert budget amount to Decimal
            budget_amount = Decimal(str(budget.amount)) if budget.amount else Decimal('0')
            
            # Calculate variance
            variance = actual - budget_amount
            variance_percent = float((variance / budget_amount * 100)) if budget_amount > 0 else 0
            
            # Determine if variance is favorable
            is_favorable = False
            if budget.budget_type == 'REVENUE' and variance > 0:
                is_favorable = True
            elif budget.budget_type == 'EXPENSE' and variance < 0:
                is_favorable = True
            
            variance_data.append({
                'id': budget.id,
                'name': budget.name,
                'department': budget.department,
                'budget_type': budget.budget_type,
                'budget_amount': float(budget_amount),
                'actual_amount': float(actual),
                'variance': float(variance),
                'variance_percentage': round(variance_percent, 2),
                'status': 'favorable' if is_favorable else 'unfavorable'
            })
            
            total_budget += budget_amount
            total_actual += actual
            total_variance += variance
        
        return jsonify({
            'variance_data': variance_data,
            'summary': {
                'total_budget': float(total_budget),
                'total_actual': float(total_actual),
                'total_variance': float(total_variance),
                'variance_percentage': round(float(total_variance / total_budget * 100) if total_budget > 0 else 0, 2),
                'favorable_count': len([v for v in variance_data if v['status'] == 'favorable']),
                'unfavorable_count': len([v for v in variance_data if v['status'] == 'unfavorable'])
            },
            'year': year,
            'month': month
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting budget variance: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
@treasurer_bp.route('/budget-variance/export', methods=['GET', 'OPTIONS'])
@token_required
def export_budget_variance():
    """Export budget variance report as CSV or PDF"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        year = request.args.get('year', datetime.now().year, type=int)
        month = request.args.get('month', type=int)
        budget_type = request.args.get('type', 'all')
        format_type = request.args.get('format', 'csv').lower()
        
        # Get variance data (same logic as get_budget_variance)
        from decimal import Decimal
        from app.models import JournalEntry, JournalLine
        
        query = Budget.query.filter_by(
            church_id=church_id,
            fiscal_year=year,
            status='APPROVED'
        )
        
        if budget_type != 'all':
            query = query.filter_by(budget_type=budget_type.upper())
        
        budgets = query.all()
        
        # Build variance data
        variance_data = []
        total_budget = Decimal('0')
        total_actual = Decimal('0')
        
        for budget in budgets:
            # Build actual query
            actual_query = db.session.query(func.sum(JournalLine.debit - JournalLine.credit)).join(
                JournalEntry
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.status == 'POSTED',
                extract('year', JournalEntry.entry_date) == year
            )
            
            if month:
                actual_query = actual_query.filter(extract('month', JournalEntry.entry_date) == month)
            
            if budget.account_id:
                actual_query = actual_query.filter(JournalLine.account_id == budget.account_id)
            elif budget.account_code:
                account = Account.query.filter_by(
                    account_code=budget.account_code,
                    church_id=church_id
                ).first()
                if account:
                    actual_query = actual_query.filter(JournalLine.account_id == account.id)
            
            actual_result = actual_query.scalar()
            actual = Decimal(str(actual_result)) if actual_result is not None else Decimal('0')
            budget_amount = Decimal(str(budget.amount)) if budget.amount else Decimal('0')
            
            variance = actual - budget_amount
            variance_percent = float((variance / budget_amount * 100)) if budget_amount > 0 else 0
            
            is_favorable = False
            if budget.budget_type == 'REVENUE' and variance > 0:
                is_favorable = True
            elif budget.budget_type == 'EXPENSE' and variance < 0:
                is_favorable = True
            
            variance_data.append({
                'name': budget.name,
                'department': budget.department or '-',
                'budget_type': budget.budget_type,
                'budget_amount': float(budget_amount),
                'actual_amount': float(actual),
                'variance': float(variance),
                'variance_percentage': round(variance_percent, 2),
                'status': 'favorable' if is_favorable else 'unfavorable'
            })
            
            total_budget += budget_amount
            total_actual += actual
        
        if format_type == 'csv':
            return export_variance_csv(variance_data, year, month, budget_type)
        elif format_type == 'pdf':
            return export_variance_pdf(variance_data, year, month, budget_type)
        else:
            return jsonify({'error': 'Unsupported format'}), 400
            
    except Exception as e:
        logger.error(f"Error exporting budget variance: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def export_variance_csv(variance_data, year, month, budget_type):
    """Export variance data as CSV"""
    import csv
    import io
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['Budget Variance Report'])
    writer.writerow([f'Fiscal Year: {year}'])
    writer.writerow([f'Month: {month if month else "Full Year"}'])
    writer.writerow([f'Budget Type: {budget_type.upper()}'])
    writer.writerow([])
    
    # Column headers
    writer.writerow([
        'Budget Name', 'Department', 'Type', 
        'Budget Amount', 'Actual Amount', 'Variance', 'Variance %', 'Status'
    ])
    
    # Data rows
    for item in variance_data:
        writer.writerow([
            item['name'],
            item['department'],
            item['budget_type'],
            f"{item['budget_amount']:.2f}",
            f"{item['actual_amount']:.2f}",
            f"{item['variance']:+.2f}",
            f"{item['variance_percentage']:+.2f}%",
            item['status'].upper()
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=budget_variance_{year}_{month if month else "full"}.csv'
    
    return response


def export_variance_pdf(variance_data, year, month, budget_type):
    """Export variance data as PDF"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from io import BytesIO
    from datetime import datetime
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72,
    )
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Title style
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        alignment=TA_CENTER,
        spaceAfter=12,
        textColor=colors.HexColor('#1FB256')
    )
    
    # Add title
    elements.append(Paragraph('Budget Variance Report', title_style))
    elements.append(Spacer(1, 6))
    
    # Add info
    info_style = ParagraphStyle(
        'Info',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_CENTER
    )
    elements.append(Paragraph(f'Fiscal Year: {year}', info_style))
    elements.append(Paragraph(f'Month: {month if month else "Full Year"}', info_style))
    elements.append(Paragraph(f'Budget Type: {budget_type.upper()}', info_style))
    elements.append(Spacer(1, 20))
    
    # Create table data
    table_data = [['Budget Name', 'Department', 'Type', 'Budget', 'Actual', 'Variance', '%', 'Status']]
    
    for item in variance_data:
        table_data.append([
            item['name'],
            item['department'],
            item['budget_type'],
            f"{item['budget_amount']:,.2f}",
            f"{item['actual_amount']:,.2f}",
            f"{item['variance']:+,.2f}",
            f"{item['variance_percentage']:+.2f}%",
            item['status'].upper()
        ])
    
    # Create table
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1FB256')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
    ]))
    
    elements.append(table)
    elements.append(Spacer(1, 20))
    
    # Add footer
    footer_text = f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    elements.append(Paragraph(footer_text, styles['Normal']))
    
    doc.build(elements)
    
    pdf = buffer.getvalue()
    buffer.close()
    
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=budget_variance_{year}_{month if month else "full"}.pdf'
    
    return response