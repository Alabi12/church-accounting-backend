# app/routes/pastor_routes.py
from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import Budget, User, AuditLog, Church, JournalEntry, JournalLine, Account
from app.extensions import db
from datetime import datetime, timedelta
from sqlalchemy import func, or_
import traceback
import logging

logger = logging.getLogger(__name__)
pastor_bp = Blueprint('pastor', __name__)

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
    try:
        # Get user if not provided
        if user is None:
            user = get_current_user()
        
        # If no user found, try to get church from g or fallback to first church
        if not user:
            # Check if church is in g (from token validation)
            if hasattr(g, 'current_user') and g.current_user and g.current_user.church_id:
                return g.current_user.church_id
            
            # Fallback: get the first available church
            default_church = Church.query.first()
            if default_church:
                logger.warning(f"No user found, using default church {default_church.id}")
                return default_church.id
            raise ValueError("No authenticated user and no default church found")
        
        # If user exists but no church_id, assign the first available church
        if not user.church_id:
            default_church = Church.query.first()
            if default_church:
                user.church_id = default_church.id
                db.session.add(user)
                db.session.commit()
                logger.info(f"Assigned user {user.id} to default church {default_church.id}")
            else:
                raise ValueError("No church found in database")
        
        return user.church_id
        
    except Exception as e:
        logger.error(f"Error in ensure_user_church: {str(e)}")
        # Last resort: try to get any church from database
        any_church = Church.query.first()
        if any_church:
            return any_church.id
        raise ValueError(f"Could not determine church: {str(e)}")


def _get_expense_status(status):
    """Convert internal status to display status"""
    status_map = {
        'PENDING': 'pending',
        'DRAFT': 'pending',
        'POSTED': 'approved',
        'REJECTED': 'rejected'
    }
    return status_map.get(status, 'pending')


# ==================== DASHBOARD STATS ====================

