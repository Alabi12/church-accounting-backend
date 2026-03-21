# app/routes/leave_routes.py
from flask import Blueprint, request, jsonify, g, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import Employee, LeaveBalance, LeaveRequest, User, AuditLog, Church
from app.extensions import db
from datetime import datetime, timedelta
import logging
import traceback

logger = logging.getLogger(__name__)
leave_bp = Blueprint('leave', __name__)


# ==================== HELPER FUNCTIONS ====================

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
    """
    Ensure we have a valid church_id.
    Returns church_id or raises appropriate error.
    """
    try:
        # Case 1: User object provided
        if user and hasattr(user, 'church_id') and user.church_id:
            return user.church_id
        
        # Case 2: Try to get current user from context
        current_user = get_current_user()
        if current_user and current_user.church_id:
            return current_user.church_id
        
        # Case 3: Try to get default church
        default_church = Church.query.first()
        if default_church:
            # If we have a user but no church_id, assign default
            if current_user and not current_user.church_id:
                current_user.church_id = default_church.id
                db.session.add(current_user)
                db.session.commit()
                logger.info(f"Assigned default church {default_church.id} to user {current_user.id}")
            return default_church.id
        
        # Case 4: For development, return a fallback
        if current_app.debug:
            logger.warning("Using fallback church_id=1 for development")
            return 1
            
        raise ValueError("No church found in database")
        
    except Exception as e:
        logger.error(f"Error in ensure_user_church: {str(e)}")
        if current_app.debug:
            return 1  # Fallback for development
        raise


# ==================== LEAVE BALANCES ====================

