# app/routes/account_routes.py
from flask import Blueprint, request, jsonify, g
from app.models import Account, Church, User
from app.extensions import db
from datetime import datetime
from app.routes.auth_routes import token_required
import traceback
import logging

logger = logging.getLogger(__name__)
account_bp = Blueprint('account', __name__)



# ==================== ACCOUNT MANAGEMENT ====================

@account_bp.route('/accounts', methods=['GET', 'OPTIONS'])
@token_required
def get_accounts():
    """Get all accounts with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = request.args.get('church_id', type=int)
        account_type = request.args.get('type')
        is_active = request.args.get('is_active')
        search = request.args.get('search')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Build query
        query = Account.query
        
        if church_id:
            query = query.filter_by(church_id=church_id)
        elif g.current_user.church_id:
            query = query.filter_by(church_id=g.current_user.church_id)
        
        if account_type:
            query = query.filter_by(type=account_type)
        
        if is_active is not None:
            is_active_bool = is_active.lower() == 'true'
            query = query.filter_by(is_active=is_active_bool)
        
        if search:
            query = query.filter(
                db.or_(
                    Account.name.ilike(f'%{search}%'),
                    Account.account_code.ilike(f'%{search}%'),
                    Account.description.ilike(f'%{search}%')
                )
            )
        
        # Pagination
        paginated = query.order_by(Account.name).paginate(page=page, per_page=per_page, error_out=False)
        
        accounts = []
        for account in paginated.items:
            accounts.append({
                'id': account.id,
                'church_id': account.church_id,
                'account_code': account.account_code,
                'name': account.name,
                'type': account.type,
                'category': account.category,
                'description': account.description,
                'opening_balance': float(account.opening_balance) if account.opening_balance else 0,
                'current_balance': float(account.current_balance) if account.current_balance else 0,
                'is_active': account.is_active,
                'created_at': account.created_at.isoformat() if account.created_at else None
            })
        
        return jsonify({
            'accounts': accounts,
            'total': paginated.total,
            'page': page,
            'per_page': per_page,
            'pages': paginated.pages
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching accounts: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@account_bp.route('/accounts/<int:account_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_account(account_id):
    """Get a single account by ID"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        account = Account.query.get(account_id)
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        
        # Check access
        if account.church_id != g.current_user.church_id and g.current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Access denied'}), 403
        
        return jsonify({
            'id': account.id,
            'church_id': account.church_id,
            'account_code': account.account_code,
            'name': account.name,
            'type': account.type,
            'category': account.category,
            'description': account.description,
            'opening_balance': float(account.opening_balance) if account.opening_balance else 0,
            'current_balance': float(account.current_balance) if account.current_balance else 0,
            'is_active': account.is_active,
            'created_at': account.created_at.isoformat() if account.created_at else None,
            'updated_at': account.updated_at.isoformat() if account.updated_at else None
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching account: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@account_bp.route('/accounts', methods=['POST', 'OPTIONS'])
@token_required
def create_account():
    """Create a new account"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'type']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Generate account code if not provided
        if 'account_code' not in data:
            # Get the last account for this church
            last_account = Account.query.filter_by(
                church_id=data.get('church_id', g.current_user.church_id)
            ).order_by(Account.id.desc()).first()
            
            if last_account and last_account.account_code:
                # Try to extract numeric part from the last account code
                import re
                # Find all numbers in the account code
                numbers = re.findall(r'\d+', last_account.account_code)
                if numbers:
                    # Get the last number found and increment
                    last_num = int(numbers[-1]) + 1
                    # Determine prefix (everything before the number)
                    prefix = re.sub(r'\d+', '', last_account.account_code)
                    if not prefix:
                        prefix = 'ACC'
                else:
                    # If no numbers found, start from 1
                    last_num = 1
                    prefix = 'ACC'
            else:
                # First account for this church
                last_num = 1
                prefix = 'ACC'
            
            # Format with leading zeros
            data['account_code'] = f"{prefix}{last_num:04d}"
        
        account = Account(
            church_id=data.get('church_id', g.current_user.church_id),
            account_code=data['account_code'],
            name=data['name'],
            type=data['type'],
            category=data.get('category'),
            description=data.get('description', ''),
            opening_balance=data.get('opening_balance', 0),
            current_balance=data.get('opening_balance', 0),  # Initial balance equals opening balance
            is_active=data.get('is_active', True)
        )
        
        db.session.add(account)
        db.session.commit()
        
        return jsonify({
            'message': 'Account created successfully',
            'account': {
                'id': account.id,
                'name': account.name,
                'account_code': account.account_code,
                'type': account.type
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating account: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@account_bp.route('/accounts/<int:account_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_account(account_id):
    """Update an account"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        account = Account.query.get(account_id)
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        
        # Check access
        if account.church_id != g.current_user.church_id and g.current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Access denied'}), 403
        
        data = request.get_json()
        
        # Update fields
        if 'name' in data:
            account.name = data['name']
        if 'account_code' in data:
            account.account_code = data['account_code']
        if 'type' in data:
            account.type = data['type']
        if 'category' in data:
            account.category = data['category']
        if 'description' in data:
            account.description = data['description']
        if 'is_active' in data:
            account.is_active = data['is_active']
        
        account.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'message': 'Account updated successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating account: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@account_bp.route('/accounts/<int:account_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_account(account_id):
    """Delete an account"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        account = Account.query.get(account_id)
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        
        # Check access
        if account.church_id != g.current_user.church_id and g.current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Access denied'}), 403
        
        # Check if account has transactions
        if account.transactions and len(account.transactions) > 0:
            # Soft delete - just deactivate
            account.is_active = False
            account.updated_at = datetime.utcnow()
            db.session.commit()
            return jsonify({'message': 'Account deactivated successfully'}), 200
        else:
            # Hard delete if no transactions
            db.session.delete(account)
            db.session.commit()
            return jsonify({'message': 'Account deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting account: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@account_bp.route('/accounts/<int:account_id>/balance', methods=['GET', 'OPTIONS'])
@token_required
def get_account_balance(account_id):
    """Get account balance"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        account = Account.query.get(account_id)
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        
        return jsonify({
            'account_id': account.id,
            'account_name': account.name,
            'opening_balance': float(account.opening_balance) if account.opening_balance else 0,
            'current_balance': float(account.current_balance) if account.current_balance else 0
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching account balance: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@account_bp.route('/accounts/<int:account_id>/transactions', methods=['GET', 'OPTIONS'])
@token_required
def get_account_transactions(account_id):
    """Get transactions for an account"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        from app.models import Transaction
        
        account = Account.query.get(account_id)
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        
        # Get query parameters
        start_date = request.args.get('startDate')
        end_date = request.args.get('endDate')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Build query
        query = Transaction.query.filter_by(account_id=account_id)
        
        if start_date:
            query = query.filter(Transaction.transaction_date >= datetime.fromisoformat(start_date))
        if end_date:
            query = query.filter(Transaction.transaction_date <= datetime.fromisoformat(end_date))
        
        # Pagination
        paginated = query.order_by(Transaction.transaction_date.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        transactions = []
        for t in paginated.items:
            transactions.append({
                'id': t.id,
                'date': t.transaction_date.isoformat() if t.transaction_date else None,
                'description': t.description,
                'amount': float(t.amount),
                'type': t.transaction_type,
                'status': t.status,
                'reference': t.reference_number
            })
        
        return jsonify({
            'transactions': transactions,
            'total': paginated.total,
            'page': page,
            'per_page': per_page,
            'pages': paginated.pages
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching account transactions: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@account_bp.route('/accounts/types', methods=['GET', 'OPTIONS'])
@token_required
def get_account_types():
    """Get all account types"""
    if request.method == 'OPTIONS':
        return '', 200
    
    account_types = [
        {'id': 'asset', 'name': 'Asset'},
        {'id': 'liability', 'name': 'Liability'},
        {'id': 'equity', 'name': 'Equity'},
        {'id': 'income', 'name': 'Income'},
        {'id': 'expense', 'name': 'Expense'},
        {'id': 'bank', 'name': 'Bank'},
        {'id': 'cash', 'name': 'Cash'}
    ]
    
    return jsonify(account_types), 200