@pastor_bp.route('/dashboard-stats', methods=['GET', 'OPTIONS'])
@token_required
def get_dashboard_stats():
    """Get pastor dashboard statistics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Get all budgets for stats
        all_budgets = Budget.query.filter_by(church_id=church_id).all()
        
        # Calculate stats
        total_budgets = len(all_budgets)
        pending_budgets = len([b for b in all_budgets if b.status == 'PENDING'])
        approved_budgets = len([b for b in all_budgets if b.status == 'APPROVED'])
        rejected_budgets = len([b for b in all_budgets if b.status == 'REJECTED'])
        
        # Calculate amounts
        pending_amount = sum(float(b.amount) for b in all_budgets if b.status == 'PENDING')
        approved_amount = sum(float(b.amount) for b in all_budgets if b.status == 'APPROVED')
        
        # Count high priority pending budgets
        high_priority_pending = len([b for b in all_budgets if b.status == 'PENDING' and b.priority == 'HIGH'])
        
        # Calculate average response time
        response_times = []
        for budget in all_budgets:
            if budget.submitted_at and (budget.approved_at or budget.rejected_at):
                decision_time = budget.approved_at or budget.rejected_at
                response_time = (decision_time - budget.submitted_at).days
                if response_time >= 0:
                    response_times.append(response_time)
        
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        return jsonify({
            'totalBudgets': total_budgets,
            'pendingBudgets': pending_budgets,
            'approvedBudgets': approved_budgets,
            'rejectedBudgets': rejected_budgets,
            'pendingAmount': float(pending_amount),
            'approvedAmount': float(approved_amount),
            'highPriorityPending': high_priority_pending,
            'averageResponseTime': round(avg_response_time, 1)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting pastor dashboard stats: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get dashboard stats: {str(e)}'}), 500


# ==================== PENDING BUDGETS ====================

@pastor_bp.route('/pending-budgets', methods=['GET', 'OPTIONS'])
@token_required
def get_pending_budgets():
    """Get all pending budgets for pastor approval"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Query pending budgets
        pending_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).order_by(Budget.submitted_at.desc()).all()
        
        # Format the response
        budgets_list = []
        for budget in pending_budgets:
            # Get submitter info
            submitter = User.query.get(budget.submitted_by) if budget.submitted_by else None
            
            budgets_list.append({
                'id': budget.id,
                'name': budget.name,
                'description': budget.description,
                'department': budget.department,
                'fiscal_year': budget.fiscal_year,
                'amount': float(budget.amount),
                'priority': budget.priority,
                'budget_type': budget.budget_type,
                'justification': budget.justification,
                'submitted_by': budget.submitted_by,
                'submitted_by_name': submitter.full_name if submitter else 'Unknown',
                'submitted_at': budget.submitted_at.isoformat() if budget.submitted_at else None,
                'created_at': budget.created_at.isoformat() if budget.created_at else None
            })
        
        return jsonify({
            'budgets': budgets_list,
            'total': len(budgets_list)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting pending budgets: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== GET BUDGET BY ID ====================

@pastor_bp.route('/budgets/<int:budget_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_budget(budget_id):
    """Get a single budget by ID for pastor review"""
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
        
        # Get related user info
        submitter = User.query.get(budget.submitted_by) if budget.submitted_by else None
        creator = User.query.get(budget.created_by) if budget.created_by else None
        
        return jsonify({
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
            'submitted_by': budget.submitted_by,
            'submitted_by_name': submitter.full_name if submitter else None,
            'submitted_at': budget.submitted_at.isoformat() if budget.submitted_at else None,
            'created_by': budget.created_by,
            'created_by_name': creator.full_name if creator else None,
            'created_at': budget.created_at.isoformat() if budget.created_at else None,
            'monthly': {
                'january': float(budget.january) if budget.january else 0,
                'february': float(budget.february) if budget.february else 0,
                'march': float(budget.march) if budget.march else 0,
                'april': float(budget.april) if budget.april else 0,
                'may': float(budget.may) if budget.may else 0,
                'june': float(budget.june) if budget.june else 0,
                'july': float(budget.july) if budget.july else 0,
                'august': float(budget.august) if budget.august else 0,
                'september': float(budget.september) if budget.september else 0,
                'october': float(budget.october) if budget.october else 0,
                'november': float(budget.november) if budget.november else 0,
                'december': float(budget.december) if budget.december else 0
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== APPROVE BUDGET ====================

@pastor_bp.route('/budgets/<int:budget_id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_budget(budget_id):
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
        
        # Optional: set approved amount if provided
        if data.get('approved_amount'):
            budget.amount = data['approved_amount']
        
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
        
        logger.info(f"Budget {budget_id} approved by pastor {current_user.id if current_user else None}")
        
        return jsonify({
            'message': 'Budget approved successfully',
            'budget': {
                'id': budget.id,
                'status': budget.status,
                'approved_at': budget.approved_at.isoformat() if budget.approved_at else None
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to approve budget: {str(e)}'}), 500


# ==================== REJECT BUDGET ====================

@pastor_bp.route('/budgets/<int:budget_id>/reject', methods=['POST', 'OPTIONS'])
@token_required
def reject_budget(budget_id):
    """Reject a budget with reason"""
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
        
        # Update budget
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
        
        logger.info(f"Budget {budget_id} rejected by pastor {current_user.id if current_user else None}")
        
        return jsonify({
            'message': 'Budget rejected',
            'budget': {
                'id': budget.id,
                'status': budget.status,
                'rejected_at': budget.rejected_at.isoformat() if budget.rejected_at else None,
                'rejection_reason': budget.rejection_reason
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to reject budget: {str(e)}'}), 500


# ==================== APPROVED BUDGETS ====================

@pastor_bp.route('/approved-budgets', methods=['GET', 'OPTIONS'])
@token_required
def get_approved_budgets():
    """Get all approved budgets"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Query approved budgets
        approved_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='APPROVED'
        ).order_by(Budget.approved_at.desc()).all()
        
        # Format the response
        budgets_list = []
        for budget in approved_budgets:
            approver = User.query.get(budget.approved_by) if budget.approved_by else None
            
            budgets_list.append({
                'id': budget.id,
                'name': budget.name,
                'description': budget.description,
                'department': budget.department,
                'fiscal_year': budget.fiscal_year,
                'amount': float(budget.amount),
                'priority': budget.priority,
                'budget_type': budget.budget_type,
                'approved_by': budget.approved_by,
                'approved_by_name': approver.full_name if approver else None,
                'approved_at': budget.approved_at.isoformat() if budget.approved_at else None,
                'created_at': budget.created_at.isoformat() if budget.created_at else None
            })
        
        return jsonify({
            'budgets': budgets_list,
            'total': len(budgets_list)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting approved budgets: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== REJECTED BUDGETS ====================

@pastor_bp.route('/rejected-budgets', methods=['GET', 'OPTIONS'])
@token_required
def get_rejected_budgets():
    """Get all rejected budgets"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Query rejected budgets
        rejected_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='REJECTED'
        ).order_by(Budget.rejected_at.desc()).all()
        
        # Format the response
        budgets_list = []
        for budget in rejected_budgets:
            rejecter = User.query.get(budget.rejected_by) if budget.rejected_by else None
            
            budgets_list.append({
                'id': budget.id,
                'name': budget.name,
                'description': budget.description,
                'department': budget.department,
                'fiscal_year': budget.fiscal_year,
                'amount': float(budget.amount),
                'priority': budget.priority,
                'budget_type': budget.budget_type,
                'rejection_reason': budget.rejection_reason,
                'rejected_by': budget.rejected_by,
                'rejected_by_name': rejecter.full_name if rejecter else None,
                'rejected_at': budget.rejected_at.isoformat() if budget.rejected_at else None,
                'created_at': budget.created_at.isoformat() if budget.created_at else None
            })
        
        return jsonify({
            'budgets': budgets_list,
            'total': len(budgets_list)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting rejected budgets: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== SEARCH BUDGETS ====================

@pastor_bp.route('/search-budgets', methods=['GET', 'OPTIONS'])
@token_required
def search_budgets():
    """Search budgets by name, department, or description"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        query = request.args.get('q', '')
        status = request.args.get('status', 'all')
        
        if not query:
            return jsonify({'error': 'Search query required'}), 400
        
        # Build search query
        budget_query = Budget.query.filter_by(church_id=church_id)
        
        if status != 'all':
            budget_query = budget_query.filter_by(status=status.upper())
        
        # Search in name, description, and department
        budget_query = budget_query.filter(
            or_(
                Budget.name.ilike(f'%{query}%'),
                Budget.description.ilike(f'%{query}%'),
                Budget.department.ilike(f'%{query}%')
            )
        ).order_by(Budget.created_at.desc())
        
        budgets = budget_query.all()
        
        # Format response
        budgets_list = []
        for budget in budgets:
            submitter = User.query.get(budget.submitted_by) if budget.submitted_by else None
            
            budgets_list.append({
                'id': budget.id,
                'name': budget.name,
                'description': budget.description,
                'department': budget.department,
                'fiscal_year': budget.fiscal_year,
                'amount': float(budget.amount),
                'priority': budget.priority,
                'status': budget.status,
                'submitted_by_name': submitter.full_name if submitter else None,
                'submitted_at': budget.submitted_at.isoformat() if budget.submitted_at else None
            })
        
        return jsonify({
            'budgets': budgets_list,
            'total': len(budgets_list),
            'query': query
        }), 200
        
    except Exception as e:
        logger.error(f"Error searching budgets: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== EXPENSE APPROVALS ====================

@pastor_bp.route('/departments', methods=['GET', 'OPTIONS'])
@token_required
def get_departments():
    """Get list of departments for filtering"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Get unique departments from expense accounts
        departments = db.session.query(Account.category).filter(
            Account.church_id == church_id,
            Account.account_type == 'EXPENSE',
            Account.category.isnot(None)
        ).distinct().all()
        
        dept_list = [d[0] for d in departments if d[0]]
        
        # Add common departments if none found
        if not dept_list:
            dept_list = ['Youth Ministry', 'Worship', 'Outreach', 'Missions', 'Administration']
        
        return jsonify({'departments': dept_list}), 200
        
    except Exception as e:
        logger.error(f"Error fetching departments: {str(e)}")
        return jsonify({'departments': []}), 200


@pastor_bp.route('/expense-approvals', methods=['GET', 'OPTIONS'])
@token_required
def get_expense_approvals():
    """Get expense requests pending approval"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Get query parameters
        status = request.args.get('status', 'pending')
        department = request.args.get('department')
        search = request.args.get('search')
        
        # Build query for expense journal entries
        query = JournalEntry.query.join(
            JournalLine, JournalEntry.id == JournalLine.journal_entry_id
        ).join(
            Account, Account.id == JournalLine.account_id
        ).filter(
            JournalEntry.church_id == church_id,
            Account.account_type == 'EXPENSE'
        )
        
        # Apply status filter
        if status == 'pending':
            query = query.filter(JournalEntry.status.in_(['PENDING', 'DRAFT']))
        elif status == 'approved':
            query = query.filter(JournalEntry.status == 'POSTED')
        elif status == 'rejected':
            query = query.filter(JournalEntry.status == 'REJECTED')
        
        # Apply department filter
        if department and department != 'all':
            query = query.filter(Account.category == department)
        
        # Apply search filter
        if search:
            query = query.filter(
                or_(
                    JournalEntry.description.ilike(f'%{search}%'),
                    JournalEntry.reference.ilike(f'%{search}%')
                )
            )
        
        # Order by date
        query = query.order_by(JournalEntry.entry_date.desc())
        
        expenses = query.all()
        
        # Format expenses
        expenses_data = []
        total_amount = 0
        
        for entry in expenses:
            # Calculate total amount
            amount = 0
            dept = None
            for line in entry.lines:
                amount += line.debit or 0
                if not dept:
                    account = Account.query.get(line.account_id)
                    if account:
                        dept = account.category
            
            expenses_data.append({
                'id': entry.id,
                'date': entry.entry_date.isoformat(),
                'description': entry.description or 'Expense Request',
                'amount': float(amount),
                'category': dept or 'General',
                'department': dept or 'General',
                'requestedBy': getattr(entry, 'created_by_name', 'Unknown'),
                'submittedDate': entry.created_at.isoformat() if entry.created_at else entry.entry_date.isoformat(),
                'status': _get_expense_status(entry.status),
                'justification': entry.description or 'No justification provided',
                'attachments': [],
                'approvedBy': getattr(entry, 'approved_by_name', None),
                'approvedDate': entry.approved_at.isoformat() if hasattr(entry, 'approved_at') and entry.approved_at else None,
                'rejectionReason': None
            })
            total_amount += amount
        
        # Calculate stats
        stats = {
            'pending': len([e for e in expenses_data if e['status'] == 'pending']),
            'approved': len([e for e in expenses_data if e['status'] == 'approved']),
            'rejected': len([e for e in expenses_data if e['status'] == 'rejected']),
            'totalAmount': total_amount
        }
        
        return jsonify({
            'expenses': expenses_data,
            'stats': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching expense approvals: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@pastor_bp.route('/expense-approvals/<int:expense_id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_expense(expense_id):
    """Approve an expense request"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = get_current_user()
        
        journal_entry = JournalEntry.query.filter_by(
            id=expense_id,
            church_id=church_id
        ).first()
        
        if not journal_entry:
            return jsonify({'error': 'Expense not found'}), 404
        
        if journal_entry.status not in ['PENDING', 'DRAFT']:
            return jsonify({'error': f'Expense is already {journal_entry.status}'}), 400
        
        # Update status
        journal_entry.status = 'POSTED'
        journal_entry.approved_by = current_user.id if current_user else None
        journal_entry.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=current_user.id if current_user else None,
            action='APPROVE_EXPENSE',
            resource='journal_entry',
            resource_id=expense_id,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else None
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Expense approved successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving expense: {str(e)}")
        return jsonify({'error': str(e)}), 500


@pastor_bp.route('/expense-approvals/<int:expense_id>/reject', methods=['POST', 'OPTIONS'])
@token_required
def reject_expense(expense_id):
    """Reject an expense request"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = get_current_user()
        
        data = request.get_json() or {}
        reason = data.get('reason', 'No reason provided')
        
        journal_entry = JournalEntry.query.filter_by(
            id=expense_id,
            church_id=church_id
        ).first()
        
        if not journal_entry:
            return jsonify({'error': 'Expense not found'}), 404
        
        if journal_entry.status not in ['PENDING', 'DRAFT']:
            return jsonify({'error': f'Expense is already {journal_entry.status}'}), 400
        
        # Update status
        journal_entry.status = 'REJECTED'
        journal_entry.rejected_by = current_user.id if current_user else None
        journal_entry.rejected_at = datetime.utcnow()
        journal_entry.rejection_reason = reason
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=current_user.id if current_user else None,
            action='REJECT_EXPENSE',
            resource='journal_entry',
            resource_id=expense_id,
            data={'reason': reason},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else None
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Expense rejected', 'reason': reason}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting expense: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==================== DEBUG ENDPOINT ====================

@pastor_bp.route('/debug', methods=['GET', 'OPTIONS'])
@token_required
def debug_pastor():
    """Debug endpoint to check pastor routes"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = get_current_user()
        
        debug_info = {
            'user': {
                'id': current_user.id if current_user else None,
                'role': current_user.role if current_user else None,
                'church_id': church_id
            },
            'budget_stats': {
                'total': Budget.query.filter_by(church_id=church_id).count(),
                'pending': Budget.query.filter_by(church_id=church_id, status='PENDING').count(),
                'approved': Budget.query.filter_by(church_id=church_id, status='APPROVED').count(),
                'rejected': Budget.query.filter_by(church_id=church_id, status='REJECTED').count()
            },
            'expense_stats': {
                'total': JournalEntry.query.filter_by(church_id=church_id).count(),
                'pending': JournalEntry.query.filter_by(church_id=church_id, status='PENDING').count(),
                'approved': JournalEntry.query.filter_by(church_id=church_id, status='POSTED').count(),
                'rejected': JournalEntry.query.filter_by(church_id=church_id, status='REJECTED').count()
            }
        }
        
        return jsonify(debug_info), 200
        
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Add to pastor_routes.py

@pastor_bp.route('/members', methods=['GET', 'OPTIONS'])
@token_required
def get_members():
    """Get all members for pastor view"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        # Get all members (users with role 'member')
        members = User.query.filter_by(
            church_id=church_id,
            role='member'
        ).all()
        
        members_list = []
        total_giving = 0
        
        for member in members:
            # Calculate total giving from journal entries
            total_given = db.session.query(func.sum(JournalLine.credit)).join(
                JournalEntry, JournalEntry.id == JournalLine.journal_entry_id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.created_by == member.id,
                JournalEntry.entry_type == 'RECEIPT'
            ).scalar() or 0
            
            # Get last gift date
            last_gift = db.session.query(JournalEntry.entry_date).join(
                JournalLine, JournalEntry.id == JournalLine.journal_entry_id
            ).filter(
                JournalEntry.church_id == church_id,
                JournalEntry.created_by == member.id,
                JournalLine.credit > 0
            ).order_by(JournalEntry.entry_date.desc()).first()
            
            members_list.append({
                'id': member.id,
                'name': member.full_name,
                'email': member.email,
                'phone': member.phone or '',
                'joinDate': member.created_at.isoformat() if member.created_at else None,
                'totalGiven': float(total_given),
                'lastGift': last_gift[0].isoformat() if last_gift else None,
                'givingFrequency': 'monthly',  # Calculate based on history
                'status': 'active' if member.is_active else 'inactive'
            })
            total_giving += float(total_given)
        
        # Calculate stats
        stats = {
            'totalGivers': len(members_list),
            'totalAmount': total_giving,
            'averageGift': total_giving / len(members_list) if members_list else 0,
            'topGiver': members_list[0]['name'] if members_list else '',
            'monthlyTotal': total_giving / 12 if total_giving > 0 else 0,
            'growth': 12.5  # Calculate from historical data
        }
        
        return jsonify({
            'members': members_list,
            'stats': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting members: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@pastor_bp.route('/members/<int:member_id>/giving', methods=['GET', 'OPTIONS'])
@token_required
def get_member_giving(member_id):
    """Get giving history for a specific member"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        start_date = request.args.get('startDate')
        end_date = request.args.get('endDate')
        
        # Verify member belongs to this church
        member = User.query.filter_by(
            id=member_id,
            church_id=church_id,
            role='member'
        ).first()
        
        if not member:
            return jsonify({'error': 'Member not found'}), 404
        
        # Build query for giving history
        query = JournalEntry.query.join(
            JournalLine, JournalEntry.id == JournalLine.journal_entry_id
        ).filter(
            JournalEntry.church_id == church_id,
            JournalEntry.created_by == member_id,
            JournalEntry.entry_type == 'RECEIPT',
            JournalLine.credit > 0
        )
        
        if start_date:
            query = query.filter(JournalEntry.entry_date >= start_date)
        if end_date:
            query = query.filter(JournalEntry.entry_date <= end_date)
        
        entries = query.order_by(JournalEntry.entry_date.desc()).all()
        
        # Format giving history
        history = []
        monthly_data = {}
        category_data = {}
        
        for entry in entries:
            amount = 0
            category = 'tithe'  # Default category
            
            for line in entry.lines:
                if line.credit > 0:
                    amount = line.credit
                    # Try to determine category from account
                    account = Account.query.get(line.account_id)
                    if account:
                        if 'tithe' in account.name.lower():
                            category = 'tithe'
                        elif 'offering' in account.name.lower():
                            category = 'offering'
                        else:
                            category = 'special'
                    break
            
            history.append({
                'date': entry.entry_date.isoformat(),
                'amount': float(amount),
                'category': category,
                'method': 'online'  # You can track this in your transactions table
            })
            
            # Aggregate for monthly chart
            month_key = entry.entry_date.strftime('%b')
            monthly_data[month_key] = monthly_data.get(month_key, 0) + float(amount)
            
            # Aggregate for category chart
            category_data[category] = category_data.get(category, 0) + float(amount)
        
        # Format chart data
        chart_data = [{'month': month, 'amount': amount} for month, amount in monthly_data.items()]
        
        # Format category data
        category_chart_data = [{'name': k.capitalize(), 'value': v} for k, v in category_data.items()]
        
        return jsonify({
            'history': history,
            'chartData': chart_data,
            'categoryData': category_chart_data
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting member giving: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500