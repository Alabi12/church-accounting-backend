# app/routes/treasurer_routes.py
from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import Budget, Transaction, Account, User, AuditLog, Church
from app.extensions import db
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_, desc, extract
import traceback
import logging

# Import socketio if you use it
try:
    from app import socketio
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False
    print("⚠️ SocketIO not available")

logger = logging.getLogger(__name__)
treasurer_bp = Blueprint('treasurer', __name__)

# Import token_required from auth_routes
from app.routes.auth_routes import token_required


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
        
        # Calculate monthly growth
        last_month_start = (first_day - timedelta(days=1)).replace(day=1)
        last_month_end = first_day - timedelta(days=1)
        
        this_month_income = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.status == 'POSTED',
            Transaction.transaction_date >= first_day
        ).scalar() or 0
        
        last_month_income = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.status == 'POSTED',
            Transaction.transaction_date >= last_month_start,
            Transaction.transaction_date <= last_month_end
        ).scalar() or 0
        
        monthly_growth = 0
        if last_month_income > 0:
            monthly_growth = ((this_month_income - last_month_income) / last_month_income) * 100
        
        # Calculate budget utilization
        total_budget = db.session.query(func.sum(Budget.amount)).filter(
            Budget.church_id == church_id,
            Budget.status == 'APPROVED'
        ).scalar() or 0
        
        # Note: Use actual_amount if available, otherwise use amount
        total_approved = db.session.query(func.sum(Budget.amount)).filter(
            Budget.church_id == church_id,
            Budget.status == 'APPROVED'
        ).scalar() or 0
        
        budget_utilization = 0
        if total_budget > 0:
            budget_utilization = (total_approved / total_budget) * 100
        
        return jsonify({
            'totalIncome': float(total_income),
            'totalExpenses': float(total_expenses),
            'netBalance': float(net_balance),
            'pendingApprovals': pending_approvals,
            'pendingTransactions': pending_transactions,
            'accountBalance': float(account_balance),
            'monthlyGrowth': round(monthly_growth, 1),
            'budgetUtilization': round(budget_utilization, 1)
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
        
        # Create new budget - include all required fields
        budget = Budget(
            church_id=church_id,
            name=data.get('name'),
            description=data.get('description', ''),
            department=data.get('department'),
            fiscal_year=data.get('fiscal_year', datetime.now().year),
            period='annual',  # Set default period
            amount=data.get('amount', 0),
            priority=data.get('priority', 'MEDIUM'),
            budget_type=data.get('budget_type', 'EXPENSE'),
            justification=data.get('justification', ''),
            status='DRAFT',
            created_by=current_user.id if current_user else None,
            # Initialize monthly amounts to 0
            january=0, february=0, march=0, april=0, may=0, june=0,
            july=0, august=0, september=0, october=0, november=0, december=0,
            # Initialize variance fields
            actual_amount=0, variance=0, variance_percentage=0
        )
        
        # Add optional dates if provided
        if data.get('start_date'):
            budget.start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00')).date()
        if data.get('end_date'):
            budget.end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00')).date()
        
        db.session.add(budget)
        db.session.commit()
        
        print(f"✅ Budget created with ID: {budget.id}")
        
        # Log audit
        if current_user:
            audit_log = AuditLog(
                user_id=current_user.id,
                action='CREATE_BUDGET',
                resource='budget',
                resource_id=budget.id,
                data={'name': budget.name, 'amount': float(budget.amount)},
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string if request.user_agent else None
            )
            db.session.add(audit_log)
            db.session.commit()
        
        return jsonify({
            'message': 'Budget created successfully',
            'budget': budget.to_dict() if hasattr(budget, 'to_dict') else {'id': budget.id, 'name': budget.name}
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
        
        min_amount = request.args.get('minAmount', type=float)
        if min_amount:
            query = query.filter(Budget.amount >= min_amount)
        
        max_amount = request.args.get('maxAmount', type=float)
        if max_amount:
            query = query.filter(Budget.amount <= max_amount)
        
        # Get paginated results
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        paginated = query.order_by(
            Budget.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        # Format budgets
        budget_list = []
        for budget in paginated.items:
            submitter = User.query.get(budget.created_by)
            
            budget_dict = {
                'id': budget.id,
                'name': budget.name,
                'description': budget.description,
                'department': budget.department,
                'fiscal_year': budget.fiscal_year,
                'amount': float(budget.amount),
                'priority': budget.priority,
                'budget_type': budget.budget_type,
                'justification': budget.justification,
                'status': budget.status,
                'start_date': budget.start_date.isoformat() if budget.start_date else None,
                'end_date': budget.end_date.isoformat() if budget.end_date else None,
                'created_by': budget.created_by,
                'created_at': budget.created_at.isoformat() if budget.created_at else None,
                'submitted_by': budget.submitted_by,
                'submitted_at': budget.submitted_at.isoformat() if budget.submitted_at else None,
                'approved_by': budget.approved_by,
                'approved_at': budget.approved_at.isoformat() if budget.approved_at else None
            }
            
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
        
        # Get submitter info
        submitter = User.query.get(budget.created_by)
        approver = User.query.get(budget.approved_by)
        rejecter = User.query.get(budget.rejected_by)
        
        budget_data = {
            'id': budget.id,
            'name': budget.name,
            'description': budget.description,
            'department': budget.department,
            'fiscal_year': budget.fiscal_year,
            'period': budget.period if hasattr(budget, 'period') else 'annual',
            'amount': float(budget.amount),
            'priority': budget.priority,
            'budget_type': budget.budget_type,
            'justification': budget.justification,
            'status': budget.status,
            'start_date': budget.start_date.isoformat() if budget.start_date else None,
            'end_date': budget.end_date.isoformat() if budget.end_date else None,
            'created_by': budget.created_by,
            'created_by_name': submitter.full_name if submitter else None,
            'created_at': budget.created_at.isoformat() if budget.created_at else None,
            'submitted_by': budget.submitted_by,
            'submitted_at': budget.submitted_at.isoformat() if budget.submitted_at else None,
            'approved_by': budget.approved_by,
            'approved_by_name': approver.full_name if approver else None,
            'approved_at': budget.approved_at.isoformat() if budget.approved_at else None,
            'rejected_by': budget.rejected_by,
            'rejected_by_name': rejecter.full_name if rejecter else None,
            'rejected_at': budget.rejected_at.isoformat() if budget.rejected_at else None,
            'rejection_reason': budget.rejection_reason,
            'updated_at': budget.updated_at.isoformat() if budget.updated_at else None
        }
        
        return jsonify(budget_data), 200
        
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
        if 'start_date' in data and data['start_date']:
            budget.start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00')).date()
        if 'end_date' in data and data['end_date']:
            budget.end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00')).date()
        
        # If submitting for approval, change status to PENDING
        if data.get('submit_for_approval', False):
            budget.status = 'PENDING'
            budget.submitted_by = current_user.id if current_user else None
            budget.submitted_at = datetime.utcnow()
        
        budget.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Budget updated successfully',
            'budget': {
                'id': budget.id,
                'name': budget.name,
                'status': budget.status
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@treasurer_bp.route('/budgets/<int:budget_id>/submit', methods=['POST', 'OPTIONS'])
@token_required
def submit_budget_for_approval(budget_id):
    """Submit a budget for approval (changes status from DRAFT to PENDING)"""
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
        
        # Update status to PENDING
        budget.status = 'PENDING'
        budget.submitted_by = current_user.id if current_user else None
        budget.submitted_at = datetime.utcnow()
        budget.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Budget submitted for approval successfully',
            'budget': {
                'id': budget.id,
                'status': budget.status,
                'submitted_at': budget.submitted_at.isoformat() if budget.submitted_at else None
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@treasurer_bp.route('/budgets/<int:budget_id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_budget_request(budget_id):
    """Approve a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = get_current_user()
        data = request.get_json() or {}
        
        budget = Budget.query.filter_by(
            id=budget_id,
            church_id=church_id
        ).first()
        
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        if budget.status != 'PENDING':
            return jsonify({'error': f'Budget is already {budget.status.lower()}'}), 400
        
        # Update budget
        budget.status = 'APPROVED'
        budget.approved_by = current_user.id if current_user else None
        budget.approved_at = datetime.utcnow()
        
        # Optional: set approved amount
        if data.get('amount'):
            budget.approved_amount = data['amount']
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=current_user.id if current_user else None,
            action='APPROVE_BUDGET',
            resource='budget',
            resource_id=budget_id,
            data={'amount': float(budget.amount)},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else None
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Budget approved successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to approve budget: {str(e)}'}), 500


@treasurer_bp.route('/budgets/<int:budget_id>/reject', methods=['POST', 'OPTIONS'])
@token_required
def reject_budget_request(budget_id):
    """Reject a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = get_current_user()
        data = request.get_json() or {}
        reason = data.get('reason', 'No reason provided')
        
        budget = Budget.query.filter_by(
            id=budget_id,
            church_id=church_id
        ).first()
        
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        if budget.status != 'PENDING':
            return jsonify({'error': f'Budget is already {budget.status.lower()}'}), 400
        
        budget.status = 'REJECTED'
        budget.rejected_by = current_user.id if current_user else None
        budget.rejected_at = datetime.utcnow()
        budget.rejection_reason = reason
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=current_user.id if current_user else None,
            action='REJECT_BUDGET',
            resource='budget',
            resource_id=budget_id,
            data={'reason': reason},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else None
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Budget rejected'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to reject budget: {str(e)}'}), 500


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
        
        # Get all budgets for the year
        query = Budget.query.filter_by(
            church_id=church_id,
            fiscal_year=year,
            status='APPROVED'
        )
        
        if budget_type != 'all':
            query = query.filter_by(budget_type=budget_type.upper())
        
        budgets = query.all()
        
        # Get actuals from journal entries
        from app.models import JournalEntry, JournalLine
        
        variance_data = []
        total_budget = 0
        total_actual = 0
        total_variance = 0
        
        for budget in budgets:
            # Get actual amounts from journal entries
            actual_query = db.session.query(func.sum(JournalLine.debit - JournalLine.credit)).join(
                JournalEntry
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.status == 'POSTED',
                extract('year', JournalEntry.entry_date) == year
            )
            
            if budget.account_id:
                actual_query = actual_query.filter(JournalLine.account_id == budget.account_id)
            elif budget.account_code:
                account = Account.query.filter_by(
                    account_code=budget.account_code,
                    church_id=church_id
                ).first()
                if account:
                    actual_query = actual_query.filter(JournalLine.account_id == account.id)
            
            actual = actual_query.scalar() or 0
            
            # Calculate variance
            variance = actual - budget.amount
            variance_percent = (variance / budget.amount * 100) if budget.amount > 0 else 0
            
            variance_data.append({
                'id': budget.id,
                'name': budget.name,
                'account_code': budget.account_code,
                'budget_type': budget.budget_type,
                'department': budget.department,
                'budget_amount': float(budget.amount),
                'actual_amount': float(actual),
                'variance': float(variance),
                'variance_percentage': round(variance_percent, 2),
                'status': 'favorable' if (budget.budget_type == 'REVENUE' and variance > 0) or (budget.budget_type == 'EXPENSE' and variance < 0) else 'unfavorable'
            })
            
            total_budget += budget.amount
            total_actual += actual
            total_variance += variance
        
        return jsonify({
            'variance_data': variance_data,
            'summary': {
                'total_budget': round(total_budget, 2),
                'total_actual': round(total_actual, 2),
                'total_variance': round(total_variance, 2),
                'variance_percentage': round((total_variance / total_budget * 100) if total_budget > 0 else 0, 2),
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


# ==================== ALERTS ====================

@treasurer_bp.route('/alerts', methods=['GET', 'OPTIONS'])
@token_required
def get_treasurer_alerts():
    """Get treasurer alerts"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        alerts = []
        alert_id = 1
        
        # Check for pending budgets
        pending_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).count()
        
        if pending_budgets > 0:
            alerts.append({
                'id': alert_id,
                'type': 'warning',
                'severity': 'medium',
                'message': f'{pending_budgets} budget(s) awaiting your review',
                'time': 'Now'
            })
            alert_id += 1
        
        # Check for pending transactions
        pending_transactions = Transaction.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).count()
        
        if pending_transactions > 0:
            alerts.append({
                'id': alert_id,
                'type': 'warning',
                'severity': 'medium',
                'message': f'{pending_transactions} transaction(s) awaiting approval',
                'time': 'Now'
            })
            alert_id += 1
        
        # Check for old pending transactions
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        old_pending = Transaction.query.filter(
            Transaction.church_id == church_id,
            Transaction.status == 'PENDING',
            Transaction.transaction_date <= thirty_days_ago
        ).count()
        
        if old_pending > 0:
            alerts.append({
                'id': alert_id,
                'type': 'critical',
                'severity': 'high',
                'message': f'{old_pending} transaction(s) pending for over 30 days',
                'time': f'{thirty_days_ago.strftime("%b %d")}'
            })
            alert_id += 1
        
        # Check for low balance accounts
        low_balance_accounts = Account.query.filter(
            Account.church_id == church_id,
            Account.current_balance < 1000,
            Account.is_active == True
        ).count()
        
        if low_balance_accounts > 0:
            alerts.append({
                'id': alert_id,
                'type': 'info',
                'severity': 'low',
                'message': f'{low_balance_accounts} accounts have low balance',
                'time': 'Today'
            })
            alert_id += 1
        
        # Budget utilization alert
        total_budget = db.session.query(func.sum(Budget.amount)).filter(
            Budget.church_id == church_id,
            Budget.status == 'APPROVED'
        ).scalar() or 0
        
        total_spent = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'EXPENSE',
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        if total_budget > 0:
            utilization = (total_spent / total_budget) * 100
            if utilization > 85:
                alerts.append({
                    'id': alert_id,
                    'type': 'warning',
                    'severity': 'medium',
                    'message': f'Budget utilization at {utilization:.1f}% - approaching limit',
                    'time': 'Now'
                })
                alert_id += 1
        
        return jsonify({'alerts': alerts}), 200
        
    except Exception as e:
        logger.error(f"Error getting alerts: {str(e)}")
        traceback.print_exc()
        return jsonify({'alerts': [], 'error': str(e)}), 200


# ==================== PENDING ITEMS ====================

@treasurer_bp.route('/pending-items', methods=['GET', 'OPTIONS'])
@token_required
def get_pending_items():
    """Get all pending items requiring treasurer approval"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        pending_items = []
        
        # Get pending budgets
        pending_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).order_by(Budget.created_at.desc()).limit(5).all()
        
        for budget in pending_budgets:
            submitter = User.query.get(budget.created_by)
            pending_items.append({
                'id': budget.id,
                'type': 'budget',
                'title': budget.name,
                'description': budget.description,
                'amount': float(budget.amount),
                'submittedBy': submitter.full_name if submitter else 'Unknown',
                'date': budget.created_at.isoformat() if budget.created_at else None,
                'department': budget.department
            })
        
        # Get pending expense transactions
        pending_expenses = Transaction.query.filter_by(
            church_id=church_id,
            transaction_type='EXPENSE',
            status='PENDING'
        ).order_by(Transaction.transaction_date.desc()).limit(5).all()
        
        for expense in pending_expenses:
            creator = User.query.get(expense.created_by)
            account = Account.query.get(expense.account_id)
            pending_items.append({
                'id': expense.id,
                'type': 'expense',
                'title': expense.description,
                'description': expense.description,
                'amount': float(expense.amount),
                'submittedBy': creator.full_name if creator else 'Unknown',
                'date': expense.transaction_date.isoformat(),
                'account': account.name if account else 'Unknown',
                'category': expense.category
            })
        
        # Sort by date (most recent first)
        pending_items.sort(key=lambda x: x.get('date', ''), reverse=True)
        
        return jsonify({'items': pending_items[:10]}), 200
        
    except Exception as e:
        logger.error(f"Error getting pending items: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== DEBUG ENDPOINT ====================

@treasurer_bp.route('/debug', methods=['GET', 'OPTIONS'])
@token_required
def debug_treasurer():
    """Debug endpoint to check model accessibility"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        debug_info = {
            'user': {
                'id': g.current_user.id,
                'church_id': church_id,
                'role': g.current_user.role
            },
            'models': {}
        }
        
        # Check Budget model
        try:
            budget_count = Budget.query.filter_by(church_id=church_id).count()
            debug_info['models']['budget'] = {
                'accessible': True,
                'count': budget_count,
                'error': None
            }
        except Exception as e:
            debug_info['models']['budget'] = {
                'accessible': False,
                'error': str(e)
            }
        
        # Check Transaction model
        try:
            transaction_count = Transaction.query.filter_by(church_id=church_id).count()
            debug_info['models']['transaction'] = {
                'accessible': True,
                'count': transaction_count,
                'error': None
            }
        except Exception as e:
            debug_info['models']['transaction'] = {
                'accessible': False,
                'error': str(e)
            }
        
        # Check Account model
        try:
            account_count = Account.query.filter_by(church_id=church_id).count()
            debug_info['models']['account'] = {
                'accessible': True,
                'count': account_count,
                'error': None
            }
        except Exception as e:
            debug_info['models']['account'] = {
                'accessible': False,
                'error': str(e)
            }
        
        return jsonify(debug_info), 200
        
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500