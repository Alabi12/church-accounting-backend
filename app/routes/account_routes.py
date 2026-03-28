# app/routes/account_routes.py
from flask import Blueprint, request, jsonify, g
from app.models import Account
from app.extensions import db
from datetime import datetime
from app.routes.auth_routes import token_required
import traceback
import logging

logger = logging.getLogger(__name__)
account_bp = Blueprint('account', __name__)

@account_bp.route('/accounting/chart-of-accounts', methods=['GET', 'OPTIONS'])
@token_required
def get_chart_of_accounts():
    """Get complete chart of accounts grouped by type for the journal form"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        if not church_id:
            return jsonify({'error': 'No church associated with user'}), 400
        
        # Get all active accounts
        accounts = Account.query.filter_by(
            church_id=church_id,
            is_active=True
        ).order_by(Account.account_code).all()
        
        # Group by account_type
        chart_of_accounts = {
            'ASSET': [],
            'LIABILITY': [],
            'EQUITY': [],
            'REVENUE': [],
            'EXPENSE': []
        }
        
        for account in accounts:
            account_data = {
                'id': account.id,
                'account_code': account.account_code,
                'name': account.name,
                'account_type': account.account_type,
                'category': account.category,
                'sub_category': account.sub_category,
                'normal_balance': account.normal_balance,
                'current_balance': float(account.current_balance) if account.current_balance else 0,
                'opening_balance': float(account.opening_balance) if account.opening_balance else 0,
                'is_contra': account.is_contra,
                'description': account.description
            }
            
            if account.account_type in chart_of_accounts:
                chart_of_accounts[account.account_type].append(account_data)
        
        logger.info(f"Returning chart of accounts with {len(accounts)} accounts for church {church_id}")
        
        return jsonify({
            'chart_of_accounts': chart_of_accounts,
            'total_accounts': len(accounts)
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching chart of accounts: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@account_bp.route('/accounting/accounts', methods=['GET', 'OPTIONS'])
@token_required
def get_accounting_accounts():
    """Get accounts for accounting module (simplified response)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        account_type = request.args.get('type')
        
        query = Account.query.filter_by(church_id=church_id, is_active=True)
        
        if account_type:
            query = query.filter_by(account_type=account_type.upper())
        
        accounts = query.order_by(Account.account_code).all()
        
        return jsonify({
            'accounts': [{
                'id': a.id,
                'account_code': a.account_code,
                'name': a.name,
                'account_type': a.account_type,
                'category': a.category,
                'normal_balance': a.normal_balance,
                'current_balance': float(a.current_balance) if a.current_balance else 0
            } for a in accounts]
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching accounting accounts: {str(e)}")
        return jsonify({'error': str(e)}), 500

@account_bp.route('/accounts', methods=['GET', 'OPTIONS'])
@token_required
def get_accounts():
    """Get all accounts with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        account_type = request.args.get('type')
        account_category = request.args.get('account_type')
        search = request.args.get('search')
        
        # Build query
        query = Account.query.filter_by(church_id=church_id)
        
        # Filter by account category (ASSET, REVENUE, etc.)
        if account_category:
            query = query.filter_by(account_type=account_category.upper())
        
        # Handle frontend 'type' parameter (bank/cash/petty_cash)
        if account_type:
            if account_type == 'bank':
                query = query.filter(
                    Account.account_type == 'ASSET',
                    db.or_(
                        Account.category == 'Bank',
                        Account.name.ilike('%bank%'),
                        Account.account_code.like('1020%')
                    )
                )
            elif account_type in ['cash', 'petty_cash']:
                query = query.filter(
                    Account.account_type == 'ASSET',
                    db.or_(
                        Account.category == 'Cash',
                        Account.name.ilike('%cash%'),
                        Account.account_code.like('1010%')
                    )
                )
        
        # Search
        if search:
            query = query.filter(
                db.or_(
                    Account.name.ilike(f'%{search}%'),
                    Account.account_code.ilike(f'%{search}%')
                )
            )
        
        accounts = query.filter_by(is_active=True).order_by(Account.account_code).all()
        
        return jsonify({
            'accounts': [{
                'id': a.id,
                'account_code': a.account_code,
                'name': a.name,
                'account_type': a.account_type,
                'category': a.category,
                'normal_balance': a.normal_balance,
                'current_balance': float(a.current_balance) if a.current_balance else 0
            } for a in accounts]
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching accounts: {str(e)}")
        return jsonify({'error': str(e)}), 500

@account_bp.route('/accounts/bank', methods=['GET', 'OPTIONS'])
@token_required
def get_bank_accounts():
    """Get bank accounts specifically"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        if not church_id:
            return jsonify({'error': 'No church specified'}), 400
        
        accounts = Account.get_bank_accounts(church_id)
        
        return jsonify({
            'accounts': [account.to_dict() for account in accounts]
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching bank accounts: {str(e)}")
        return jsonify({'error': str(e)}), 500

@account_bp.route('/accounts/cash', methods=['GET', 'OPTIONS'])
@token_required
def get_cash_accounts():
    """Get cash accounts specifically"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        if not church_id:
            return jsonify({'error': 'No church specified'}), 400
        
        accounts = Account.get_cash_accounts(church_id)
        
        return jsonify({
            'accounts': [account.to_dict() for account in accounts]
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching cash accounts: {str(e)}")
        return jsonify({'error': str(e)}), 500