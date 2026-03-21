from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import Budget, Transaction, Account, User, AuditLog, BudgetComment
from app.extensions import db
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_, desc
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

# ==================== DASHBOARD STATS ====================

@treasurer_bp.route('/dashboard-stats', methods=['GET', 'OPTIONS'])
@token_required
def get_dashboard_stats():
    """Get treasurer dashboard statistics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
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
            Account.account_type == 'asset',
            Account.is_active == True
        ).scalar() or 0
        
        liabilities = db.session.query(func.sum(Account.current_balance)).filter(
            Account.church_id == church_id,
            Account.account_type == 'liability',
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
        
        total_approved = db.session.query(func.sum(Budget.approved_amount)).filter(
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


# ==================== RECENT TRANSACTIONS ====================

@treasurer_bp.route('/recent-transactions', methods=['GET', 'OPTIONS'])
@token_required
def get_recent_transactions():
    """Get recent transactions for treasurer dashboard"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        limit = request.args.get('limit', 10, type=int)
        
        transactions = Transaction.query.filter_by(
            church_id=church_id
        ).order_by(
            Transaction.transaction_date.desc()
        ).limit(limit).all()
        
        transaction_list = []
        for t in transactions:
            account = Account.query.get(t.account_id)
            transaction_list.append({
                'id': t.id,
                'date': t.transaction_date.isoformat(),
                'description': t.description,
                'account': account.name if account else 'Unknown',
                'amount': float(t.amount),
                'type': t.transaction_type.lower(),
                'status': t.status.lower(),
                'reference': t.reference_number
            })
        
        return jsonify({'transactions': transaction_list}), 200
        
    except Exception as e:
        logger.error(f"Error getting recent transactions: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get recent transactions: {str(e)}'}), 500


# ==================== PENDING ITEMS ====================

@treasurer_bp.route('/pending-items', methods=['GET', 'OPTIONS'])
@token_required
def get_pending_items():
    """Get all pending items requiring treasurer approval"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        pending_items = []
        
        # Get pending budgets
        pending_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).order_by(Budget.submitted_date.desc()).limit(5).all()
        
        for budget in pending_budgets:
            submitter = User.query.get(budget.submitted_by)
            pending_items.append({
                'id': budget.id,
                'type': 'budget',
                'title': budget.name,
                'description': budget.description,
                'amount': float(budget.amount),
                'submittedBy': submitter.full_name if submitter else 'Unknown',
                'date': budget.submitted_date.isoformat() if budget.submitted_date else None,
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
        return jsonify({'error': f'Failed to get pending items: {str(e)}'}), 500


# ==================== BUDGET ENDPOINTS ====================

@treasurer_bp.route('/budgets', methods=['POST', 'OPTIONS'])
@token_required
def create_budget():
    """Create a new budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'department', 'fiscal_year', 'amount']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Create new budget
        budget = Budget(
            church_id=g.current_user.church_id,
            name=data['name'],
            description=data.get('description', ''),
            department=data['department'],
            fiscal_year=data['fiscal_year'],
            amount=data['amount'],
            start_date=datetime.fromisoformat(data['start_date']) if data.get('start_date') else None,
            end_date=datetime.fromisoformat(data['end_date']) if data.get('end_date') else None,
            priority=data.get('priority', 'MEDIUM'),
            justification=data.get('justification', ''),
            status='DRAFT',  # Start as DRAFT, then submit for approval
            submitted_by=g.current_user.id,
            submitted_date=datetime.utcnow(),
            created_at=datetime.utcnow()
        )
        
        db.session.add(budget)
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='CREATE_BUDGET',
            resource='budget',
            resource_id=budget.id,
            data={'name': budget.name, 'amount': float(budget.amount)},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Budget created successfully',
            'budget': {
                'id': budget.id,
                'name': budget.name,
                'status': budget.status
            }
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
        church_id = g.current_user.church_id
        
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
            Budget.submitted_date.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        # Format budgets
        budget_list = []
        for budget in paginated.items:
            submitter = User.query.get(budget.submitted_by)
            
            budget_list.append({
                'id': budget.id,
                'name': budget.name,
                'department': budget.department,
                'fiscalYear': budget.fiscal_year,
                'amount': float(budget.amount),
                'approvedAmount': float(budget.approved_amount) if budget.approved_amount else None,
                'previousAmount': float(budget.previous_amount) if budget.previous_amount else 0,
                'startDate': budget.start_date.isoformat() if budget.start_date else None,
                'endDate': budget.end_date.isoformat() if budget.end_date else None,
                'submittedBy': submitter.full_name if submitter else 'Unknown',
                'submittedDate': budget.submitted_date.isoformat() if budget.submitted_date else None,
                'status': budget.status,
                'priority': budget.priority,
                'description': budget.description,
                'justification': budget.justification,
                # 'commentCount': budget.comment_count  # Comment out if not exists
            })
        
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
def get_budget_by_id(budget_id):
    """Get a specific budget by ID"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        print(f"\n{'='*60}")
        print(f"📡 GET /treasurer/budgets/{budget_id} called")
        print(f"{'='*60}")
        
        # Log user info
        print(f"👤 Current user ID: {g.current_user.id}")
        print(f"👤 Current user church: {g.current_user.church_id}")
        
        # Try to query the budget
        print(f"🔍 Attempting to fetch budget with ID: {budget_id}")
        budget = Budget.query.get(budget_id)
        
        if not budget:
            print(f"❌ Budget {budget_id} not found in database")
            return jsonify({'error': 'Budget not found'}), 404
        
        print(f"✅ Budget found: {budget.name}")
        print(f"📊 Budget status: {budget.status}")
        print(f"📊 Budget church_id: {budget.church_id}")
        
        # Check if user has access to this budget
        if budget.church_id != g.current_user.church_id:
            print(f"❌ Access denied: Budget church_id {budget.church_id} != User church_id {g.current_user.church_id}")
            return jsonify({'error': 'Access denied'}), 403
        
        # Get submitter info
        submitter = None
        if budget.submitted_by:
            submitter = User.query.get(budget.submitted_by)
            print(f"👤 Submitter found: {submitter.full_name if submitter else 'None'}")
        
        # Get approver/rejecter info
        approver = None
        if budget.approved_by:
            approver = User.query.get(budget.approved_by)
            print(f"👤 Approver found: {approver.full_name if approver else 'None'}")
        
        rejecter = None
        if budget.rejected_by:
            rejecter = User.query.get(budget.rejected_by)
            print(f"👤 Rejecter found: {rejecter.full_name if rejecter else 'None'}")
        
        # Format the response
        print("🔧 Formatting response...")
        budget_data = {
            'id': budget.id,
            'name': budget.name,
            'description': budget.description,
            'department': budget.department,
            'fiscalYear': budget.fiscal_year,
            'amount': float(budget.amount) if budget.amount else 0,
            'approvedAmount': float(budget.approved_amount) if budget.approved_amount else None,
            'previousAmount': float(budget.previous_amount) if budget.previous_amount else 0,
            'startDate': budget.start_date.isoformat() if budget.start_date else None,
            'endDate': budget.end_date.isoformat() if budget.end_date else None,
            'status': budget.status,
            'priority': budget.priority,
            'justification': budget.justification,
            'submittedBy': submitter.full_name if submitter else None,
            'submittedById': budget.submitted_by,
            'submittedDate': budget.submitted_date.isoformat() if budget.submitted_date else None,
            'approvedBy': approver.full_name if approver else None,
            'approvedById': budget.approved_by,
            'approvedDate': budget.approved_date.isoformat() if budget.approved_date else None,
            'rejectedBy': rejecter.full_name if rejecter else None,
            'rejectedById': budget.rejected_by,
            'rejectedDate': budget.rejected_date.isoformat() if budget.rejected_date else None,
            'rejectionReason': budget.rejection_reason,
            'createdAt': budget.created_at.isoformat() if budget.created_at else None,
            'updatedAt': budget.updated_at.isoformat() if budget.updated_at else None
        }
        
        print(f"✅ Response formatted successfully")
        print(f"📦 Returning budget data for: {budget_data['name']}")
        return jsonify(budget_data), 200
        
    except AttributeError as ae:
        print(f"❌ AttributeError: {str(ae)}")
        print(f"❌ This usually means a model field doesn't exist")
        traceback.print_exc()
        return jsonify({'error': f'Database model error: {str(ae)}'}), 500
        
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        print(f"❌ Error type: {type(e).__name__}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get budget: {str(e)}'}), 500
      


@treasurer_bp.route('/budgets/<int:budget_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_budget(budget_id):
    """Update a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Find the budget
        budget = Budget.query.get(budget_id)
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        # Check church access
        if budget.church_id != g.current_user.church_id:
            return jsonify({'error': 'Access denied'}), 403
        
        data = request.get_json()
        
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
        if 'start_date' in data:
            budget.start_date = datetime.fromisoformat(data['start_date']) if data['start_date'] else None
        if 'end_date' in data:
            budget.end_date = datetime.fromisoformat(data['end_date']) if data['end_date'] else None
        if 'priority' in data:
            budget.priority = data['priority']
        if 'justification' in data:
            budget.justification = data['justification']
        
        # If submitting for approval, change status to PENDING
        if data.get('submit_for_approval', False):
            budget.status = 'PENDING'
            budget.submitted_date = datetime.utcnow()
        
        budget.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Budget updated successfully',
            'budget': budget.to_dict() if hasattr(budget, 'to_dict') else {'id': budget.id, 'status': budget.status}
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error updating budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    

