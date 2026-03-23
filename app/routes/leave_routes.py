# app/routes/leave_routes.py
from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import LeaveRequest, LeaveBalance, LeaveType, Employee, User, AuditLog
from app.extensions import db
from datetime import datetime, timedelta
from decimal import Decimal
import traceback
import logging

logger = logging.getLogger(__name__)
leave_bp = Blueprint('leave', __name__)

from app.routes.auth_routes import token_required

def get_current_user():
    try:
        user_id = get_jwt_identity()
        if user_id:
            return User.query.get(int(user_id))
    except Exception as e:
        logger.warning(f"Error getting user from JWT: {e}")
    return None


# ==================== LEAVE REQUESTS ====================

@leave_bp.route('/requests', methods=['GET', 'OPTIONS'])
@token_required
def get_leave_requests():
    """Get leave requests with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        status = request.args.get('status')
        employee_id = request.args.get('employee_id')
        
        query = LeaveRequest.query.join(Employee).filter(Employee.church_id == church_id)
        
        if status and status != 'all':
            query = query.filter_by(status=status)
        if employee_id:
            query = query.filter_by(employee_id=employee_id)
        
        requests = query.order_by(LeaveRequest.created_at.desc()).all()
        
        return jsonify({
            'requests': [req.to_dict() for req in requests],
            'total': len(requests)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting leave requests: {str(e)}")
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests', methods=['POST', 'OPTIONS'])
@token_required
def create_leave_request():
    """Create a new leave request (Employee)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        data = request.get_json()
        
        # Get employee record for current user
        employee = Employee.query.filter_by(
            user_id=current_user.id,
            church_id=g.current_user.church_id
        ).first()
        
        if not employee:
            return jsonify({'error': 'Employee record not found'}), 404
        
        # Calculate days
        start_date = datetime.fromisoformat(data['start_date']).date()
        end_date = datetime.fromisoformat(data['end_date']).date()
        days = (end_date - start_date).days + 1
        
        # Check leave balance
        leave_type = LeaveType.query.get(data['leave_type_id'])
        balance = LeaveBalance.query.filter_by(
            employee_id=employee.id,
            leave_type_id=data['leave_type_id'],
            year=start_date.year
        ).first()
        
        if balance and days > balance.remaining_days:
            return jsonify({'error': f'Insufficient leave balance. Available: {balance.remaining_days} days'}), 400
        
        leave_request = LeaveRequest(
            employee_id=employee.id,
            leave_type_id=data['leave_type_id'],
            start_date=start_date,
            end_date=end_date,
            days_requested=days,
            reason=data['reason'],
            status='PENDING'
        )
        
        db.session.add(leave_request)
        db.session.commit()
        
        return jsonify({
            'message': 'Leave request submitted',
            'request': leave_request.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating leave request: {str(e)}")
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>/review', methods=['POST', 'OPTIONS'])
@token_required
def review_leave_request(request_id):
    """Admin reviews leave request"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Only admin can review leave requests'}), 403
        
        data = request.get_json()
        
        leave_request = LeaveRequest.query.get(request_id)
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if not leave_request.can_review():
            return jsonify({'error': f'Cannot review request with status {leave_request.status}'}), 400
        
        leave_request.status = 'REVIEWED'
        leave_request.reviewed_by = current_user.id
        leave_request.reviewed_at = datetime.utcnow()
        leave_request.review_comments = data.get('comments')
        
        db.session.commit()
        
        return jsonify({
            'message': 'Leave request reviewed',
            'request': leave_request.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error reviewing leave: {str(e)}")
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>/recommend', methods=['POST', 'OPTIONS'])
@token_required
def recommend_leave_request(request_id):
    """Admin recommends leave request to pastor"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Only admin can recommend leave requests'}), 403
        
        data = request.get_json()
        recommendation = data.get('recommendation', 'RECOMMEND')  # RECOMMEND or NOT_RECOMMEND
        
        leave_request = LeaveRequest.query.get(request_id)
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if not leave_request.can_recommend():
            return jsonify({'error': f'Cannot recommend request with status {leave_request.status}'}), 400
        
        if recommendation == 'RECOMMEND':
            leave_request.status = 'RECOMMENDED'
        else:
            leave_request.status = 'REJECTED'
            leave_request.rejected_by = current_user.id
            leave_request.rejected_at = datetime.utcnow()
            leave_request.rejection_reason = data.get('reason', 'Not recommended by admin')
        
        leave_request.recommended_by = current_user.id
        leave_request.recommended_at = datetime.utcnow()
        leave_request.recommendation = recommendation
        leave_request.recommendation_comments = data.get('comments')
        
        db.session.commit()
        
        return jsonify({
            'message': 'Leave request ' + ('recommended' if recommendation == 'RECOMMEND' else 'rejected'),
            'request': leave_request.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error recommending leave: {str(e)}")
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_leave_request(request_id):
    """Pastor approves leave request"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin', 'pastor']:
            return jsonify({'error': 'Only pastor can approve leave requests'}), 403
        
        data = request.get_json()
        
        leave_request = LeaveRequest.query.get(request_id)
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if not leave_request.can_approve():
            return jsonify({'error': f'Cannot approve request with status {leave_request.status}'}), 400
        
        leave_request.status = 'APPROVED'
        leave_request.approved_by = current_user.id
        leave_request.approved_at = datetime.utcnow()
        leave_request.approval_comments = data.get('comments')
        
        # Update leave balance
        balance = LeaveBalance.query.filter_by(
            employee_id=leave_request.employee_id,
            leave_type_id=leave_request.leave_type_id,
            year=leave_request.start_date.year
        ).first()
        
        if balance:
            balance.used_days += leave_request.days_requested
            balance.remaining_days = balance.total_days - balance.used_days
            balance.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Leave request approved',
            'request': leave_request.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving leave: {str(e)}")
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>/return', methods=['POST', 'OPTIONS'])
@token_required
def return_leave_request(request_id):
    """Return leave request for corrections"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        data = request.get_json()
        reason = data.get('reason', 'No reason provided')
        
        leave_request = LeaveRequest.query.get(request_id)
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        leave_request.status = 'RETURNED'
        leave_request.returned_by = current_user.id
        leave_request.returned_at = datetime.utcnow()
        leave_request.return_reason = reason
        
        db.session.commit()
        
        return jsonify({
            'message': 'Leave request returned for corrections',
            'request': leave_request.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error returning leave: {str(e)}")
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>/process-allowance', methods=['POST', 'OPTIONS'])
@token_required
def process_leave_allowance(request_id):
    """Process leave allowance payment (Accountant)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin', 'accountant']:
            return jsonify({'error': 'Only accountant can process leave allowances'}), 403
        
        data = request.get_json()
        
        leave_request = LeaveRequest.query.get(request_id)
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if not leave_request.can_process_allowance():
            return jsonify({'error': 'Leave request cannot be processed for allowance'}), 400
        
        # Calculate allowance (e.g., daily rate * days)
        employee = Employee.query.get(leave_request.employee_id)
        daily_rate = employee.basic_salary / 30 if employee.basic_salary else 0
        allowance_amount = daily_rate * leave_request.days_requested
        
        leave_request.allowance_processed = True
        leave_request.allowance_processed_at = datetime.utcnow()
        leave_request.allowance_amount = Decimal(str(allowance_amount))
        
        # Link to payroll for payment processing
        if data.get('payroll_run_id'):
            leave_request.payroll_run_id = data['payroll_run_id']
        
        db.session.commit()
        
        return jsonify({
            'message': 'Leave allowance processed',
            'request': leave_request.to_dict(),
            'allowance_amount': float(allowance_amount)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing leave allowance: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==================== LEAVE TYPES AND BALANCES ====================

@leave_bp.route('/types', methods=['GET', 'OPTIONS'])
@token_required
def get_leave_types():
    """Get all leave types"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        types = LeaveType.query.filter_by(is_active=True).all()
        return jsonify({
            'types': [t.to_dict() for t in types]
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting leave types: {str(e)}")
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/balances', methods=['GET', 'OPTIONS'])
@token_required
def get_leave_balances():
    """Get leave balances for current employee"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        employee = Employee.query.filter_by(
            user_id=current_user.id,
            church_id=g.current_user.church_id
        ).first()
        
        if not employee:
            return jsonify({'error': 'Employee record not found'}), 404
        
        balances = LeaveBalance.query.filter_by(
            employee_id=employee.id
        ).all()
        
        return jsonify({
            'balances': [b.to_dict() for b in balances]
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting leave balances: {str(e)}")
        return jsonify({'error': str(e)}), 500