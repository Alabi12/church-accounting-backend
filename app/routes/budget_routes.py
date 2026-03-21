from flask import Blueprint, request, jsonify, g, make_response
from datetime import datetime
import logging
import traceback
from app.models import Budget, BudgetCategory, AuditLog, User
from app.extensions import db
from app.routes.auth_routes import token_required
from app.routes.auth_routes import token_required, role_required
from app.socketio_helper import socketio

logger = logging.getLogger(__name__)
budget_bp = Blueprint('budget', __name__)

def can_manage_budgets(user):
    return user.role in ['super_admin', 'admin', 'treasurer', 'finance_committee']

def can_approve_budgets(user):
    return user.role in ['super_admin', 'admin', 'pastor']

# OPTIONS handlers
@budget_bp.route('', methods=['OPTIONS'])
@budget_bp.route('/', methods=['OPTIONS'])
@budget_bp.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path=None):
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With,Accept,Origin')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

# GET all budgets with filters
@budget_bp.route('', methods=['GET'])
@budget_bp.route('/', methods=['GET'])
@token_required
def get_budgets():
    """Get budgets with filters"""
    try:
        church_id = g.current_user.church_id
        status = request.args.get('status')
        fiscal_year = request.args.get('fiscalYear', type=int)
        department = request.args.get('department')
        search = request.args.get('search')
        per_page = request.args.get('perPage', type=int)
        
        logger.info(f"GET budgets - church: {church_id}, fiscal_year: {fiscal_year}, status: {status}, department: {department}")
        
        query = Budget.query.filter_by(church_id=church_id)
        
        if status and status != 'all':
            query = query.filter_by(status=status.upper())
        if fiscal_year:
            query = query.filter_by(fiscal_year=fiscal_year)
        if department and department != 'all':
            query = query.filter_by(department=department.upper())
        if search:
            query = query.filter(
                db.or_(
                    Budget.name.ilike(f'%{search}%'),
                    Budget.description.ilike(f'%{search}%')
                )
            )
        
        # Apply limit if per_page is specified
        if per_page:
            budgets = query.order_by(Budget.fiscal_year.desc(), Budget.created_at.desc()).limit(per_page).all()
        else:
            budgets = query.order_by(Budget.fiscal_year.desc(), Budget.created_at.desc()).all()
        
        logger.info(f"Found {len(budgets)} budgets")
        
        # Calculate stats
        total_budget = sum(b.amount for b in budgets)
        pending = sum(1 for b in budgets if b.status == 'PENDING')
        approved = sum(1 for b in budgets if b.status == 'APPROVED')
        rejected = sum(1 for b in budgets if b.status == 'REJECTED')
        
        # Convert budgets to dict
        budget_list = [budget.to_dict() for budget in budgets]
        
        response = jsonify({
            'budgets': budget_list,
            'stats': {
                'total': len(budgets),
                'pending': pending,
                'approved': approved,
                'rejected': rejected,
                'totalBudget': float(total_budget)
            }
        })
        response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
        return response, 200
        
    except Exception as e:
        logger.error(f"Error getting budgets: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

# POST create new budget
@budget_bp.route('', methods=['POST'])
@budget_bp.route('/', methods=['POST'])
@token_required
def create_budget():
    """Create a new budget"""
    try:
        if not can_manage_budgets(g.current_user):
            return jsonify({'error': 'Permission denied'}), 403
        
        data = request.get_json()
        
        logger.info(f"Creating budget with data: {data}")
        
        # Validate required fields
        required_fields = ['name', 'amount']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        budget = Budget(
            church_id=g.current_user.church_id,
            name=data['name'],
            description=data.get('description'),
            department=data.get('department', 'GENERAL'),
            fiscal_year=data.get('fiscal_year', datetime.utcnow().year),
            amount=float(data['amount']),
            status=data.get('status', 'PENDING')
        )
        
        db.session.add(budget)
        db.session.commit()
        
        logger.info(f"Budget created with ID: {budget.id}")
        
        response = jsonify({
            'message': 'Budget created successfully',
            'budget': budget.to_dict()
        })
        response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
        return response, 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating budget: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

# GET single budget by ID
@budget_bp.route('/<int:budget_id>', methods=['GET'])
@token_required
def get_budget(budget_id):
    """Get a single budget by ID"""
    try:
        budget = Budget.query.get(budget_id)
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        response = jsonify(budget.to_dict())
        response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
        return response, 200
        
    except Exception as e:
        logger.error(f"Error getting budget {budget_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

# PUT update budget
@budget_bp.route('/<int:budget_id>', methods=['PUT'])
@token_required
def update_budget(budget_id):
    """Update a budget"""
    try:
        if not can_manage_budgets(g.current_user):
            return jsonify({'error': 'Permission denied'}), 403
        
        budget = Budget.query.get(budget_id)
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        data = request.get_json()
        
        if 'name' in data:
            budget.name = data['name']
        if 'description' in data:
            budget.description = data['description']
        if 'department' in data:
            budget.department = data['department'].upper()
        if 'amount' in data:
            budget.amount = float(data['amount'])
        if 'status' in data:
            budget.status = data['status']
        
        db.session.commit()
        
        response = jsonify({'message': 'Budget updated successfully', 'budget': budget.to_dict()})
        response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
        return response, 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating budget {budget_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

# DELETE budget
@budget_bp.route('/<int:budget_id>', methods=['DELETE'])
@token_required
def delete_budget(budget_id):
    """Delete a budget"""
    try:
        if not can_manage_budgets(g.current_user):
            return jsonify({'error': 'Permission denied'}), 403
        
        budget = Budget.query.get(budget_id)
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        db.session.delete(budget)
        db.session.commit()
        
        response = jsonify({'message': 'Budget deleted successfully'})
        response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
        return response, 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting budget {budget_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

# POST approve budget
@budget_bp.route('/<int:budget_id>/approve', methods=['POST'])
@token_required
def approve_budget(budget_id):
    """Approve a budget"""
    try:
        if not can_approve_budgets(g.current_user):
            return jsonify({'error': 'Only pastors can approve budgets'}), 403
        
        budget = Budget.query.get(budget_id)
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        if budget.status != 'PENDING':
            return jsonify({'error': f'Cannot approve budget with status: {budget.status}'}), 400
        
        old_status = budget.status
        budget.status = 'APPROVED'
        budget.approved_by = g.current_user.id
        budget.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        logger.info(f"Budget {budget_id} approved by {g.current_user.id}")
        
        # Get approver details
        approver = g.current_user
        approver_name = f"{approver.first_name} {approver.last_name}" if approver.first_name else approver.username
        
        # Emit socket event
        socketio.emit('budget_updated', {
            'budget_id': budget_id,
            'status': 'APPROVED',
            'old_status': old_status,
            'action': 'approve',
            'updated_by': g.current_user.id,
            'updated_by_name': approver_name,
            'timestamp': datetime.utcnow().isoformat(),
            'budget_name': budget.name,
            'department': budget.department
        })
        
        response = jsonify({
            'message': 'Budget approved successfully',
            'status': 'APPROVED',
            'budget': budget.to_dict()
        })
        response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
        return response, 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving budget: {str(e)}")
        return jsonify({'error': str(e)}), 500

# POST reject budget
@budget_bp.route('/<int:budget_id>/reject', methods=['POST'])
@token_required
def reject_budget(budget_id):
    """Reject a budget"""
    try:
        if not can_approve_budgets(g.current_user):
            return jsonify({'error': 'Only pastors can reject budgets'}), 403
        
        data = request.get_json() or {}
        reason = data.get('reason', 'No reason provided')
        
        budget = Budget.query.get(budget_id)
        if not budget:
            return jsonify({'error': 'Budget not found'}), 404
        
        if budget.status != 'PENDING':
            return jsonify({'error': f'Cannot reject budget with status: {budget.status}'}), 400
        
        old_status = budget.status
        budget.status = 'REJECTED'
        budget.rejected_by = g.current_user.id
        budget.rejected_at = datetime.utcnow()
        budget.rejection_reason = reason
        
        db.session.commit()
        
        logger.info(f"Budget {budget_id} rejected by {g.current_user.id}")
        
        # Get rejector details
        rejector = g.current_user
        rejector_name = f"{rejector.first_name} {rejector.last_name}" if rejector.first_name else rejector.username
        
        # Emit socket event
        socketio.emit('budget_updated', {
            'budget_id': budget_id,
            'status': 'REJECTED',
            'old_status': old_status,
            'action': 'reject',
            'reason': reason,
            'updated_by': g.current_user.id,
            'updated_by_name': rejector_name,
            'timestamp': datetime.utcnow().isoformat(),
            'budget_name': budget.name,
            'department': budget.department
        })
        
        response = jsonify({
            'message': 'Budget rejected successfully',
            'status': 'REJECTED',
            'budget_id': budget_id,
            'reason': reason
        })
        response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
        return response, 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting budget: {str(e)}")
        return jsonify({'error': str(e)}), 500