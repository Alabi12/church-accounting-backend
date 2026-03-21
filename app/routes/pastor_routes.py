# app/routes/pastor_routes.py
from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import Budget, User, AuditLog, BudgetComment
from app.extensions import db
from datetime import datetime
from functools import wraps
import traceback
import logging
from sqlalchemy import func  # Add this import
from app import socketio

logger = logging.getLogger(__name__)
pastor_bp = Blueprint('pastor', __name__)

# Import token_required from auth_routes
from app.routes.auth_routes import token_required

def pastor_required(f):
    """Decorator to check if user has pastor role or higher"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(g, 'current_user') or not g.current_user:
            return jsonify({'error': 'Authentication required'}), 401
        
        # Allow super_admin, admin, and pastor to access
        if g.current_user.role not in ['super_admin', 'admin', 'pastor']:
            return jsonify({'error': 'Pastor access required'}), 403
        
        return f(*args, **kwargs)
    return decorated_function

# ==================== PENDING BUDGETS ====================

@pastor_bp.route('/pending-budgets', methods=['GET', 'OPTIONS'])
@token_required
@pastor_required
def get_pending_budgets():
    """Get all pending budgets for pastor approval"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        print(f"\n{'='*60}")
        print("📡 GET /pastor/pending-budgets called")
        print(f"{'='*60}")
        
        church_id = g.current_user.church_id
        print(f"👤 User ID: {g.current_user.id}, Role: {g.current_user.role}, Church ID: {church_id}")
        
        # Get all pending budgets for this church
        pending_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).order_by(Budget.submitted_date.desc()).all()
        
        print(f"📊 Found {len(pending_budgets)} pending budgets")
        
        # Format the response
        budget_list = []
        for budget in pending_budgets:
            submitter = User.query.get(budget.submitted_by)
            
            # Calculate days pending
            days_pending = 0
            if budget.submitted_date:
                days_pending = (datetime.utcnow() - budget.submitted_date).days
            
            # Get comment count safely
            comment_count = 0
            if hasattr(budget, 'comments'):
                comment_count = budget.comments.count()
            
            budget_list.append({
                'id': budget.id,
                'name': budget.name,
                'description': budget.description,
                'department': budget.department,
                'fiscalYear': budget.fiscal_year,
                'fiscal_year': budget.fiscal_year,
                'amount': float(budget.amount),
                'submittedBy': submitter.full_name if submitter else 'Unknown',
                'submitted_by_name': submitter.full_name if submitter else 'Unknown',
                'submittedById': budget.submitted_by,
                'submittedDate': budget.submitted_date.isoformat() if budget.submitted_date else None,
                'submitted_date': budget.submitted_date.isoformat() if budget.submitted_date else None,
                'daysPending': days_pending,
                'priority': budget.priority,
                'justification': budget.justification,
                'commentCount': comment_count,
                'created_at': budget.created_at.isoformat() if budget.created_at else None
            })
        
        # Get stats
        stats = {
            'total': len(budget_list),
            'highPriority': sum(1 for b in pending_budgets if b.priority == 'HIGH'),
            'mediumPriority': sum(1 for b in pending_budgets if b.priority == 'MEDIUM'),
            'lowPriority': sum(1 for b in pending_budgets if b.priority == 'LOW'),
            'totalAmount': sum(float(b.amount) for b in pending_budgets)
        }
        
        print(f"✅ Returning {len(budget_list)} budgets")
        return jsonify({
            'budgets': budget_list,
            'stats': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting pending budgets: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get pending budgets: {str(e)}'}), 500

# ==================== APPROVE BUDGET ====================

@pastor_bp.route('/budgets/<int:budget_id>/approve', methods=['POST', 'OPTIONS'])
@token_required
@pastor_required
def approve_budget(budget_id):
    """Approve a budget as pastor"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        print(f"\n{'='*60}")
        print(f"📡 Pastor approving budget ID: {budget_id}")
        print(f"{'='*60}")
        
        data = request.get_json() or {}
        comments = data.get('comments', '')
        
        print(f"📦 Request data: {data}")
        print(f"👤 Approver: {g.current_user.id} - {g.current_user.full_name}")
        
        # Find the budget
        budget = Budget.query.get(budget_id)
        if not budget:
            print(f"❌ Budget {budget_id} not found")
            return jsonify({'error': 'Budget not found'}), 404
        
        print(f"✅ Budget found: {budget.name}, Current status: {budget.status}")
        
        # Check church access
        if budget.church_id != g.current_user.church_id:
            print(f"❌ Access denied: Budget church {budget.church_id} != User church {g.current_user.church_id}")
            return jsonify({'error': 'Access denied'}), 403
        
        # Check if budget is pending
        if budget.status != 'PENDING':
            print(f"❌ Budget is not pending: {budget.status}")
            return jsonify({'error': f'Budget is already {budget.status.lower()}'}), 400
        
        # Update budget
        budget.status = 'APPROVED'
        budget.approved_by = g.current_user.id
        budget.approved_date = datetime.utcnow()
        
        # Add comment if provided
        if comments:
            comment = BudgetComment(
                budget_id=budget_id,
                user_id=g.current_user.id,
                comment=comments
            )
            db.session.add(comment)
            print(f"✅ Comment added: {comments[:50]}...")
        
        db.session.commit()
        print(f"✅ Database commit successful")
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='PASTOR_APPROVE_BUDGET',
            resource='budget',
            resource_id=budget_id,
            data={'comments': comments},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        print(f"✅ Audit log created")
        
        # Emit socket event for real-time updates
        try:
            socketio.emit('budget_updated', {
                'budget_id': budget_id,
                'status': 'APPROVED',
                'action': 'approve',
                'approved_by': g.current_user.full_name,
                'timestamp': datetime.utcnow().isoformat()
            })
            print(f"✅ Socket event emitted")
        except Exception as e:
            print(f"⚠️ Socket emit failed (non-critical): {e}")
        
        return jsonify({
            'message': 'Budget approved successfully',
            'budget': {
                'id': budget.id,
                'status': budget.status,
                'approved_by': g.current_user.full_name,
                'approved_date': budget.approved_date.isoformat()
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== REJECT BUDGET ====================

@pastor_bp.route('/budgets/<int:budget_id>/reject', methods=['POST', 'OPTIONS'])
@token_required
@pastor_required
def reject_budget(budget_id):
    """Reject a budget as pastor"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        print(f"\n{'='*60}")
        print(f"📡 Pastor rejecting budget ID: {budget_id}")
        print(f"{'='*60}")
        
        data = request.get_json()
        if not data or 'reason' not in data:
            return jsonify({'error': 'Rejection reason is required'}), 400
        
        reason = data['reason']
        comments = data.get('comments', '')
        
        print(f"📦 Rejection reason: {reason}")
        print(f"👤 Rejecter: {g.current_user.id} - {g.current_user.full_name}")
        
        # Find the budget
        budget = Budget.query.get(budget_id)
        if not budget:
            print(f"❌ Budget {budget_id} not found")
            return jsonify({'error': 'Budget not found'}), 404
        
        print(f"✅ Budget found: {budget.name}, Current status: {budget.status}")
        
        # Check church access
        if budget.church_id != g.current_user.church_id:
            print(f"❌ Access denied: Budget church {budget.church_id} != User church {g.current_user.church_id}")
            return jsonify({'error': 'Access denied'}), 403
        
        # Check if budget is pending
        if budget.status != 'PENDING':
            print(f"❌ Budget is not pending: {budget.status}")
            return jsonify({'error': f'Budget is already {budget.status.lower()}'}), 400
        
        # Update budget
        budget.status = 'REJECTED'
        budget.rejected_by = g.current_user.id
        budget.rejected_date = datetime.utcnow()
        budget.rejection_reason = reason
        
        # Add comment if provided
        if comments:
            comment = BudgetComment(
                budget_id=budget_id,
                user_id=g.current_user.id,
                comment=f"Rejection reason: {reason}\n\n{comments}"
            )
            db.session.add(comment)
            print(f"✅ Comment added")
        
        db.session.commit()
        print(f"✅ Database commit successful")
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='PASTOR_REJECT_BUDGET',
            resource='budget',
            resource_id=budget_id,
            data={'reason': reason},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        print(f"✅ Audit log created")
        
        # Emit socket event for real-time updates
        try:
            socketio.emit('budget_updated', {
                'budget_id': budget_id,
                'status': 'REJECTED',
                'action': 'reject',
                'rejected_by': g.current_user.full_name,
                'reason': reason,
                'timestamp': datetime.utcnow().isoformat()
            })
            print(f"✅ Socket event emitted")
        except Exception as e:
            print(f"⚠️ Socket emit failed (non-critical): {e}")
        
        return jsonify({
            'message': 'Budget rejected',
            'budget': {
                'id': budget.id,
                'status': budget.status,
                'rejected_by': g.current_user.full_name,
                'rejected_date': budget.rejected_date.isoformat(),
                'rejection_reason': reason
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting budget: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== BUDGET COMMENTS ====================

@pastor_bp.route('/budgets/<int:budget_id>/comments', methods=['GET', 'OPTIONS'])
@token_required
@pastor_required
def get_budget_comments(budget_id):
    """Get comments for a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        budget = Budget.query.get(budget_id)
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
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
        
        return jsonify({'comments': result}), 200
        
    except Exception as e:
        print(f"Error getting comments: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@pastor_bp.route('/budgets/<int:budget_id>/comments', methods=['POST', 'OPTIONS'])
@token_required
@pastor_required
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
        
        # Create comment
        comment = BudgetComment(
            budget_id=budget_id,
            user_id=g.current_user.id,
            comment=comment_text
        )
        
        db.session.add(comment)
        db.session.commit()
        
        # Get user info for response
        user = User.query.get(g.current_user.id)
        
        return jsonify({
            'message': 'Comment added successfully',
            'comment': {
                'id': comment.id,
                'user': user.full_name if user else 'Unknown',
                'user_id': g.current_user.id,
                'text': comment.comment,
                'date': comment.created_at.isoformat() if comment.created_at else None
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"Error adding comment: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
# ==================== BUDGET DETAILS ====================

@pastor_bp.route('/budgets/<int:budget_id>', methods=['GET', 'OPTIONS'])
@token_required
@pastor_required
def get_budget_details(budget_id):
    """Get budget details for pastor view"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        print(f"\n{'='*60}")
        print(f"📡 Pastor fetching budget details ID: {budget_id}")
        print(f"{'='*60}")
        
        budget = Budget.query.get(budget_id)
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        if budget.church_id != g.current_user.church_id:
            return jsonify({'error': 'Access denied'}), 403
        
        # Get submitter info
        submitter = User.query.get(budget.submitted_by)
        
        # Get approver/rejecter info
        approver = User.query.get(budget.approved_by) if budget.approved_by else None
        rejecter = User.query.get(budget.rejected_by) if budget.rejected_by else None
        
        # Get comments
        comments = []
        if hasattr(budget, 'comments'):
            for comment in budget.comments.order_by(BudgetComment.created_at.desc()).all():
                commenter = User.query.get(comment.user_id)
                comments.append({
                    'id': comment.id,
                    'user': commenter.full_name if commenter else 'Unknown',
                    'userId': comment.user_id,
                    'text': comment.comment,
                    'date': comment.created_at.isoformat() if comment.created_at else None
                })
        
        response_data = {
            'id': budget.id,
            'name': budget.name,
            'description': budget.description,
            'department': budget.department,
            'fiscalYear': budget.fiscal_year,
            'fiscal_year': budget.fiscal_year,
            'amount': float(budget.amount),
            'approvedAmount': float(budget.approved_amount) if budget.approved_amount else None,
            'approved_amount': float(budget.approved_amount) if budget.approved_amount else None,
            'status': budget.status,
            'priority': budget.priority,
            'justification': budget.justification,
            'submittedBy': submitter.full_name if submitter else None,
            'submitted_by_name': submitter.full_name if submitter else None,
            'submittedById': budget.submitted_by,
            'submittedDate': budget.submitted_date.isoformat() if budget.submitted_date else None,
            'submitted_date': budget.submitted_date.isoformat() if budget.submitted_date else None,
            'approvedBy': approver.full_name if approver else None,
            'approvedDate': budget.approved_date.isoformat() if budget.approved_date else None,
            'rejectedBy': rejecter.full_name if rejecter else None,
            'rejectedDate': budget.rejected_date.isoformat() if budget.rejected_date else None,
            'rejectionReason': budget.rejection_reason,
            'rejection_reason': budget.rejection_reason,
            'comments': comments,
            'createdAt': budget.created_at.isoformat() if budget.created_at else None,
            'created_at': budget.created_at.isoformat() if budget.created_at else None
        }
        
        print(f"✅ Returning budget details for: {budget.name}")
        return jsonify(response_data), 200
        
    except Exception as e:
        logger.error(f"Error getting budget details: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get budget details: {str(e)}'}), 500


# ==================== DASHBOARD STATS ====================

@pastor_bp.route('/dashboard-stats', methods=['GET', 'OPTIONS'])
@token_required
@pastor_required
def get_dashboard_stats():
    """Get pastor dashboard statistics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        print(f"\n📡 Pastor dashboard stats for church {church_id}")
        
        # Get budget stats
        total_budgets = Budget.query.filter_by(church_id=church_id).count()
        pending_budgets = Budget.query.filter_by(church_id=church_id, status='PENDING').count()
        approved_budgets = Budget.query.filter_by(church_id=church_id, status='APPROVED').count()
        rejected_budgets = Budget.query.filter_by(church_id=church_id, status='REJECTED').count()
        
        # Calculate total amounts
        pending_amount = db.session.query(func.sum(Budget.amount)).filter(
            Budget.church_id == church_id,
            Budget.status == 'PENDING'
        ).scalar() or 0
        
        approved_amount = db.session.query(func.sum(Budget.amount)).filter(
            Budget.church_id == church_id,
            Budget.status == 'APPROVED'
        ).scalar() or 0
        
        # Get high priority pending
        high_priority_pending = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING',
            priority='HIGH'
        ).count()
        
        print(f"📊 Stats - Total: {total_budgets}, Pending: {pending_budgets}, Approved: {approved_budgets}")
        
        return jsonify({
            'totalBudgets': total_budgets,
            'pendingBudgets': pending_budgets,
            'approvedBudgets': approved_budgets,
            'rejectedBudgets': rejected_budgets,
            'pendingAmount': float(pending_amount),
            'approvedAmount': float(approved_amount),
            'highPriorityPending': high_priority_pending,
            'averageResponseTime': 2.5  # You can calculate this from actual data
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting pastor stats: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get stats: {str(e)}'}), 500


# ==================== TEST ENDPOINT ====================

@pastor_bp.route('/test', methods=['GET'])
def test():
    """Test endpoint to verify blueprint is working"""
    return jsonify({
        'message': 'Pastor routes are working!',
        'status': 'ok'
    }), 200