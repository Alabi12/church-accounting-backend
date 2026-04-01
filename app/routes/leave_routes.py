# app/routes/leave_routes.py
from flask import Blueprint, request, jsonify, g, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import Employee, LeaveBalance, LeaveRequest, LeaveType, User, AuditLog, Church, JournalEntry, JournalLine
from app.extensions import db
from datetime import datetime, timedelta
import logging
import traceback

logger = logging.getLogger(__name__)
leave_bp = Blueprint('leave', __name__)


def get_current_user():
    """Get current user from JWT token or g"""
    if hasattr(g, 'current_user') and g.current_user:
        return g.current_user
    
    try:
        user_id = get_jwt_identity()
        if user_id:
            user = User.query.get(int(user_id))
            if user:
                g.current_user = user
                return user
    except Exception as e:
        logger.warning(f"Error getting user from JWT: {e}")
    
    return None


def ensure_user_church(user=None):
    """Ensure we have a valid church_id."""
    try:
        if user and hasattr(user, 'church_id') and user.church_id:
            return user.church_id
        
        current_user = get_current_user()
        if current_user and current_user.church_id:
            return current_user.church_id
        
        default_church = Church.query.first()
        if default_church:
            if current_user and not current_user.church_id:
                current_user.church_id = default_church.id
                db.session.add(current_user)
                db.session.commit()
            return default_church.id
        
        if current_app.debug:
            return 1
            
        raise ValueError("No church found in database")
        
    except Exception as e:
        logger.error(f"Error in ensure_user_church: {str(e)}")
        if current_app.debug:
            return 1
        raise


# ==================== LEAVE REQUESTS WITH WORKFLOW ====================

