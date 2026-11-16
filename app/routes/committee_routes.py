from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import Budget, User, AuditLog, Church, JournalEntry, JournalLine, Account
from app.extensions import db
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_
import logging
import traceback
import json

logger = logging.getLogger(__name__)
committee_bp = Blueprint('committee', __name__)

# Define allowed roles at the top
ALLOWED_ROLES = ['finance_committee', 'admin', 'pastor', 'super_admin', 'treasurer', 'accountant']

def get_current_user():
    """Get current user from JWT token"""
    try:
        user_id = get_jwt_identity()
        if user_id:
            return User.query.get(int(user_id))
    except Exception as e:
        logger.warning(f"Error getting user from JWT: {e}")
    return None

def check_role(current_user):
    """Helper function to check if user has required role"""
    if not current_user:
        return False
    return current_user.role in ALLOWED_ROLES

# ==================== DASHBOARD ENDPOINTS ====================

@committee_bp.route('/dashboard-stats', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_dashboard_stats():
    """Get committee dashboard statistics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        church_id = current_user.church_id
        
        # Get budget statistics
        pending_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).count()
        
        reviewed_budgets = Budget.query.filter(
            Budget.church_id == church_id,
            Budget.status.in_(['APPROVED', 'REJECTED'])
        ).count()
        
        total_budgets = Budget.query.filter_by(church_id=church_id).count()
        
        # Get open votes (pending budgets)
        open_votes = pending_budgets
        
        # Get upcoming deadlines
        upcoming_deadlines = Budget.query.filter(
            Budget.church_id == church_id,
            Budget.status == 'PENDING',
            Budget.submitted_at <= datetime.utcnow() + timedelta(days=7)
        ).count()
        
        stats = {
            'pendingBudgets': pending_budgets,
            'upcomingMeetings': 0,
            'openVotes': open_votes,
            'reviewedBudgets': reviewed_budgets,
            'pendingResolutions': 0,
            'upcomingDeadlines': upcoming_deadlines,
            'totalBudgets': total_budgets,
            'attendanceRate': 85,
            'resolutionsPassed': 12,
            'totalResolutions': 15
        }
        
        return jsonify(stats), 200
        
    except Exception as e:
        logger.error(f"Error getting committee stats: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@committee_bp.route('/recent-budgets', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_recent_budgets():
    """Get recent budgets for review"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        church_id = current_user.church_id
        
        # Get pending budgets first
        pending_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).order_by(Budget.submitted_at.desc()).limit(10).all()
        
        # Format response
        budgets_list = []
        for budget in pending_budgets:
            submitter = User.query.get(budget.submitted_by) if budget.submitted_by else None
            
            budgets_list.append({
                'id': budget.id,
                'name': budget.name,
                'department': budget.department or 'General',
                'amount': float(budget.amount),
                'submittedBy': submitter.full_name if submitter else 'Unknown',
                'submittedDate': budget.submitted_at.isoformat() if budget.submitted_at else budget.created_at.isoformat(),
                'status': budget.status.lower(),
                'priority': budget.priority.lower() if budget.priority else 'medium'
            })
        
        # If not enough pending budgets, add some approved/recent ones
        if len(budgets_list) < 10:
            recent_budgets = Budget.query.filter(
                Budget.church_id == church_id,
                Budget.status.in_(['APPROVED', 'REJECTED'])
            ).order_by(Budget.approved_at.desc()).limit(10 - len(budgets_list)).all()
            
            for budget in recent_budgets:
                approver = User.query.get(budget.approved_by) if budget.approved_by else None
                budgets_list.append({
                    'id': budget.id,
                    'name': budget.name,
                    'department': budget.department or 'General',
                    'amount': float(budget.amount),
                    'submittedBy': approver.full_name if approver else 'System',
                    'submittedDate': budget.approved_at.isoformat() if budget.approved_at else budget.created_at.isoformat(),
                    'status': budget.status.lower(),
                    'priority': budget.priority.lower() if budget.priority else 'medium'
                })
        
        return jsonify({'budgets': budgets_list}), 200
        
    except Exception as e:
        logger.error(f"Error getting recent budgets: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@committee_bp.route('/upcoming-votes', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_upcoming_votes():
    """Get upcoming votes for committee members"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        church_id = current_user.church_id
        
        # Get budgets pending approval
        pending_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).filter(
            Budget.submitted_at <= datetime.utcnow() + timedelta(days=3)
        ).limit(5).all()
        
        votes_list = []
        for budget in pending_budgets:
            # Check if user has voted
            has_voted = AuditLog.query.filter_by(
                user_id=current_user.id,
                resource='budget',
                resource_id=budget.id,
                action='CAST_VOTE'
            ).first() is not None
            
            votes_list.append({
                'id': budget.id,
                'title': f"Budget Approval: {budget.name}",
                'meeting': 'Finance Committee Meeting',
                'date': (datetime.utcnow() + timedelta(days=2)).isoformat(),
                'deadline': (datetime.utcnow() + timedelta(days=1)).isoformat(),
                'status': 'voted' if has_voted else 'open',
                'yesVotes': 0,
                'noVotes': 0,
                'abstain': 0
            })
        
        return jsonify({'votes': votes_list}), 200
        
    except Exception as e:
        logger.error(f"Error getting upcoming votes: {str(e)}")
        return jsonify({'votes': []}), 200

@committee_bp.route('/upcoming-meetings', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_upcoming_meetings():
    """Get upcoming committee meetings"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        church_id = current_user.church_id
        
        meetings = []
        
        # Check if there are any pending budgets that need discussion
        pending_count = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).count()
        
        if pending_count > 0:
            meetings.append({
                'id': 1,
                'title': 'Budget Review Committee Meeting',
                'date': (datetime.utcnow() + timedelta(days=5)).isoformat(),
                'time': '19:00',
                'location': 'Conference Room A',
                'agenda': ['Opening Prayer', 'Review Pending Budgets', 'Financial Report', 'New Business'],
                'attendees': 7
            })
        
        return jsonify({'meetings': meetings}), 200
        
    except Exception as e:
        logger.error(f"Error getting upcoming meetings: {str(e)}")
        return jsonify({'meetings': []}), 200