@treasurer_bp.route('/budgets/<int:budget_id>/submit', methods=['POST', 'OPTIONS'])
@token_required
def submit_budget_for_approval(budget_id):
    """Submit a budget for approval (changes status from DRAFT to PENDING)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        budget = Budget.query.get(budget_id)
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        if budget.church_id != g.current_user.church_id:
            return jsonify({'error': 'Access denied'}), 403
        
        if budget.status != 'DRAFT':
            return jsonify({'error': f'Budget is already {budget.status.lower()}'}), 400
        
        # Update status to PENDING
        budget.status = 'PENDING'
        budget.submitted_date = datetime.utcnow()
        budget.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Budget submitted for approval successfully',
            'budget': {
                'id': budget.id,
                'status': budget.status,
                'submitted_date': budget.submitted_date.isoformat() if budget.submitted_date else None
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error submitting budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    

@treasurer_bp.route('/budgets/<int:budget_id>/comments', methods=['GET', 'OPTIONS'])
@token_required
def get_budget_comments(budget_id):
    """Get comments for a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        print(f"📡 Fetching comments for budget {budget_id}")
        
        # Check if BudgetComment model exists
        try:
            from app.models import BudgetComment
        except ImportError:
            return jsonify({'error': 'BudgetComment model not found'}), 500
        
        # Direct query for comments
        comments = BudgetComment.query.filter_by(budget_id=budget_id).order_by(BudgetComment.created_at.desc()).all()
        
        result = []
        for comment in comments:
            # Get user info
            user = User.query.get(comment.user_id)
            result.append({
                'id': comment.id,
                'user': user.full_name if user else 'Unknown',
                'user_id': comment.user_id,
                'text': comment.comment,
                'date': comment.created_at.isoformat() if comment.created_at else None
            })
        
        print(f"✅ Found {len(result)} comments")
        return jsonify({'comments': result}), 200
        
    except Exception as e:
        print(f"❌ Error getting budget comments: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get comments: {str(e)}'}), 500


@treasurer_bp.route('/budgets/<int:budget_id>/comments', methods=['POST', 'OPTIONS'])
@token_required
def add_budget_comment(budget_id):
    """Add a comment to a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        if not data or 'comment' not in data:
            return jsonify({'error': 'Comment text is required'}), 400
        
        comment_text = data['comment']
        
        budget = Budget.query.get(budget_id)
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        # Check if BudgetComment model exists
        try:
            from app.models import BudgetComment
        except ImportError:
            return jsonify({'error': 'BudgetComment model not found'}), 500
        
        # Create comment
        comment = BudgetComment(
            budget_id=budget_id,
            user_id=g.current_user.id,
            comment=comment_text
        )
        
        db.session.add(comment)
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='ADD_BUDGET_COMMENT',
            resource='budget',
            resource_id=budget_id,
            data={'comment': comment_text[:100]},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Comment added successfully',
            'comment': {
                'id': comment.id,
                'user': g.current_user.full_name,
                'user_id': g.current_user.id,
                'text': comment.comment,
                'date': comment.created_at.isoformat() if comment.created_at else None
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error adding comment: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to add comment: {str(e)}'}), 500


@treasurer_bp.route('/budgets/<int:budget_id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_budget_request(budget_id):
    """Approve a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Only try to parse JSON if there's data, otherwise use empty dict
        data = {}
        if request.data and request.content_type == 'application/json':
            data = request.get_json() or {}
        
        # Optional fields that might be sent
        amount = data.get('amount')
        categories = data.get('categories', {})
        
        budget = Budget.query.get(budget_id)
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        if budget.status != 'PENDING':
            return jsonify({'error': f'Budget is already {budget.status.lower()}'}), 400
        
        # Update budget
        budget.status = 'APPROVED'
        budget.approved_by = g.current_user.id
        budget.approved_date = datetime.utcnow()
        
        if amount:
            budget.approved_amount = amount
        
        # Update categories if provided (and if categories exist)
        if categories and hasattr(budget, 'categories'):
            for idx, cat in enumerate(budget.categories):
                if str(idx) in categories:
                    cat.approved_amount = categories[str(idx)]
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='APPROVE_BUDGET',
            resource='budget',
            resource_id=budget_id,
            data={'amount': amount},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        # Emit socket event for real-time updates
        if SOCKETIO_AVAILABLE:
            try:
                socketio.emit('budget_updated', {
                    'budget_id': budget_id,
                    'status': 'APPROVED',
                    'action': 'approve',
                    'timestamp': datetime.utcnow().isoformat()
                })
            except Exception as e:
                print(f"⚠️ Socket emit failed: {e}")
        
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
        data = request.get_json() or {}
        reason = data.get('reason', 'No reason provided')
        
        budget = Budget.query.get(budget_id)
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        if budget.status != 'PENDING':
            return jsonify({'error': f'Budget is already {budget.status.lower()}'}), 400
        
        budget.status = 'REJECTED'
        budget.rejected_by = g.current_user.id
        budget.rejected_date = datetime.utcnow()
        budget.rejection_reason = reason
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='REJECT_BUDGET',
            resource='budget',
            resource_id=budget_id,
            data={'reason': reason},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        # Emit socket event for real-time updates
        if SOCKETIO_AVAILABLE:
            try:
                socketio.emit('budget_updated', {
                    'budget_id': budget_id,
                    'status': 'REJECTED',
                    'action': 'reject',
                    'reason': reason,
                    'timestamp': datetime.utcnow().isoformat()
                })
            except Exception as e:
                print(f"⚠️ Socket emit failed: {e}")
        
        return jsonify({'message': 'Budget rejected'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to reject budget: {str(e)}'}), 500


# ==================== EXPENSE MANAGEMENT ENDPOINTS ====================

@treasurer_bp.route('/expenses', methods=['GET', 'OPTIONS'])
@token_required
def get_expenses_list():
    """Get expenses with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        # Build query for expense transactions
        query = Transaction.query.filter_by(
            church_id=church_id,
            transaction_type='EXPENSE'
        )
        
        # Apply filters
        status = request.args.get('status')
        if status and status != 'all':
            query = query.filter_by(status=status.upper())
        
        category = request.args.get('category')
        if category and category != 'all':
            query = query.filter_by(category=category.upper())
        
        start_date = request.args.get('startDate')
        if start_date:
            query = query.filter(Transaction.transaction_date >= datetime.fromisoformat(start_date))
        
        end_date = request.args.get('endDate')
        if end_date:
            query = query.filter(Transaction.transaction_date <= datetime.fromisoformat(end_date))
        
        search = request.args.get('search')
        if search:
            query = query.filter(
                or_(
                    Transaction.description.ilike(f'%{search}%'),
                    Transaction.reference_number.ilike(f'%{search}%')
                )
            )
        
        # Get paginated results
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        paginated = query.order_by(
            Transaction.transaction_date.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        # Format expenses
        expense_list = []
        for t in paginated.items:
            account = Account.query.get(t.account_id)
            creator = User.query.get(t.created_by)
            
            expense_list.append({
                'id': t.id,
                'date': t.transaction_date.isoformat(),
                'category': t.category,
                'amount': float(t.amount),
                'description': t.description,
                'vendor': account.name if account else 'Unknown',
                'paymentMethod': t.payment_method.lower() if t.payment_method else 'cash',
                'status': t.status.lower(),
                'reference': t.reference_number,
                'submittedBy': creator.full_name if creator else 'Unknown',
                'approvedBy': User.query.get(t.approved_by).full_name if t.approved_by else None,
                'approvedDate': t.approved_date.isoformat() if t.approved_date else None,
                'rejectedBy': User.query.get(t.rejected_by).full_name if t.rejected_by else None,
                'rejectedDate': t.rejected_date.isoformat() if t.rejected_date else None,
                'rejectionReason': t.rejection_reason
            })
        
        # Calculate stats
        all_expenses = Transaction.query.filter_by(
            church_id=church_id,
            transaction_type='EXPENSE'
        ).all()
        
        stats = {
            'total': len(all_expenses),
            'pending': len([e for e in all_expenses if e.status == 'PENDING']),
            'approved': len([e for e in all_expenses if e.status == 'POSTED']),
            'rejected': len([e for e in all_expenses if e.status == 'REJECTED']),
            'totalAmount': sum(float(e.amount) for e in all_expenses)
        }
        
        return jsonify({
            'expenses': expense_list,
            'stats': stats,
            'total': paginated.total,
            'pages': paginated.pages,
            'currentPage': paginated.page
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting expenses: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get expenses: {str(e)}'}), 500


@treasurer_bp.route('/expenses', methods=['POST', 'OPTIONS'])
@token_required
def create_new_expense():
    """Create a new expense"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['date', 'category', 'amount', 'description', 'vendor']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        # Find or create account for this vendor/category
        account = Account.query.filter_by(
            church_id=g.current_user.church_id,
            name=data['vendor'],
            type='expense'
        ).first()
        
        if not account:
            # Create a new expense account
            account = Account(
                church_id=g.current_user.church_id,
                account_code=f"EXP{len(Account.query.all()) + 1:04d}",
                name=data['vendor'],
                type='expense',
                category=data['category'].upper(),
                description=f"Expense account for {data['vendor']}",
                opening_balance=0,
                current_balance=0,
                is_active=True
            )
            db.session.add(account)
            db.session.flush()
        
        # Generate transaction number
        date_str = datetime.utcnow().strftime('%Y%m%d')
        last_txn = Transaction.query.filter(
            Transaction.transaction_number.like(f'EXP{date_str}%')
        ).order_by(Transaction.id.desc()).first()
        
        if last_txn:
            last_num = int(last_txn.transaction_number[-4:])
            new_num = last_num + 1
        else:
            new_num = 1
        
        transaction_number = f"EXP{date_str}{new_num:04d}"
        
        # Create expense transaction
        transaction = Transaction(
            church_id=g.current_user.church_id,
            transaction_number=transaction_number,
            transaction_date=datetime.fromisoformat(data['date']),
            transaction_type='EXPENSE',
            category=data['category'].upper(),
            amount=float(data['amount']),
            account_id=account.id,
            description=data['description'],
            payment_method=data.get('paymentMethod', 'cash').upper(),
            reference_number=data.get('reference'),
            status='PENDING',
            created_by=g.current_user.id
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='CREATE_EXPENSE',
            resource='transaction',
            resource_id=transaction.id,
            data={'amount': data['amount'], 'vendor': data['vendor']},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Expense created successfully',
            'id': transaction.id,
            'transactionNumber': transaction_number
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating expense: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@treasurer_bp.route('/expenses/<int:expense_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_existing_expense(expense_id):
    """Update an expense"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        transaction = Transaction.query.get(expense_id)
        if not transaction:
            return jsonify({'error': 'Expense not found'}), 404
        
        if transaction.status != 'PENDING':
            return jsonify({'error': 'Cannot update non-pending expense'}), 400
        
        data = request.get_json()
        
        # Update fields
        if data.get('date'):
            transaction.transaction_date = datetime.fromisoformat(data['date'])
        if data.get('category'):
            transaction.category = data['category'].upper()
        if data.get('amount'):
            transaction.amount = float(data['amount'])
        if data.get('description'):
            transaction.description = data['description']
        if data.get('vendor'):
            # Update or find account
            account = Account.query.filter_by(
                church_id=g.current_user.church_id,
                name=data['vendor'],
                type='expense'
            ).first()
            if account:
                transaction.account_id = account.id
        if data.get('paymentMethod'):
            transaction.payment_method = data['paymentMethod'].upper()
        if data.get('reference'):
            transaction.reference_number = data['reference']
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='UPDATE_EXPENSE',
            resource='transaction',
            resource_id=expense_id,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Expense updated successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating expense: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to update expense: {str(e)}'}), 500


@treasurer_bp.route('/expenses/<int:expense_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_existing_expense(expense_id):
    """Delete an expense"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        transaction = Transaction.query.get(expense_id)
        if not transaction:
            return jsonify({'error': 'Expense not found'}), 404
        
        if transaction.status != 'PENDING':
            return jsonify({'error': 'Cannot delete non-pending expense'}), 400
        
        db.session.delete(transaction)
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='DELETE_EXPENSE',
            resource='transaction',
            resource_id=expense_id,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Expense deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting expense: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to delete expense: {str(e)}'}), 500


@treasurer_bp.route('/expenses/<int:expense_id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_expense_request(expense_id):
    """Approve an expense"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        transaction = Transaction.query.get(expense_id)
        if not transaction:
            return jsonify({'error': 'Expense not found'}), 404
        
        if transaction.status != 'PENDING':
            return jsonify({'error': f'Expense is already {transaction.status.lower()}'}), 400
        
        transaction.status = 'POSTED'
        transaction.approved_by = g.current_user.id
        transaction.approved_date = datetime.utcnow()
        
        # Update account balance
        account = Account.query.get(transaction.account_id)
        if account:
            from decimal import Decimal
            account.current_balance = account.current_balance - Decimal(str(transaction.amount))
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='APPROVE_EXPENSE',
            resource='transaction',
            resource_id=expense_id,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Expense approved successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving expense: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to approve expense: {str(e)}'}), 500


@treasurer_bp.route('/expenses/<int:expense_id>/reject', methods=['POST', 'OPTIONS'])
@token_required
def reject_expense_request(expense_id):
    """Reject an expense"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json() or {}
        reason = data.get('reason', 'No reason provided')
        
        transaction = Transaction.query.get(expense_id)
        if not transaction:
            return jsonify({'error': 'Expense not found'}), 404
        
        if transaction.status != 'PENDING':
            return jsonify({'error': f'Expense is already {transaction.status.lower()}'}), 400
        
        transaction.status = 'REJECTED'
        transaction.rejected_by = g.current_user.id
        transaction.rejected_date = datetime.utcnow()
        transaction.rejection_reason = reason
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='REJECT_EXPENSE',
            resource='transaction',
            resource_id=expense_id,
            data={'reason': reason},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Expense rejected'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting expense: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to reject expense: {str(e)}'}), 500


# ==================== INCOME/EXPENSE TRENDS ====================

@treasurer_bp.route('/income-expense-trends', methods=['GET', 'OPTIONS'])
@token_required
def get_income_expense_trends():
    """Get income and expense trends for chart"""
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
        
        trend_data = []
        for r in results:
            month_parts = r.month.split('-')
            month_name = datetime(int(month_parts[0]), int(month_parts[1]), 1).strftime('%b')
            
            trend_data.append({
                'month': month_name,
                'income': float(r.income or 0),
                'expenses': float(r.expenses or 0)
            })
        
        return jsonify(trend_data), 200
        
    except Exception as e:
        logger.error(f"Error getting income/expense trends: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get trends: {str(e)}'}), 500


# ==================== CATEGORY BREAKDOWN ====================

@treasurer_bp.route('/category-breakdown', methods=['GET', 'OPTIONS'])
@token_required
def get_category_breakdown():
    """Get income breakdown by category"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        period = request.args.get('period', 'month')
        
        # Set date range based on period
        end_date = datetime.utcnow()
        if period == 'month':
            start_date = end_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == 'quarter':
            quarter = (end_date.month - 1) // 3
            start_date = datetime(end_date.year, quarter * 3 + 1, 1)
        else:  # year
            start_date = datetime(end_date.year, 1, 1)
        
        # Get expense by category (changed from income to expense for treasurer view)
        results = db.session.query(
            Transaction.category,
            func.sum(Transaction.amount).label('total')
        ).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'EXPENSE',
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED'
        ).group_by(Transaction.category).order_by(desc('total')).all()
        
        category_data = []
        for r in results:
            if r.category and r.total > 0:
                category_name = r.category.replace('_', ' ').title()
                category_data.append({
                    'name': category_name,
                    'value': float(r.total)
                })
        
        return jsonify(category_data), 200
        
    except Exception as e:
        logger.error(f"Error getting category breakdown: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get category breakdown: {str(e)}'}), 500


# ==================== ALERTS ====================

@treasurer_bp.route('/alerts', methods=['GET', 'OPTIONS'])
@token_required
def get_treasurer_alerts():
    """Get treasurer alerts"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # Start with an empty try block to catch any import errors
    try:
        print("\n" + "="*60)
        print("📡 GET /treasurer/alerts called")
        print("="*60)
        
        church_id = g.current_user.church_id
        print(f"👤 User church_id: {church_id}")
        print(f"👤 User role: {g.current_user.role}")
        print(f"👤 User ID: {g.current_user.id}")
        
        alerts = []
        alert_id = 1
        
        # Check if Budget model is accessible
        try:
            print("🔍 Testing Budget model access...")
            test_budget = Budget.query.first()
            print(f"✅ Budget model accessible. Sample: {test_budget.id if test_budget else 'No budgets'}")
        except Exception as e:
            print(f"❌ Budget model error: {str(e)}")
            traceback.print_exc()
        
        # Check for pending budgets
        try:
            print("🔍 Checking pending budgets...")
            pending_budgets = Budget.query.filter_by(
                church_id=church_id,
                status='PENDING'
            ).count()
            print(f"📊 Pending budgets: {pending_budgets}")
            
            if pending_budgets > 0:
                alerts.append({
                    'id': alert_id,
                    'type': 'warning',
                    'severity': 'medium',
                    'message': f'{pending_budgets} budget(s) awaiting your review',
                    'time': 'Now'
                })
                alert_id += 1
        except Exception as e:
            print(f"❌ Error checking pending budgets: {str(e)}")
            traceback.print_exc()
            # Continue with other checks instead of failing
        
        # Check if Transaction model is accessible
        try:
            print("🔍 Testing Transaction model access...")
            test_trans = Transaction.query.first()
            print(f"✅ Transaction model accessible. Sample: {test_trans.id if test_trans else 'No transactions'}")
        except Exception as e:
            print(f"❌ Transaction model error: {str(e)}")
            traceback.print_exc()
        
        # Check for pending transactions
        try:
            print("🔍 Checking pending transactions...")
            pending_transactions = Transaction.query.filter_by(
                church_id=church_id,
                status='PENDING'
            ).count()
            print(f"📊 Pending transactions: {pending_transactions}")
            
            if pending_transactions > 0:
                alerts.append({
                    'id': alert_id,
                    'type': 'warning',
                    'severity': 'medium',
                    'message': f'{pending_transactions} transaction(s) awaiting approval',
                    'time': 'Now'
                })
                alert_id += 1
        except Exception as e:
            print(f"❌ Error checking pending transactions: {str(e)}")
            traceback.print_exc()
        
        # Check for old pending transactions
        try:
            print("🔍 Checking old pending transactions...")
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            print(f"📅 Thirty days ago: {thirty_days_ago}")
            
            old_pending = Transaction.query.filter(
                Transaction.church_id == church_id,
                Transaction.status == 'PENDING',
                Transaction.transaction_date <= thirty_days_ago
            ).count()
            print(f"📊 Old pending transactions: {old_pending}")
            
            if old_pending > 0:
                alerts.append({
                    'id': alert_id,
                    'type': 'critical',
                    'severity': 'high',
                    'message': f'{old_pending} transaction(s) pending for over 30 days',
                    'time': f'{thirty_days_ago.strftime("%b %d")}'
                })
                alert_id += 1
        except Exception as e:
            print(f"❌ Error checking old pending: {str(e)}")
            traceback.print_exc()
        
        # Check for recent rejected
        try:
            print("🔍 Checking recent rejected...")
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            print(f"📅 Seven days ago: {seven_days_ago}")
            
            recent_rejected = Transaction.query.filter(
                Transaction.church_id == church_id,
                Transaction.status == 'REJECTED',
                Transaction.transaction_date >= seven_days_ago
            ).count()
            print(f"📊 Recent rejected: {recent_rejected}")
            
            if recent_rejected > 0:
                alerts.append({
                    'id': alert_id,
                    'type': 'info',
                    'severity': 'low',
                    'message': f'{recent_rejected} transaction(s) rejected in the last 7 days',
                    'time': 'This week'
                })
                alert_id += 1
        except Exception as e:
            print(f"❌ Error checking recent rejected: {str(e)}")
            traceback.print_exc()
        
        # Check if Account model is accessible
        try:
            print("🔍 Testing Account model access...")
            test_account = Account.query.first()
            print(f"✅ Account model accessible. Sample: {test_account.id if test_account else 'No accounts'}")
        except Exception as e:
            print(f"❌ Account model error: {str(e)}")
            traceback.print_exc()
        
        # Check for low balance accounts
        try:
            print("🔍 Checking low balance accounts...")
            low_balance_accounts = Account.query.filter(
                Account.church_id == church_id,
                Account.current_balance < 1000,
                Account.is_active == True
            ).count()
            print(f"📊 Low balance accounts: {low_balance_accounts}")
            
            if low_balance_accounts > 0:
                alerts.append({
                    'id': alert_id,
                    'type': 'info',
                    'severity': 'low',
                    'message': f'{low_balance_accounts} accounts have low balance',
                    'time': 'Today'
                })
                alert_id += 1
        except Exception as e:
            print(f"❌ Error checking low balance: {str(e)}")
            traceback.print_exc()
        
        # Budget utilization alert
        try:
            print("🔍 Checking budget utilization...")
            total_budget = db.session.query(func.sum(Budget.amount)).filter(
                Budget.church_id == church_id,
                Budget.status == 'APPROVED'
            ).scalar() or 0
            print(f"📊 Total budget: {total_budget}")
            
            total_spent = db.session.query(func.sum(Transaction.amount)).filter(
                Transaction.church_id == church_id,
                Transaction.transaction_type == 'EXPENSE',
                Transaction.status == 'POSTED'
            ).scalar() or 0
            print(f"📊 Total spent: {total_spent}")
            
            if total_budget > 0:
                utilization = (total_spent / total_budget) * 100
                print(f"📊 Utilization: {utilization:.1f}%")
                
                if utilization > 85:
                    alerts.append({
                        'id': alert_id,
                        'type': 'warning',
                        'severity': 'medium',
                        'message': f'Budget utilization at {utilization:.1f}% - approaching limit',
                        'time': 'Now'
                    })
                    alert_id += 1
        except Exception as e:
            print(f"❌ Error checking budget utilization: {str(e)}")
            traceback.print_exc()
        
        print(f"✅ Returning {len(alerts)} alerts")
        return jsonify({'alerts': alerts}), 200
        
    except Exception as e:
        print(f"❌ CRITICAL ERROR in get_treasurer_alerts: {str(e)}")
        print(f"❌ Error type: {type(e).__name__}")
        print(f"❌ Error details: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Return a 200 with empty alerts instead of 500 to prevent frontend errors
        print("⚠️ Returning empty alerts due to error")
        return jsonify({'alerts': [], 'error': str(e)}), 200
    

@treasurer_bp.route('/debug', methods=['GET', 'OPTIONS'])
@token_required
def debug_treasurer():
    """Debug endpoint to check model accessibility"""
    if request.method == 'OPTIONS':
        return '', 200
    
    debug_info = {
        'user': {
            'id': g.current_user.id,
            'church_id': g.current_user.church_id,
            'role': g.current_user.role
        },
        'models': {}
    }
    
    # Check Budget model
    try:
        budget_count = Budget.query.filter_by(church_id=g.current_user.church_id).count()
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
        transaction_count = Transaction.query.filter_by(church_id=g.current_user.church_id).count()
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
        account_count = Account.query.filter_by(church_id=g.current_user.church_id).count()
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

# ==================== BUDGET STATUS ====================

@treasurer_bp.route('/budget-status', methods=['GET', 'OPTIONS'])
@token_required
def get_budget_status_report():
    """Get budget utilization status"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        # Get approved budgets grouped by department
        budgets = Budget.query.filter_by(
            church_id=church_id,
            status='APPROVED'
        ).all()
        
        # Group by department
        dept_budgets = {}
        for budget in budgets:
            dept = budget.department or 'Other'
            if dept not in dept_budgets:
                dept_budgets[dept] = {
                    'budget': 0,
                    'spent': 0
                }
            
            dept_budgets[dept]['budget'] += float(budget.approved_amount or budget.amount)
            
            # Calculate spent amount from transactions in this department
            spent = db.session.query(func.sum(Transaction.amount)).filter(
                Transaction.church_id == church_id,
                Transaction.category.ilike(f'%{dept}%'),
                Transaction.transaction_type == 'EXPENSE',
                Transaction.status == 'POSTED'
            ).scalar() or 0
            dept_budgets[dept]['spent'] += float(spent)
        
        # Format response
        budget_status = []
        for dept, data in dept_budgets.items():
            remaining = data['budget'] - data['spent']
            utilization = (data['spent'] / data['budget'] * 100) if data['budget'] > 0 else 0
            
            budget_status.append({
                'department': dept,
                'budget': data['budget'],
                'spent': data['spent'],
                'remaining': remaining,
                'utilization': round(utilization, 1)
            })
        
        return jsonify(budget_status), 200
        
    except Exception as e:
        logger.error(f"Error getting budget status: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get budget status: {str(e)}'}), 500


# ==================== CASH FLOW ====================

@treasurer_bp.route('/cash-flow', methods=['GET', 'OPTIONS'])
@token_required
def get_cash_flow_analysis():
    """Get cash flow analysis data"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        period = request.args.get('period', 'monthly')
        start_date = request.args.get('startDate')
        end_date = request.args.get('endDate')
        account_id = request.args.get('accountId')
        
        # Parse dates
        if start_date:
            start = datetime.fromisoformat(start_date)
        else:
            start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        if end_date:
            end = datetime.fromisoformat(end_date)
        else:
            end = datetime.utcnow()
        
        # Get cash accounts
        cash_accounts = Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'asset',
            Account.name.ilike('%cash%') | Account.name.ilike('%bank%'),
            Account.is_active == True
        ).all()
        
        opening_balance = 0
        closing_balance = 0
        
        for acc in cash_accounts:
            opening_balance += float(acc.opening_balance)
            closing_balance += float(acc.current_balance)
        
        # Get transactions in period
        query = Transaction.query.filter(
            Transaction.church_id == church_id,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
            Transaction.status == 'POSTED'
        )
        
        if account_id and account_id != 'all':
            query = query.filter_by(account_id=account_id)
        
        transactions = query.order_by(Transaction.transaction_date.desc()).all()
        
        # Calculate totals
        total_inflow = sum(float(t.amount) for t in transactions if t.transaction_type == 'INCOME')
        total_outflow = sum(float(t.amount) for t in transactions if t.transaction_type == 'EXPENSE')
        net_cash_flow = total_inflow - total_outflow
        
        # Group by period for chart data
        cash_flow_data = []
        if period == 'weekly':
            # Group by week
            current = start
            while current <= end:
                week_end = min(current + timedelta(days=7), end)
                week_inflow = sum(float(t.amount) for t in transactions 
                                 if t.transaction_type == 'INCOME' 
                                 and current <= t.transaction_date <= week_end)
                week_outflow = sum(float(t.amount) for t in transactions 
                                  if t.transaction_type == 'EXPENSE' 
                                  and current <= t.transaction_date <= week_end)
                
                cash_flow_data.append({
                    'week': f'Week {current.strftime("%U")}',
                    'inflow': week_inflow,
                    'outflow': week_outflow,
                    'net': week_inflow - week_outflow
                })
                current = week_end + timedelta(days=1)
        
        elif period == 'monthly':
            # Group by month
            months = {}
            for t in transactions:
                month_key = t.transaction_date.strftime('%Y-%m')
                if month_key not in months:
                    months[month_key] = {'inflow': 0, 'outflow': 0}
                
                if t.transaction_type == 'INCOME':
                    months[month_key]['inflow'] += float(t.amount)
                else:
                    months[month_key]['outflow'] += float(t.amount)
            
            for month, data in sorted(months.items()):
                cash_flow_data.append({
                    'month': datetime.strptime(month, '%Y-%m').strftime('%b'),
                    'inflow': data['inflow'],
                    'outflow': data['outflow'],
                    'net': data['inflow'] - data['outflow']
                })
        
        # Format transactions for display
        transaction_list = []
        for t in transactions[:10]:
            account = Account.query.get(t.account_id)
            transaction_list.append({
                'id': t.id,
                'date': t.transaction_date.isoformat(),
                'description': t.description,
                'category': t.category,
                'amount': float(t.amount),
                'type': 'inflow' if t.transaction_type == 'INCOME' else 'outflow',
                'reference': t.reference_number,
                'account': account.name if account else None
            })
        
        # Calculate metrics
        avg_monthly_expense = total_outflow / max(1, ((end - start).days / 30))
        cash_reserve_ratio = closing_balance / max(avg_monthly_expense, 1)
        operating_cash_flow_ratio = total_inflow / max(total_outflow, 1)
        
        metrics = {
            'operatingCashFlowRatio': round(operating_cash_flow_ratio, 2),
            'cashBurnRate': round(avg_monthly_expense, 2),
            'runway': round(cash_reserve_ratio, 1),
            'cashReserveRatio': round(cash_reserve_ratio, 2)
        }
        
        # Generate simple projections
        projections = []
        if cash_flow_data:
            avg_inflow = sum(d['inflow'] for d in cash_flow_data) / len(cash_flow_data)
            avg_outflow = sum(d['outflow'] for d in cash_flow_data) / len(cash_flow_data)
            
            next_periods = ['Apr', 'May', 'Jun', 'Jul'] if period == 'monthly' else ['Next', 'Next+1', 'Next+2', 'Next+3']
            for i, period_name in enumerate(next_periods):
                projections.append({
                    'month': period_name,
                    'projected': avg_inflow - avg_outflow,
                    'actual': None
                })
        
        return jsonify({
            'cashFlow': cash_flow_data,
            'projections': projections,
            'summary': {
                'openingBalance': opening_balance,
                'totalInflow': total_inflow,
                'totalOutflow': total_outflow,
                'netCashFlow': net_cash_flow,
                'closingBalance': closing_balance,
                'projectedBalance': closing_balance + (avg_inflow - avg_outflow) if 'avg_inflow' in locals() else closing_balance
            },
            'transactions': transaction_list,
            'metrics': metrics
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting cash flow data: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get cash flow data: {str(e)}'}), 500


# ==================== FINANCIAL OVERVIEW ====================

@treasurer_bp.route('/financial-overview', methods=['GET', 'OPTIONS'])
@token_required
def get_financial_overview():
    """Get financial overview data"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        period = request.args.get('period', 'monthly')
        start_date = request.args.get('startDate')
        end_date = request.args.get('endDate')
        
        # Parse dates
        if start_date:
            start = datetime.fromisoformat(start_date)
        else:
            start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        if end_date:
            end = datetime.fromisoformat(end_date)
        else:
            end = datetime.utcnow()
        
        # Get all posted transactions in period
        transactions = Transaction.query.filter(
            Transaction.church_id == church_id,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
            Transaction.status == 'POSTED'
        ).all()
        
        # Calculate totals
        total_income = sum(float(t.amount) for t in transactions if t.transaction_type == 'INCOME')
        total_expenses = sum(float(t.amount) for t in transactions if t.transaction_type == 'EXPENSE')
        net_income = total_income - total_expenses
        
        # Group income by category
        income_by_category = {}
        for t in transactions:
            if t.transaction_type == 'INCOME' and t.category:
                cat = t.category.replace('_', ' ').title()
                if cat not in income_by_category:
                    income_by_category[cat] = 0
                income_by_category[cat] += float(t.amount)
        
        income_data = [
            {'category': cat, 'amount': amount, 'percentage': (amount / total_income * 100) if total_income > 0 else 0}
            for cat, amount in sorted(income_by_category.items(), key=lambda x: x[1], reverse=True)
        ]
        
        # Group expenses by category
        expenses_by_category = {}
        for t in transactions:
            if t.transaction_type == 'EXPENSE' and t.category:
                cat = t.category.replace('_', ' ').title()
                if cat not in expenses_by_category:
                    expenses_by_category[cat] = 0
                expenses_by_category[cat] += float(t.amount)
        
        expenses_data = [
            {'category': cat, 'amount': amount, 'percentage': (amount / total_expenses * 100) if total_expenses > 0 else 0}
            for cat, amount in sorted(expenses_by_category.items(), key=lambda x: x[1], reverse=True)
        ]
        
        # Get monthly trends
        months_data = []
        current = start
        while current <= end:
            month_end = current.replace(day=28) + timedelta(days=4)
            month_end = month_end - timedelta(days=month_end.day)
            
            month_income = sum(float(t.amount) for t in transactions 
                              if t.transaction_type == 'INCOME' 
                              and current <= t.transaction_date <= month_end)
            month_expenses = sum(float(t.amount) for t in transactions 
                               if t.transaction_type == 'EXPENSE' 
                               and current <= t.transaction_date <= month_end)
            
            months_data.append({
                'month': current.strftime('%b'),
                'income': month_income,
                'expenses': month_expenses
            })
            
            current = month_end + timedelta(days=1)
        
        # Calculate averages
        num_months = max(len(months_data), 1)
        avg_monthly_income = total_income / num_months
        avg_monthly_expenses = total_expenses / num_months
        
        # Get top categories
        all_categories = []
        for cat, amount in income_by_category.items():
            all_categories.append({'name': cat, 'amount': amount, 'type': 'Income'})
        for cat, amount in expenses_by_category.items():
            all_categories.append({'name': cat, 'amount': -amount, 'type': 'Expense'})
        
        top_categories = sorted(all_categories, key=lambda x: abs(x['amount']), reverse=True)[:6]
        
        # Add change percentages
        for cat in top_categories:
            cat['change'] = round((cat['amount'] / max(total_income, total_expenses) * 100) or 0, 1)
        
        # Calculate key ratios
        operating_margin = (net_income / total_income * 100) if total_income > 0 else 0
        expense_ratio = (total_expenses / total_income * 100) if total_income > 0 else 0
        savings_rate = (net_income / total_income * 100) if total_income > 0 else 0
        
        # Get cash accounts for liquidity ratio
        cash_accounts = Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'asset',
            Account.name.ilike('%cash%') | Account.name.ilike('%bank%'),
            Account.is_active == True
        ).all()
        
        total_cash = sum(float(acc.current_balance) for acc in cash_accounts)
        liquidity_ratio = total_cash / max(avg_monthly_expenses, 1)
        
        return jsonify({
            'income': income_data[:10],
            'expenses': expenses_data[:10],
            'summary': {
                'totalIncome': total_income,
                'totalExpenses': total_expenses,
                'netIncome': net_income,
                'profitMargin': round(operating_margin, 1),
                'avgMonthlyIncome': round(avg_monthly_income, 2),
                'avgMonthlyExpenses': round(avg_monthly_expenses, 2)
            },
            'trends': months_data,
            'topCategories': top_categories,
            'ratios': {
                'operatingMargin': round(operating_margin, 1),
                'expenseRatio': round(expense_ratio, 1),
                'savingsRate': round(savings_rate, 1),
                'liquidityRatio': round(liquidity_ratio, 2)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting financial overview: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get financial overview: {str(e)}'}), 500