@leave_bp.route('/requests', methods=['GET'])
@jwt_required()
def get_leave_requests():
    """Get all leave requests with filters"""
    try:
        church_id = ensure_user_church()
        current_user = get_current_user()
        
        query = LeaveRequest.query.join(Employee).filter(
            Employee.church_id == church_id
        )
        
        # Filters
        status = request.args.get('status')
        if status and status != 'all':
            query = query.filter(LeaveRequest.status == status)
        
        employee_id = request.args.get('employee_id', type=int)
        if employee_id:
            query = query.filter(LeaveRequest.employee_id == employee_id)
        
        # Filter by stage for specific roles
        stage = request.args.get('stage')
        if stage == 'pending_admin':
            query = query.filter(LeaveRequest.status == 'PENDING_ADMIN')
        elif stage == 'pending_pastor':
            query = query.filter(LeaveRequest.status == 'PENDING_PASTOR')
        elif stage == 'pending_allowance':
            query = query.filter(
                LeaveRequest.status == 'APPROVED',
                LeaveRequest.allowance_processed == False
            )
        elif stage == 'pending_treasurer':
            query = query.filter(
                LeaveRequest.allowance_processed == True,
                LeaveRequest.allowance_approved == False,
                LeaveRequest.status == 'APPROVED'
            )
        elif stage == 'pending_payment':
            query = query.filter(
                LeaveRequest.allowance_approved == True,
                LeaveRequest.posted_to_ledger == False
            )
        
        requests = query.order_by(LeaveRequest.created_at.desc()).all()
        
        result = []
        for r in requests:
            r_dict = r.to_dict()
            if r.employee:
                r_dict['employee'] = {
                    'id': r.employee.id,
                    'name': r.employee.full_name(),
                    'department': r.employee.department,
                    'position': r.employee.position
                }
            result.append(r_dict)
        
        return jsonify({
            'requests': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching leave requests: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests', methods=['POST'])
@jwt_required()
def create_leave_request():
    """Create a new leave request (Admin enters data from printed form)"""
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
        
        # Check if user is admin or has permission
        allowed_roles = ['super_admin', 'admin', 'hr']
        if current_user.role not in allowed_roles:
            return jsonify({'error': 'Unauthorized to create leave requests. Only HR/Admin can create requests.'}), 403
        
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['employee_id', 'leave_type', 'start_date', 'end_date']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Parse dates
        start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00')).date()
        end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00')).date()
        
        # Calculate days
        days_requested = (end_date - start_date).days + 1
        
        if days_requested <= 0:
            return jsonify({'error': 'End date must be after start date'}), 400
        
        # Get leave type
        leave_type = LeaveType.query.filter_by(code=data['leave_type']).first()
        if not leave_type:
            return jsonify({'error': 'Invalid leave type'}), 400
        
        # Check leave balance if it's a paid leave
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
        
        # Create request with PENDING_ADMIN status (admin entered, pending pastor)
        leave_request = LeaveRequest(
            employee_id=data['employee_id'],
            leave_type_id=leave_type.id,
            start_date=start_date,
            end_date=end_date,
            days_requested=days_requested,
            reason=data.get('reason', ''),
            status='PENDING_PASTOR',  # After admin enters, goes to pastor
            admin_id=current_user.id,
            admin_at=datetime.utcnow(),
            admin_comments=data.get('admin_comments', '')
        )
        
        db.session.add(leave_request)
        
        # Calculate allowance amount if applicable
        if leave_type.is_paid and leave_type.allowance_rate > 0:
            # Get employee's daily rate
            employee = Employee.query.get(data['employee_id'])
            if employee and employee.salary:
                daily_rate = employee.salary / 30  # Approximate daily rate
                if leave_type.allowance_type == 'percentage':
                    leave_request.allowance_amount = daily_rate * days_requested * (leave_type.allowance_rate / 100)
                else:
                    leave_request.allowance_amount = leave_type.allowance_rate * days_requested
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=current_user.id,
            action='CREATE_LEAVE_REQUEST',
            resource='leave_request',
            resource_id=leave_request.id,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Leave request submitted successfully and sent to Pastor for approval',
            'request': leave_request.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating leave request: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>/pastor-approve', methods=['POST'])
@jwt_required()
def pastor_approve_leave_request(request_id):
    """Pastor approves leave request"""
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
        
        # Check if user is pastor
        if current_user.role not in ['super_admin', 'admin', 'pastor']:
            return jsonify({'error': 'Unauthorized. Only Pastors can approve leave requests.'}), 403
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if leave_request.status != 'PENDING_PASTOR':
            return jsonify({'error': f'Request is already at stage: {leave_request.status}'}), 400
        
        data = request.get_json() or {}
        
        # Update status to APPROVED
        leave_request.status = 'APPROVED'
        leave_request.pastor_id = current_user.id
        leave_request.pastor_at = datetime.utcnow()
        leave_request.pastor_comments = data.get('comments', '')
        
        # Update leave balance if it's a paid leave
        if leave_request.leave_type.is_paid:
            balance = LeaveBalance.query.filter_by(
                employee_id=leave_request.employee_id,
                leave_type_id=leave_request.leave_type_id,
                year=leave_request.start_date.year
            ).first()
            
            if balance:
                balance.used_days += leave_request.days_requested
                balance.remaining_days -= leave_request.days_requested
        
        db.session.commit()
        
        return jsonify({
            'message': 'Leave request approved by Pastor',
            'request': leave_request.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving leave request: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>/process-allowance', methods=['POST'])
@jwt_required()
def process_leave_allowance(request_id):
    """Accountant processes leave allowance"""
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
        
        # Check if user is accountant
        if current_user.role not in ['super_admin', 'admin', 'accountant']:
            return jsonify({'error': 'Unauthorized. Only Accountants can process leave allowances.'}), 403
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if leave_request.status != 'APPROVED':
            return jsonify({'error': f'Request must be approved first. Current status: {leave_request.status}'}), 400
        
        if leave_request.allowance_processed:
            return jsonify({'error': 'Allowance already processed'}), 400
        
        data = request.get_json() or {}
        
        # Update allowance
        leave_request.allowance_processed = True
        leave_request.allowance_processed_at = datetime.utcnow()
        leave_request.accountant_id = current_user.id
        leave_request.accountant_comments = data.get('comments', '')
        
        # Override allowance amount if provided
        if data.get('allowance_amount'):
            leave_request.allowance_amount = data['allowance_amount']
        
        db.session.commit()
        
        return jsonify({
            'message': 'Leave allowance processed and sent to Treasurer for approval',
            'request': leave_request.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing leave allowance: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>/treasurer-approve', methods=['POST'])
@jwt_required()
def treasurer_approve_allowance(request_id):
    """Treasurer approves leave allowance payment"""
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
        
        # Check if user is treasurer
        if current_user.role not in ['super_admin', 'admin', 'treasurer']:
            return jsonify({'error': 'Unauthorized. Only Treasurers can approve leave allowances.'}), 403
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if not leave_request.allowance_processed:
            return jsonify({'error': 'Allowance not yet processed by Accountant'}), 400
        
        if leave_request.allowance_approved:
            return jsonify({'error': 'Allowance already approved'}), 400
        
        data = request.get_json() or {}
        
        # Update allowance approval
        leave_request.allowance_approved = True
        leave_request.allowance_approved_at = datetime.utcnow()
        leave_request.treasurer_id = current_user.id
        leave_request.treasurer_comments = data.get('comments', '')
        
        db.session.commit()
        
        return jsonify({
            'message': 'Leave allowance approved by Treasurer',
            'request': leave_request.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving leave allowance: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>/post-to-ledger', methods=['POST'])
@jwt_required()
def post_leave_payment_to_ledger(request_id):
    """Accountant posts leave payment to ledger"""
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
        
        # Check if user is accountant
        if current_user.role not in ['super_admin', 'admin', 'accountant']:
            return jsonify({'error': 'Unauthorized. Only Accountants can post to ledger.'}), 403
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if not leave_request.allowance_approved:
            return jsonify({'error': 'Allowance not yet approved by Treasurer'}), 400
        
        if leave_request.posted_to_ledger:
            return jsonify({'error': 'Already posted to ledger'}), 400
        
        data = request.get_json() or {}
        
        # Create journal entry for leave payment
        journal_entry = JournalEntry(
            date=datetime.utcnow().date(),
            description=f"Leave payment for {leave_request.employee.full_name()} - {leave_request.leave_type.name} ({leave_request.start_date} to {leave_request.end_date})",
            reference=f"LEAVE-{leave_request.id}",
            entry_type='payment',
            status='posted',
            created_by=current_user.id,
            church_id=ensure_user_church()
        )
        db.session.add(journal_entry)
        db.session.flush()
        
        # Debit: Leave Expense Account (Expense)
        debit_line = JournalLine(
            journal_entry_id=journal_entry.id,
            account_code='LEAVE_EXPENSE',
            account_name='Leave Allowance Expense',
            debit=float(leave_request.allowance_amount),
            credit=0,
            description=f"Leave allowance for {leave_request.employee.full_name()}"
        )
        db.session.add(debit_line)
        
        # Credit: Bank/Cash Account
        credit_line = JournalLine(
            journal_entry_id=journal_entry.id,
            account_code='BANK',
            account_name='Bank Account',
            debit=0,
            credit=float(leave_request.allowance_amount),
            description=f"Payment of leave allowance to {leave_request.employee.full_name()}"
        )
        db.session.add(credit_line)
        
        # Update leave request
        leave_request.posted_to_ledger = True
        leave_request.posted_at = datetime.utcnow()
        leave_request.posted_by = current_user.id
        leave_request.journal_entry_id = journal_entry.id
        leave_request.status = 'PAID'
        
        db.session.commit()
        
        return jsonify({
            'message': 'Leave payment posted to ledger successfully',
            'journal_entry_id': journal_entry.id,
            'request': leave_request.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error posting to ledger: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>/reject', methods=['POST'])
@jwt_required()
def reject_leave_request(request_id):
    """Reject leave request at any stage"""
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        data = request.get_json() or {}
        reason = data.get('reason', 'No reason provided')
        
        # Determine who is rejecting
        if current_user.role in ['pastor', 'super_admin', 'admin'] and leave_request.status == 'PENDING_PASTOR':
            leave_request.status = 'REJECTED'
            leave_request.rejected_by = current_user.id
            leave_request.rejected_at = datetime.utcnow()
            leave_request.rejection_reason = reason
            leave_request.rejection_stage = 'pastor'
        elif current_user.role in ['treasurer', 'super_admin', 'admin'] and leave_request.allowance_processed and not leave_request.allowance_approved:
            leave_request.allowance_approved = False
            leave_request.rejected_by = current_user.id
            leave_request.rejected_at = datetime.utcnow()
            leave_request.rejection_reason = reason
            leave_request.rejection_stage = 'treasurer'
            leave_request.status = 'REJECTED'
        else:
            return jsonify({'error': 'Cannot reject at this stage'}), 400
        
        db.session.commit()
        
        return jsonify({
            'message': f'Leave request rejected by {current_user.role}',
            'reason': reason
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting leave request: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== LEAVE WORKFLOW SUMMARY ====================

@leave_bp.route('/workflow-summary', methods=['GET'])
@jwt_required()
def get_workflow_summary():
    """Get summary of leave requests by workflow stage"""
    try:
        church_id = ensure_user_church()
        
        summary = {
            'pending_pastor': LeaveRequest.query.join(Employee).filter(
                Employee.church_id == church_id,
                LeaveRequest.status == 'PENDING_PASTOR'
            ).count(),
            'approved_pending_allowance': LeaveRequest.query.join(Employee).filter(
                Employee.church_id == church_id,
                LeaveRequest.status == 'APPROVED',
                LeaveRequest.allowance_processed == False
            ).count(),
            'allowance_processed_pending_treasurer': LeaveRequest.query.join(Employee).filter(
                Employee.church_id == church_id,
                LeaveRequest.allowance_processed == True,
                LeaveRequest.allowance_approved == False,
                LeaveRequest.status == 'APPROVED'
            ).count(),
            'approved_pending_payment': LeaveRequest.query.join(Employee).filter(
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
        return jsonify({'error': str(e)}), 500


# ==================== LEAVE BALANCES ====================

@leave_bp.route('/balances', methods=['GET'])
@jwt_required()
def get_leave_balances():
    """Get all leave balances"""
    try:
        church_id = ensure_user_church()
        
        query = LeaveBalance.query.join(Employee).filter(
            Employee.church_id == church_id
        )
        
        employee_id = request.args.get('employee_id', type=int)
        if employee_id:
            query = query.filter(LeaveBalance.employee_id == employee_id)
        
        year = request.args.get('year', datetime.now().year, type=int)
        if year:
            query = query.filter(LeaveBalance.year == year)
        
        leave_type = request.args.get('leave_type')
        if leave_type:
            leave_type_obj = LeaveType.query.filter_by(code=leave_type).first()
            if leave_type_obj:
                query = query.filter(LeaveBalance.leave_type_id == leave_type_obj.id)
        
        balances = query.all()
        
        result = [b.to_dict() for b in balances]
        
        return jsonify({'balances': result}), 200
        
    except Exception as e:
        logger.error(f"Error fetching leave balances: {str(e)}")
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/types', methods=['GET'])
@jwt_required()
def get_leave_types():
    """Get all leave types"""
    try:
        leave_types = LeaveType.query.filter_by(is_active=True).all()
        return jsonify({'leave_types': [lt.to_dict() for lt in leave_types]}), 200
    except Exception as e:
        logger.error(f"Error fetching leave types: {str(e)}")
        return jsonify({'error': str(e)}), 500