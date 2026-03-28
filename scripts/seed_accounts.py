# app/routes/accounts.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.extensions import db
from app.models.account import Account
from app.models.user import User
from app.seeders.seed_chart_of_accounts import seed_chart_of_accounts

accounts_bp = Blueprint('accounts', __name__)

@accounts_bp.route('/accounts/seed', methods=['POST'])
@jwt_required()
def seed_accounts():
    """Seed the chart of accounts for the current church"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if not user or not user.church_id:
        return jsonify({'error': 'No church associated with user'}), 400
    
    try:
        seed_chart_of_accounts(user.church_id)
        return jsonify({'message': 'Chart of accounts seeded successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@accounts_bp.route('/accounts', methods=['GET'])
@jwt_required()
def get_accounts():
    """Get all accounts for the current church"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if not user or not user.church_id:
        return jsonify({'error': 'No church associated with user'}), 400
    
    accounts = Account.query.filter_by(
        church_id=user.church_id,
        is_active=True
    ).order_by(Account.account_code).all()
    
    return jsonify({
        'accounts': [account.to_dict() for account in accounts]
    }), 200

@accounts_bp.route('/accounts/by-type/<account_type>', methods=['GET'])
@jwt_required()
def get_accounts_by_type(account_type):
    """Get accounts by type (ASSET, LIABILITY, REVENUE, EXPENSE, EQUITY)"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if not user or not user.church_id:
        return jsonify({'error': 'No church associated with user'}), 400
    
    accounts = Account.get_by_type(user.church_id, account_type.upper())
    
    return jsonify({
        'accounts': [account.to_dict() for account in accounts]
    }), 200

@accounts_bp.route('/accounts', methods=['POST'])
@jwt_required()
def create_account():
    """Create a new account"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if not user or not user.church_id:
        return jsonify({'error': 'No church associated with user'}), 400
    
    data = request.get_json()
    
    # Check if account code already exists
    existing = Account.query.filter_by(
        church_id=user.church_id,
        account_code=data['code']
    ).first()
    
    if existing:
        return jsonify({'error': 'Account code already exists'}), 400
    
    account = Account(
        church_id=user.church_id,
        account_code=data['code'],
        name=data['name'],
        display_name=f"{data['code']} - {data['name']}",
        account_type=data['type'],
        category=data.get('category'),
        level=2,  # Default to detail level
        opening_balance=data.get('openingBalance', 0),
        current_balance=data.get('openingBalance', 0),
        normal_balance=data.get('normalBalance', 'debit'),
        description=data.get('description'),
        is_active=data.get('isActive', True)
    )
    
    db.session.add(account)
    db.session.commit()
    
    return jsonify({'account': account.to_dict()}), 201

@accounts_bp.route('/accounts/<int:account_id>', methods=['PUT'])
@jwt_required()
def update_account(account_id):
    """Update an account"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if not user or not user.church_id:
        return jsonify({'error': 'No church associated with user'}), 400
    
    account = Account.query.filter_by(
        id=account_id,
        church_id=user.church_id
    ).first_or_404()
    
    data = request.get_json()
    
    account.name = data.get('name', account.name)
    account.display_name = f"{account.account_code} - {account.name}"
    account.category = data.get('category', account.category)
    account.description = data.get('description', account.description)
    account.is_active = data.get('isActive', account.is_active)
    
    db.session.commit()
    
    return jsonify({'account': account.to_dict()}), 200