@committee_bp.route('/budget-trends', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_budget_trends():
    """Get budget request trends over time"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        church_id = current_user.church_id
        
        # Get last 6 months of data
        trends = []
        for i in range(5, -1, -1):
            month_date = datetime.utcnow().replace(day=1) - timedelta(days=30 * i)
            month_start = month_date.replace(day=1)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            
            # Get budgets submitted in this month
            monthly_budgets = Budget.query.filter(
                Budget.church_id == church_id,
                Budget.created_at >= month_start,
                Budget.created_at <= month_end
            ).all()
            
            requested = sum(float(b.amount) for b in monthly_budgets)
            approved = sum(float(b.amount) for b in monthly_budgets if b.status == 'APPROVED')
            
            trends.append({
                'month': month_start.strftime('%b'),
                'requested': requested,
                'approved': approved,
                'variance': requested - approved
            })
        
        return jsonify(trends), 200
        
    except Exception as e:
        logger.error(f"Error getting budget trends: {str(e)}")
        return jsonify([]), 200

@committee_bp.route('/alerts', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_alerts():
    """Get important alerts for committee members"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        church_id = current_user.church_id
        
        alerts = []
        
        # Check for budgets pending > 7 days
        old_pending = Budget.query.filter(
            Budget.church_id == church_id,
            Budget.status == 'PENDING',
            Budget.submitted_at <= datetime.utcnow() - timedelta(days=7)
        ).count()
        
        if old_pending > 0:
            alerts.append({
                'id': 1,
                'type': 'warning',
                'message': f'{old_pending} budget(s) pending review for over a week',
                'time': 'Just now',
                'meetingId': None
            })
        
        # Check for urgent budgets (high priority)
        high_priority = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING',
            priority='HIGH'
        ).count()
        
        if high_priority > 0:
            alerts.append({
                'id': 2,
                'type': 'critical',
                'message': f'{high_priority} high priority budget(s) require immediate attention',
                'time': 'Just now',
                'meetingId': None
            })
        
        # Check for upcoming deadlines
        upcoming_deadlines = Budget.query.filter(
            Budget.church_id == church_id,
            Budget.status == 'PENDING',
            Budget.submitted_at <= datetime.utcnow() + timedelta(days=3)
        ).count()
        
        if upcoming_deadlines > 0:
            alerts.append({
                'id': 3,
                'type': 'info',
                'message': f'{upcoming_deadlines} budget(s) approaching review deadline',
                'time': 'Just now',
                'meetingId': None
            })
        
        return jsonify({'alerts': alerts}), 200
        
    except Exception as e:
        logger.error(f"Error getting alerts: {str(e)}")
        return jsonify({'alerts': []}), 200

# ==================== BUDGETS ENDPOINTS ====================

