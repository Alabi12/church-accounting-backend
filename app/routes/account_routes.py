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
        account_type = request.args.get('type')  # This is for bank/cash from frontend
        account_category = request.args.get('account_type')  # This is for ASSET/REVENUE, etc.
        is_active = request.args.get('is_active')
        search = request.args.get('search')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Build query
        query = Account.query
        
        # Filter by church
        if church_id:
            query = query.filter_by(church_id=church_id)
        elif g.current_user and g.current_user.church_id:
            query = query.filter_by(church_id=g.current_user.church_id)
        
        # Filter by account category (ASSET, REVENUE, etc.)
        if account_category:
            query = query.filter_by(account_type=account_category.upper())
        
        # Handle frontend 'type' parameter (bank/cash/petty_cash)
        # IMPORTANT: Do NOT use filter_by(type=account_type) because your model has account_type, not type
        if account_type:
            if account_type == 'bank':
                # Get bank accounts (ASSET type with 'Bank' category or bank-related names)
                query = query.filter(
                    Account.account_type == 'ASSET',
                    db.or_(
                        Account.category == 'Bank',
                        Account.name.ilike('%bank%'),
                        Account.name.ilike('%checking%'),
                        Account.name.ilike('%savings%'),
                        Account.account_code.like('1020%')  # Common bank account code prefix
                    )
                )
            elif account_type == 'cash' or account_type == 'petty_cash':
                # Get cash/petty cash accounts
                query = query.filter(
                    Account.account_type == 'ASSET',
                    db.or_(
                        Account.category == 'Cash',
                        Account.name.ilike('%cash%'),
                        Account.name.ilike('%petty%'),
                        Account.account_code.like('1010%')  # Common cash account code prefix
                    )
                )
        
        # Filter by active status
        if is_active is not None:
            is_active_bool = is_active.lower() == 'true'
            query = query.filter_by(is_active=is_active_bool)
        
        # Search
        if search:
            query = query.filter(
                db.or_(
                    Account.name.ilike(f'%{search}%'),
                    Account.display_name.ilike(f'%{search}%'),
                    Account.account_code.ilike(f'%{search}%'),
                    Account.description.ilike(f'%{search}%')
                )
            )
        
        # Pagination
        paginated = query.order_by(Account.account_code, Account.name).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        accounts = []
        for account in paginated.items:
            accounts.append({
                'id': account.id,
                'church_id': account.church_id,
                'account_code': account.account_code,
                'name': account.name,
                'display_name': account.display_name or account.name,
                'account_type': account.account_type,
                'type': account.account_type,  # For backward compatibility
                'category': account.category,
                'sub_category': account.sub_category,
                'parent_account_id': account.parent_account_id,
                'level': account.level,
                'description': account.description,
                'opening_balance': float(account.opening_balance) if account.opening_balance else 0,
                'current_balance': float(account.current_balance) if account.current_balance else 0,
                'normal_balance': account.normal_balance,
                'is_active': account.is_active,
                'is_contra': account.is_contra,
                'created_at': account.created_at.isoformat() if account.created_at else None,
                'updated_at': account.updated_at.isoformat() if account.updated_at else None
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
            'display_name': account.display_name or account.name,
            'account_type': account.account_type,
            'type': account.account_type,  # For backward compatibility
            'category': account.category,
            'sub_category': account.sub_category,
            'parent_account_id': account.parent_account_id,
            'level': account.level,
            'description': account.description,
            'opening_balance': float(account.opening_balance) if account.opening_balance else 0,
            'current_balance': float(account.current_balance) if account.current_balance else 0,
            'normal_balance': account.normal_balance,
            'is_active': account.is_active,
            'is_contra': account.is_contra,
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
        required_fields = ['name', 'account_type']  # Changed from 'type' to 'account_type'
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Generate account code if not provided
        if 'account_code' not in data:
            # Get the last account for this church
            church_id = data.get('church_id', g.current_user.church_id)
            last_account = Account.query.filter_by(
                church_id=church_id
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
        
        # Create account with correct field names
        account = Account(
            church_id=data.get('church_id', g.current_user.church_id),
            account_code=data['account_code'],
            name=data['name'],
            display_name=data.get('display_name', data['name']),
            account_type=data['account_type'].upper(),  # Convert to uppercase
            category=data.get('category'),
            sub_category=data.get('sub_category'),
            parent_account_id=data.get('parent_account_id'),
            level=data.get('level', 1),
            description=data.get('description', ''),
            opening_balance=data.get('opening_balance', 0),
            current_balance=data.get('opening_balance', 0),  # Initial balance equals opening balance
            normal_balance=data.get('normal_balance', 'debit'),
            is_active=data.get('is_active', True),
            is_contra=data.get('is_contra', False)
        )
        
        db.session.add(account)
        db.session.commit()
        
        return jsonify({
            'message': 'Account created successfully',
            'account': {
                'id': account.id,
                'name': account.name,
                'account_code': account.account_code,
                'account_type': account.account_type,
                'category': account.category
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating account: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@account_bp.route('/accounts/bank', methods=['GET', 'OPTIONS'])
@token_required
def get_bank_accounts():
    """Get bank accounts specifically"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = request.args.get('church_id', type=int)
        
        # Determine church ID
        if church_id:
            church_id_filter = church_id
        elif g.current_user and g.current_user.church_id:
            church_id_filter = g.current_user.church_id
        else:
            return jsonify({'error': 'No church specified'}), 400
        
        # Use the model's built-in method to get bank accounts
        accounts = Account.get_bank_accounts(church_id_filter)
        
        return jsonify({
            'accounts': [account.to_dict() for account in accounts]
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching bank accounts: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@account_bp.route('/accounts/cash', methods=['GET', 'OPTIONS'])
@token_required
def get_cash_accounts():
    """Get cash accounts specifically"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = request.args.get('church_id', type=int)
        
        # Determine church ID
        if church_id:
            church_id_filter = church_id
        elif g.current_user and g.current_user.church_id:
            church_id_filter = g.current_user.church_id
        else:
            return jsonify({'error': 'No church specified'}), 400
        
        # Use the model's built-in method to get cash accounts
        accounts = Account.get_cash_accounts(church_id_filter)
        
        return jsonify({
            'accounts': [account.to_dict() for account in accounts]
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching cash accounts: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500