# app/routes/dashboard_routes.py

from flask import Blueprint, request, jsonify, g
from datetime import datetime, timedelta
import logging
from sqlalchemy import func, and_, desc

from app.models import User, Account, Transaction, Member, AuditLog
from app.extensions import db
from app.routes.auth_routes import token_required

logger = logging.getLogger(__name__)
dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_dashboard_stats():
    """Get main dashboard statistics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        # Today's date range
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        # Month to date
        month_start = today.replace(day=1)
        month_start_dt = datetime.combine(month_start, datetime.min.time())
        
        # Year to date
        year_start = today.replace(month=1, day=1)
        year_start_dt = datetime.combine(year_start, datetime.min.time())
        
        # Today's income and expenses
        today_income = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.transaction_date >= today_start,
            Transaction.transaction_date <= today_end,
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        today_expenses = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'EXPENSE',
            Transaction.transaction_date >= today_start,
            Transaction.transaction_date <= today_end,
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        # Month's income and expenses
        month_income = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.transaction_date >= month_start_dt,
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        month_expenses = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'EXPENSE',
            Transaction.transaction_date >= month_start_dt,
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        # Year to date
        ytd_income = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.transaction_date >= year_start_dt,
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        ytd_expenses = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'EXPENSE',
            Transaction.transaction_date >= year_start_dt,
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        # Account balances
        total_assets = db.session.query(func.sum(Account.current_balance)).filter(
            Account.church_id == church_id,
            Account.account_type == 'ASSET',
            Account.is_active == True
        ).scalar() or 0
        
        total_liabilities = db.session.query(func.sum(Account.current_balance)).filter(
            Account.church_id == church_id,
            Account.account_type == 'LIABILITY',
            Account.is_active == True
        ).scalar() or 0
        
        net_balance = total_assets - total_liabilities
        
        # Counts - Check if Member model has is_active field
        member_count = 0
        try:
            # Try with is_active first
            if hasattr(Member, 'is_active'):
                member_count = Member.query.filter_by(
                    church_id=church_id,
                    is_active=True
                ).count()
            else:
                # If no is_active field, just count all members
                member_count = Member.query.filter_by(
                    church_id=church_id
                ).count()
        except Exception as e:
            logger.warning(f"Error counting members: {str(e)}")
            # Fallback to counting all members
            member_count = Member.query.filter_by(
                church_id=church_id
            ).count()
        
        pending_count = Transaction.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).count()
        
        account_count = Account.query.filter_by(
            church_id=church_id,
            is_active=True
        ).count()
        
        return jsonify({
            'today': {
                'income': float(today_income),
                'expenses': float(today_expenses),
                'net': float(today_income - today_expenses)
            },
            'month': {
                'income': float(month_income),
                'expenses': float(month_expenses),
                'net': float(month_income - month_expenses)
            },
            'ytd': {
                'income': float(ytd_income),
                'expenses': float(ytd_expenses),
                'net': float(ytd_income - ytd_expenses)
            },
            'balances': {
                'assets': float(total_assets),
                'liabilities': float(total_liabilities),
                'net': float(net_balance)
            },
            'counts': {
                'pending': pending_count,
                'members': member_count,
                'accounts': account_count
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {str(e)}")
        return jsonify({'error': 'Failed to get dashboard stats'}), 500


@dashboard_bp.route('/recent-transactions', methods=['GET', 'OPTIONS'])
@token_required
def get_recent_transactions():
    """Get recent transactions for dashboard"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        limit = request.args.get('limit', 10, type=int)
        
        # Get recent transactions (both income and expense)
        transactions = Transaction.query.filter_by(
            church_id=church_id
        ).order_by(
            Transaction.transaction_date.desc()
        ).limit(limit).all()
        
        result = []
        for t in transactions:
            result.append({
                'id': t.id,
                'date': t.transaction_date.isoformat(),
                'description': t.description or 'No description',
                'category': t.category or 'Uncategorized',
                'amount': float(t.amount),
                'type': t.transaction_type.lower(),
                'status': t.status.lower()
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error getting recent transactions: {str(e)}")
        return jsonify({'error': 'Failed to get recent transactions'}), 500


@dashboard_bp.route('/income-vs-expenses', methods=['GET', 'OPTIONS'])
@token_required
def get_income_vs_expenses():
    """Get income vs expenses comparison for chart"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        months = request.args.get('months', 6, type=int)
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30 * months)
        
        # Get monthly aggregates
        results = db.session.query(
            func.strftime('%Y-%m', Transaction.transaction_date).label('month'),
            func.sum(Transaction.amount).filter(Transaction.transaction_type == 'INCOME').label('income'),
            func.sum(Transaction.amount).filter(Transaction.transaction_type == 'EXPENSE').label('expenses')
        ).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED'
        ).group_by('month').order_by('month').all()
        
        comparison = []
        for r in results:
            # Format month for display
            year_month = r.month.split('-')
            month_name = datetime(int(year_month[0]), int(year_month[1]), 1).strftime('%b')
            
            comparison.append({
                'month': month_name,
                'income': float(r.income or 0),
                'expenses': float(r.expenses or 0)
            })
        
        return jsonify(comparison), 200
        
    except Exception as e:
        logger.error(f"Error getting income vs expenses: {str(e)}")
        return jsonify({'error': 'Failed to get comparison data'}), 500


@dashboard_bp.route('/alerts', methods=['GET', 'OPTIONS'])
@token_required
def get_dashboard_alerts():
    """Get dashboard alerts and notifications"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        alerts = []
        alert_id = 1
        
        # Check pending approvals
        pending_count = Transaction.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).count()
        
        if pending_count > 0:
            alerts.append({
                'id': alert_id,
                'title': 'Pending Approvals',
                'message': f'{pending_count} transaction(s) awaiting your approval',
                'severity': 'medium',
                'type': 'warning',
                'link': '/treasurer/expenses?status=pending'
            })
            alert_id += 1
        
        # Check unreconciled transactions
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        unreconciled = Transaction.query.filter(
            Transaction.church_id == church_id,
            Transaction.reconciliation_date == None,
            Transaction.transaction_date <= thirty_days_ago
        ).count()
        
        if unreconciled > 0:
            alerts.append({
                'id': alert_id,
                'title': 'Unreconciled Transactions',
                'message': f'{unreconciled} transactions older than 30 days need reconciliation',
                'severity': 'high',
                'type': 'error',
                'link': '/accounting/reconciliation'
            })
            alert_id += 1
        
        # Check low balances
        low_balance = Account.query.filter(
            Account.church_id == church_id,
            Account.current_balance < 1000,
            Account.is_active == True,
            Account.account_type.in_(['ASSET', 'EXPENSE'])
        ).count()
        
        if low_balance > 0:
            alerts.append({
                'id': alert_id,
                'title': 'Low Balances',
                'message': f'{low_balance} accounts have low balance (below 1000)',
                'severity': 'low',
                'type': 'info',
                'link': '/accounting/accounts'
            })
        
        return jsonify(alerts), 200
        
    except Exception as e:
        logger.error(f"Error getting dashboard alerts: {str(e)}")
        return jsonify([]), 200  # Return empty array on error


@dashboard_bp.route('/cash-flow', methods=['GET', 'OPTIONS'])
@token_required
def get_cash_flow():
    """Get cash flow summary"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        months = request.args.get('months', 3, type=int)
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30 * months)
        
        # Get cash accounts
        cash_accounts = Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'ASSET',
            Account.name.ilike('%cash%') | Account.name.ilike('%bank%'),
            Account.is_active == True
        ).all()
        
        # Get opening balance
        opening_balance = sum(float(acc.opening_balance) for acc in cash_accounts)
        
        # Get monthly cash flow
        results = db.session.query(
            func.strftime('%Y-%m', Transaction.transaction_date).label('month'),
            func.sum(Transaction.amount).filter(Transaction.transaction_type == 'INCOME').label('inflow'),
            func.sum(Transaction.amount).filter(Transaction.transaction_type == 'EXPENSE').label('outflow')
        ).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED'
        ).group_by('month').order_by('month').all()
        
        monthly_flow = []
        running_balance = opening_balance
        
        for r in results:
            inflow = float(r.inflow or 0)
            outflow = float(r.outflow or 0)
            net = inflow - outflow
            running_balance += net
            
            year_month = r.month.split('-')
            month_name = datetime(int(year_month[0]), int(year_month[1]), 1).strftime('%b %Y')
            
            monthly_flow.append({
                'month': month_name,
                'inflow': inflow,
                'outflow': outflow,
                'net': net,
                'balance': running_balance
            })
        
        return jsonify({
            'monthly': monthly_flow,
            'currentBalance': running_balance,
            'openingBalance': opening_balance
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting cash flow: {str(e)}")
        return jsonify({'error': 'Failed to get cash flow'}), 500