@committee_bp.route('/budgets', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_committee_budgets():
    """Get budgets for committee review with filtering"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        church_id = current_user.church_id
        
        # Get filter parameters
        status = request.args.get('status', 'all')
        department = request.args.get('department', 'all')
        priority = request.args.get('priority', 'all')
        search = request.args.get('search', '')
        
        # Build query
        query = Budget.query.filter_by(church_id=church_id)
        
        # Apply status filter
        if status != 'all':
            if status == 'pending':
                query = query.filter_by(status='PENDING')
            elif status == 'reviewed':
                query = query.filter(Budget.status.in_(['APPROVED', 'REJECTED']))
            elif status == 'approved':
                query = query.filter_by(status='APPROVED')
            elif status == 'rejected':
                query = query.filter_by(status='REJECTED')
        
        # Apply department filter
        if department != 'all':
            query = query.filter_by(department=department)
        
        # Apply priority filter
        if priority != 'all':
            query = query.filter_by(priority=priority.upper())
        
        # Apply search filter
        if search:
            query = query.filter(
                or_(
                    Budget.name.ilike(f'%{search}%'),
                    Budget.description.ilike(f'%{search}%'),
                    Budget.department.ilike(f'%{search}%')
                )
            )
        
        # Order by submitted date
        budgets = query.order_by(Budget.submitted_at.desc()).all()
        
        # Format response
        budgets_list = []
        for budget in budgets:
            submitter = User.query.get(budget.submitted_by) if budget.submitted_by else None
            
            # Get comments count
            comment_count = AuditLog.query.filter_by(
                resource='budget',
                resource_id=budget.id,
                action='BUDGET_REVIEW'
            ).count()
            
            budgets_list.append({
                'id': budget.id,
                'name': budget.name,
                'department': budget.department or 'General',
                'fiscalYear': budget.fiscal_year or datetime.utcnow().year,
                'amount': float(budget.amount),
                'requestedAmount': float(budget.amount),
                'previousAmount': float(budget.amount) * 0.9,
                'submittedBy': submitter.full_name if submitter else 'Unknown',
                'submittedDate': budget.submitted_at.isoformat() if budget.submitted_at else budget.created_at.isoformat(),
                'status': budget.status.lower(),
                'priority': budget.priority.lower() if budget.priority else 'medium',
                'description': budget.description or '',
                'commentCount': comment_count
            })
        
        # Calculate stats
        stats = {
            'total': Budget.query.filter_by(church_id=church_id).count(),
            'pending': Budget.query.filter_by(church_id=church_id, status='PENDING').count(),
            'reviewed': Budget.query.filter(
                Budget.church_id == church_id,
                Budget.status.in_(['APPROVED', 'REJECTED'])
            ).count(),
            'approved': Budget.query.filter_by(church_id=church_id, status='APPROVED').count(),
            'rejected': Budget.query.filter_by(church_id=church_id, status='REJECTED').count()
        }
        
        return jsonify({
            'budgets': budgets_list,
            'stats': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting budgets: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@committee_bp.route('/budgets/<int:budget_id>', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_budget_detail(budget_id):
    """Get detailed budget information"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        church_id = current_user.church_id
        budget = Budget.query.filter_by(id=budget_id, church_id=church_id).first()
        
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        submitter = User.query.get(budget.submitted_by) if budget.submitted_by else None
        approver = User.query.get(budget.approved_by) if budget.approved_by else None
        
        # Get all comments/reviews
        comments = []
        audit_logs = AuditLog.query.filter_by(
            resource='budget',
            resource_id=budget.id
        ).order_by(AuditLog.created_at.desc()).all()
        
        for log in audit_logs:
            commenter = User.query.get(log.user_id) if log.user_id else None
            comments.append({
                'id': log.id,
                'user': commenter.full_name if commenter else 'System',
                'text': log.data.get('comments', f"Action: {log.action}") if log.data else f"Action: {log.action}",
                'date': log.created_at.isoformat() if log.created_at else None
            })
        
        budget_data = {
            'id': budget.id,
            'name': budget.name,
            'description': budget.description,
            'department': budget.department,
            'fiscalYear': budget.fiscal_year,
            'requestedAmount': float(budget.amount),
            'previousAmount': float(budget.amount) * 0.9,
            'submittedBy': submitter.full_name if submitter else 'Unknown',
            'submittedDate': budget.submitted_at.isoformat() if budget.submitted_at else budget.created_at.isoformat(),
            'status': budget.status.lower(),
            'priority': budget.priority.lower() if budget.priority else 'medium',
            'justification': budget.justification,
            'approvedBy': approver.full_name if approver else None,
            'approvedAt': budget.approved_at.isoformat() if budget.approved_at else None,
            'rejectionReason': budget.rejection_reason,
            'comments': comments
        }
        
        return jsonify(budget_data), 200
        
    except Exception as e:
        logger.error(f"Error getting budget detail: {str(e)}")
        return jsonify({'error': str(e)}), 500

@committee_bp.route('/budgets/<int:budget_id>/approve', methods=['POST', 'OPTIONS'])
@jwt_required()
def approve_budget_committee(budget_id):
    """Approve a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        data = request.get_json() or {}
        comments = data.get('comments', '')
        
        church_id = current_user.church_id
        budget = Budget.query.filter_by(id=budget_id, church_id=church_id).first()
        
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        if budget.status != 'PENDING':
            return jsonify({'error': f'Budget is already {budget.status}'}), 400
        
        # Update budget
        budget.status = 'APPROVED'
        budget.approved_by = current_user.id
        budget.approved_at = datetime.utcnow()
        
        # Log the approval
        audit_log = AuditLog(
            user_id=current_user.id,
            action='BUDGET_APPROVED',
            resource='budget',
            resource_id=budget_id,
            data={'comments': comments, 'approved_amount': float(budget.amount)},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else None
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Budget approved successfully',
            'budget_id': budget_id,
            'status': 'approved'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving budget: {str(e)}")
        return jsonify({'error': str(e)}), 500

@committee_bp.route('/budgets/<int:budget_id>/reject', methods=['POST', 'OPTIONS'])
@jwt_required()
def reject_budget_committee(budget_id):
    """Reject a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        data = request.get_json() or {}
        reason = data.get('reason', 'No reason provided')
        comments = data.get('comments', '')
        
        church_id = current_user.church_id
        budget = Budget.query.filter_by(id=budget_id, church_id=church_id).first()
        
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        if budget.status != 'PENDING':
            return jsonify({'error': f'Budget is already {budget.status}'}), 400
        
        # Update budget
        budget.status = 'REJECTED'
        budget.rejected_by = current_user.id
        budget.rejected_at = datetime.utcnow()
        budget.rejection_reason = reason
        
        # Log the rejection
        audit_log = AuditLog(
            user_id=current_user.id,
            action='BUDGET_REJECTED',
            resource='budget',
            resource_id=budget_id,
            data={'reason': reason, 'comments': comments},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else None
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Budget rejected',
            'budget_id': budget_id,
            'status': 'rejected'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting budget: {str(e)}")
        return jsonify({'error': str(e)}), 500

@committee_bp.route('/budgets/<int:budget_id>/request-changes', methods=['POST', 'OPTIONS'])
@jwt_required()
def request_budget_changes(budget_id):
    """Request changes to a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        data = request.get_json() or {}
        changes_needed = data.get('changes', '')
        comments = data.get('comments', '')
        
        church_id = current_user.church_id
        budget = Budget.query.filter_by(id=budget_id, church_id=church_id).first()
        
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        # Log the change request
        audit_log = AuditLog(
            user_id=current_user.id,
            action='BUDGET_CHANGES_REQUESTED',
            resource='budget',
            resource_id=budget_id,
            data={'changes_needed': changes_needed, 'comments': comments},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else None
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Change request submitted',
            'budget_id': budget_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error requesting changes: {str(e)}")
        return jsonify({'error': str(e)}), 500

@committee_bp.route('/budgets/<int:budget_id>/comments', methods=['POST', 'OPTIONS'])
@jwt_required()
def add_budget_comment(budget_id):
    """Add a comment to a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        data = request.get_json() or {}
        comment_text = data.get('comment', '')
        
        if not comment_text:
            return jsonify({'error': 'Comment cannot be empty'}), 400
        
        church_id = current_user.church_id
        budget = Budget.query.filter_by(id=budget_id, church_id=church_id).first()
        
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        # Add comment via audit log
        audit_log = AuditLog(
            user_id=current_user.id,
            action='BUDGET_REVIEW',
            resource='budget',
            resource_id=budget_id,
            data={'comments': comment_text},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else None
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Comment added',
            'comment': {
                'id': audit_log.id,
                'user': current_user.full_name,
                'text': comment_text,
                'date': audit_log.created_at.isoformat()
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding comment: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ==================== VOTES ENDPOINTS ====================

@committee_bp.route('/votes', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_all_votes():
    """Get all votes for committee"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        church_id = current_user.church_id
        
        # Get pending budgets that need votes
        pending_budgets = Budget.query.filter_by(
            church_id=church_id,
            status='PENDING'
        ).order_by(Budget.submitted_at.desc()).all()
        
        votes_list = []
        for budget in pending_budgets:
            # Check if user has already voted
            has_voted = AuditLog.query.filter_by(
                user_id=current_user.id,
                resource='budget',
                resource_id=budget.id,
                action='CAST_VOTE'
            ).first() is not None
            
            votes_list.append({
                'id': budget.id,
                'title': f"Budget Approval: {budget.name}",
                'description': budget.description,
                'meeting': 'Finance Committee Meeting',
                'date': (datetime.utcnow() + timedelta(days=2)).isoformat(),
                'deadline': (datetime.utcnow() + timedelta(days=1)).isoformat(),
                'status': 'voted' if has_voted else 'open',
                'yesVotes': 0,
                'noVotes': 0,
                'abstain': 0,
                'hasVoted': has_voted,
                'budgetAmount': float(budget.amount)
            })
        
        return jsonify({'votes': votes_list}), 200
        
    except Exception as e:
        logger.error(f"Error getting votes: {str(e)}")
        return jsonify({'votes': []}), 200

@committee_bp.route('/votes/<int:vote_id>/cast', methods=['POST', 'OPTIONS'])
@jwt_required()
def cast_committee_vote(vote_id):
    """Cast a vote on a budget"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        data = request.get_json() or {}
        decision = data.get('decision')
        
        if decision not in ['yes', 'no', 'abstain']:
            return jsonify({'error': 'Invalid decision'}), 400
        
        church_id = current_user.church_id
        budget = Budget.query.filter_by(id=vote_id, church_id=church_id).first()
        
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        # Check if already voted
        existing_vote = AuditLog.query.filter_by(
            user_id=current_user.id,
            resource='budget',
            resource_id=vote_id,
            action='CAST_VOTE'
        ).first()
        
        if existing_vote:
            return jsonify({'error': 'You have already voted on this budget'}), 400
        
        # Cast vote
        audit_log = AuditLog(
            user_id=current_user.id,
            action='CAST_VOTE',
            resource='budget',
            resource_id=vote_id,
            data={'decision': decision},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else None
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': f'Vote cast successfully: {decision}',
            'decision': decision
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error casting vote: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ==================== REPORTS ENDPOINTS ====================

@committee_bp.route('/reports', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_committee_reports():
    """Get financial reports for committee"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        church_id = current_user.church_id
        
        # Get budget summary
        total_budget = db.session.query(func.sum(Budget.amount)).filter_by(
            church_id=church_id,
            status='APPROVED'
        ).scalar() or 0
        
        pending_budget = db.session.query(func.sum(Budget.amount)).filter_by(
            church_id=church_id,
            status='PENDING'
        ).scalar() or 0
        
        reports = {
            'budgetSummary': {
                'totalApproved': float(total_budget),
                'totalPending': float(pending_budget),
                'totalBudgets': Budget.query.filter_by(church_id=church_id).count()
            },
            'financialSummary': {
                'totalIncome': 0,
                'totalExpenses': 0,
                'netPosition': 0
            },
            'departmentBudgets': []
        }
        
        # Get department-wise budget breakdown
        departments = db.session.query(Budget.department).filter(
            Budget.church_id == church_id,
            Budget.department.isnot(None)
        ).distinct().all()
        
        for dept in departments:
            if dept[0]:
                dept_budget = db.session.query(func.sum(Budget.amount)).filter_by(
                    church_id=church_id,
                    department=dept[0],
                    status='APPROVED'
                ).scalar() or 0
                
                reports['departmentBudgets'].append({
                    'department': dept[0],
                    'amount': float(dept_budget)
                })
        
        return jsonify(reports), 200
        
    except Exception as e:
        logger.error(f"Error getting reports: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
@committee_bp.route('/members', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_committee_members():
    """Get all committee members for meeting invitations"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user or not check_role(current_user):
            return jsonify({'error': 'Unauthorized'}), 403
        
        church_id = current_user.church_id
        
        # Get all users with committee roles
        committee_roles = ['finance_committee', 'admin', 'pastor', 'treasurer', 'accountant']
        members = User.query.filter(
            User.church_id == church_id,
            User.role.in_(committee_roles),
            User.is_active == True
        ).all()
        
        members_list = []
        for member in members:
            members_list.append({
                'id': member.id,
                'name': member.full_name,
                'email': member.email,
                'role': member.role,
                'avatar': None
            })
        
        return jsonify({'members': members_list}), 200
        
    except Exception as e:
        logger.error(f"Error getting committee members: {str(e)}")
        return jsonify({'members': []}), 500