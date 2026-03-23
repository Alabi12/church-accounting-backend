# app/routes/pastor_routes.py
from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import Budget, User, AuditLog, Church
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
        
        # Calculate average response time (time from submission to approval/rejection)
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
        old_status = budget.status
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
        old_status = budget.status
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
            }
        }
        
        return jsonify(debug_info), 200
        
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500