@leave_bp.route('/balances', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_leave_balances():
    """Get all leave balances"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church()
        
        # Build query
        query = LeaveBalance.query.join(Employee).filter(
            Employee.church_id == church_id
        )
        
        # Filters
        employee_id = request.args.get('employee_id', type=int)
        if employee_id:
            query = query.filter(LeaveBalance.employee_id == employee_id)
        
        year = request.args.get('year', datetime.now().year, type=int)
        if year:
            query = query.filter(LeaveBalance.year == year)
        
        leave_type = request.args.get('leave_type')
        if leave_type:
            query = query.filter(LeaveBalance.leave_type == leave_type)
        
        balances = query.all()
        
        # Enhance with employee names
        result = []
        for b in balances:
            b_dict = b.to_dict()
            if b.employee:
                b_dict['employee_name'] = b.employee.full_name()
            result.append(b_dict)
        
        return jsonify({
            'balances': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching leave balances: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/balances/initialize', methods=['POST', 'OPTIONS'])
@jwt_required()
def initialize_leave_balances():
    """Initialize leave balances for a new year"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church()
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
            
        data = request.get_json() or {}
        year = data.get('year', datetime.now().year)
        
        # Get all active employees
        employees = Employee.query.filter_by(
            church_id=church_id,
            status='active'
        ).all()
        
        created = []
        existing = []
        
        leave_types = [
            {'type': 'annual', 'entitlement': 20},  # 20 days annual leave
            {'type': 'sick', 'entitlement': 15},    # 15 days sick leave
            {'type': 'bereavement', 'entitlement': 5},  # 5 days bereavement
            {'type': 'maternity', 'entitlement': 90},   # 90 days maternity
            {'type': 'paternity', 'entitlement': 5},    # 5 days paternity
            {'type': 'study', 'entitlement': 10},       # 10 days study leave
        ]
        
        for employee in employees:
            for lt in leave_types:
                # Check if balance exists
                existing_balance = LeaveBalance.query.filter_by(
                    employee_id=employee.id,
                    leave_type=lt['type'],
                    year=year
                ).first()
                
                if existing_balance:
                    existing.append({
                        'employee_id': employee.id,
                        'employee_name': employee.full_name(),
                        'leave_type': lt['type'],
                        'year': year
                    })
                    continue
                
                # Create new balance
                balance = LeaveBalance(
                    employee_id=employee.id,
                    leave_type=lt['type'],
                    year=year,
                    annual_entitlement=lt['entitlement'],
                    used=0,
                    remaining=lt['entitlement']
                )
                
                db.session.add(balance)
                created.append({
                    'employee_id': employee.id,
                    'employee_name': employee.full_name(),
                    'leave_type': lt['type'],
                    'year': year
                })
        
        db.session.commit()
        
        return jsonify({
            'message': f'Created {len(created)} balances, {len(existing)} already existed',
            'created': created,
            'existing': existing
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error initializing leave balances: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== LEAVE REQUESTS ====================

@leave_bp.route('/requests', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_leave_requests():
    """Get all leave requests"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church()
        
        # Build query
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
        
        from_date = request.args.get('from_date')
        if from_date:
            from_date = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
            query = query.filter(LeaveRequest.start_date >= from_date)
        
        to_date = request.args.get('to_date')
        if to_date:
            to_date = datetime.fromisoformat(to_date.replace('Z', '+00:00'))
            query = query.filter(LeaveRequest.end_date <= to_date)
        
        requests = query.order_by(LeaveRequest.created_at.desc()).all()
        
        result = []
        for r in requests:
            r_dict = r.to_dict()
            if r.employee:
                r_dict['employee_name'] = r.employee.full_name()
                r_dict['employee'] = {
                    'id': r.employee.id,
                    'name': r.employee.full_name(),
                    'department': r.employee.department
                }
            result.append(r_dict)
        
        return jsonify({
            'requests': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching leave requests: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests', methods=['POST', 'OPTIONS'])
@jwt_required()
def create_leave_request():
    """Create a new leave request"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
            
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
        
        # Check leave balance
        balance = LeaveBalance.query.filter_by(
            employee_id=data['employee_id'],
            leave_type=data['leave_type'],
            year=start_date.year
        ).first()
        
        if not balance:
            return jsonify({'error': 'Leave balance not found for this employee'}), 404
        
        if balance.remaining < days_requested:
            return jsonify({
                'error': 'Insufficient leave balance',
                'available': balance.remaining,
                'requested': days_requested
            }), 400
        
        # Create request
        leave_request = LeaveRequest(
            employee_id=data['employee_id'],
            leave_type=data['leave_type'],
            start_date=start_date,
            end_date=end_date,
            days_requested=days_requested,
            reason=data.get('reason'),
            status='pending'
        )
        
        db.session.add(leave_request)
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
            'message': 'Leave request submitted successfully',
            'request': leave_request.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating leave request: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_leave_request(request_id):
    """Get a specific leave request"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church()
        
        leave_request = LeaveRequest.query.join(Employee).filter(
            LeaveRequest.id == request_id,
            Employee.church_id == church_id
        ).first()
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        result = leave_request.to_dict()
        if leave_request.employee:
            result['employee_name'] = leave_request.employee.full_name()
            result['employee'] = {
                'id': leave_request.employee.id,
                'name': leave_request.employee.full_name(),
                'department': leave_request.employee.department
            }
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error fetching leave request: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>/approve', methods=['POST', 'OPTIONS'])
@jwt_required()
def approve_leave_request(request_id):
    """Approve a leave request"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
        
        # Check if user is admin or pastor
        if not current_user.is_admin and current_user.role not in ['pastor', 'treasurer']:
            return jsonify({'error': 'Unauthorized to approve leave requests'}), 403
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if leave_request.status != 'pending':
            return jsonify({'error': f'Request is already {leave_request.status}'}), 400
        
        # Update leave balance
        balance = LeaveBalance.query.filter_by(
            employee_id=leave_request.employee_id,
            leave_type=leave_request.leave_type,
            year=leave_request.start_date.year
        ).first()
        
        if not balance:
            return jsonify({'error': 'Leave balance not found'}), 404
        
        if balance.remaining < leave_request.days_requested:
            return jsonify({'error': 'Insufficient leave balance'}), 400
        
        # Update balance
        balance.used += leave_request.days_requested
        balance.remaining -= leave_request.days_requested
        
        # Update request
        leave_request.status = 'approved'
        leave_request.approved_by = current_user.id
        leave_request.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Leave request approved',
            'request': leave_request.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving leave request: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@leave_bp.route('/requests/<int:request_id>/reject', methods=['POST', 'OPTIONS'])
@jwt_required()
def reject_leave_request(request_id):
    """Reject a leave request"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
        
        # Check if user is admin or pastor
        if not current_user.is_admin and current_user.role not in ['pastor', 'treasurer']:
            return jsonify({'error': 'Unauthorized to reject leave requests'}), 403
        
        leave_request = LeaveRequest.query.get(request_id)
        
        if not leave_request:
            return jsonify({'error': 'Leave request not found'}), 404
        
        if leave_request.status != 'pending':
            return jsonify({'error': f'Request is already {leave_request.status}'}), 400
        
        data = request.get_json() or {}
        reason = data.get('reason', 'No reason provided')
        
        leave_request.status = 'rejected'
        leave_request.rejection_reason = reason
        leave_request.approved_by = current_user.id
        leave_request.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Leave request rejected',
            'reason': reason
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting leave request: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== LEAVE CALENDAR ====================

@leave_bp.route('/calendar', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_leave_calendar():
    """Get leave calendar for visualization"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church()
        year = request.args.get('year', datetime.now().year, type=int)
        month = request.args.get('month', type=int)
        
        query = LeaveRequest.query.join(Employee).filter(
            Employee.church_id == church_id,
            LeaveRequest.status == 'approved'
        )
        
        if month:
            start_date = datetime(year, month, 1).date()
            if month == 12:
                end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
            else:
                end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
            
            query = query.filter(
                LeaveRequest.start_date <= end_date,
                LeaveRequest.end_date >= start_date
            )
        else:
            start_date = datetime(year, 1, 1).date()
            end_date = datetime(year, 12, 31).date()
            query = query.filter(
                LeaveRequest.start_date <= end_date,
                LeaveRequest.end_date >= start_date
            )
        
        requests = query.all()
        
        # Format for calendar display
        events = []
        for req in requests:
            events.append({
                'id': req.id,
                'title': f"{req.employee.full_name()} - {req.leave_type}",
                'start': req.start_date.isoformat(),
                'end': (req.end_date + timedelta(days=1)).isoformat(),  # FullCalendar needs end date exclusive
                'color': get_leave_color(req.leave_type),
                'extendedProps': {
                    'employee_id': req.employee_id,
                    'employee_name': req.employee.full_name(),
                    'leave_type': req.leave_type,
                    'days': req.days_requested,
                    'status': req.status
                }
            })
        
        return jsonify(events), 200
        
    except Exception as e:
        logger.error(f"Error getting leave calendar: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def get_leave_color(leave_type):
    """Get color for leave type in calendar"""
    colors = {
        'annual': '#3498db',  # Blue
        'sick': '#e74c3c',    # Red
        'bereavement': '#95a5a6',  # Gray
        'maternity': '#9b59b6',    # Purple
        'paternity': '#3498db',    # Blue
        'study': '#f39c12',        # Orange
        'unpaid': '#2c3e50'        # Dark blue
    }
    return colors.get(leave_type, '#3498db')