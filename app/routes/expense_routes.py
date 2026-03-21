# app/routes/expense_routes.py
from flask import Blueprint, request, jsonify, g, make_response
from decimal import Decimal, InvalidOperation
from app.services.validation_service import ValidationService
from app.models import Account, Transaction, AuditLog
from app.extensions import db
from app.routes.auth_routes import token_required
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
expense_bp = Blueprint('expense', __name__)

# OPTIONS handler for all expense routes
@expense_bp.before_request
def handle_options():
    """Handle OPTIONS requests for all expense routes"""
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add("Access-Control-Allow-Origin", "http://localhost:3000")
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With,Accept,Origin')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response

@expense_bp.route('', methods=['POST', 'OPTIONS'])
@expense_bp.route('/', methods=['POST', 'OPTIONS'])
@token_required
def create_expense():
    """Create a new expense with balance validation"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['account_id', 'amount', 'description']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        account_id = data['account_id']
        amount = float(data['amount'])
        
        # Log the attempt
        logger.info(f"Expense creation attempt - Account: {account_id}, Amount: {amount}")
        
        # Get account details first
        account = Account.query.get(account_id)
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        
        # Check for sufficient funds with detailed logging
        is_sufficient, current_balance, available_balance, message = ValidationService.check_sufficient_funds(
            account_id, amount, 'EXPENSE'
        )
        
        logger.info(f"Balance check result - Sufficient: {is_sufficient}, Current: {current_balance}, Available: {available_balance}, Message: {message}")
        
        if not is_sufficient:
            # Log the failed attempt
            logger.warning(f"Insufficient funds attempt: Account {account_id} ({account.name}), Amount {amount}, Current Balance: {current_balance}, Available: {available_balance}")
            
            deficit = amount - available_balance
            return jsonify({
                'error': 'Insufficient funds',
                'details': {
                    'message': message,
                    'current_balance': current_balance,
                    'available_balance': available_balance,
                    'requested_amount': amount,
                    'deficit': round(deficit, 2),
                    'account_name': account.name
                }
            }), 402  # Payment Required status code
        
        # Create the expense transaction
        transaction = Transaction(
            church_id=g.current_user.church_id,
            transaction_type='EXPENSE',
            amount=amount,
            account_id=account_id,
            description=data['description'],
            category=data.get('category'),
            payment_method=data.get('payment_method', 'cash'),
            reference_number=data.get('reference'),
            status='PENDING',
            created_by=g.current_user.id,
            transaction_date=datetime.fromisoformat(data.get('date', datetime.utcnow().isoformat()))
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='CREATE_EXPENSE',
            resource='transaction',
            resource_id=transaction.id,
            data={'amount': amount, 'account_id': account_id, 'account_name': account.name},
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        db.session.commit()
        
        # Get updated account summary
        account_summary = ValidationService.get_account_summary(account_id)
        
        logger.info(f"Expense created successfully: ID {transaction.id}, Amount {amount}")
        
        return jsonify({
            'message': 'Expense created successfully',
            'transaction': transaction.to_dict(),
            'account_summary': account_summary
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating expense: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@expense_bp.route('/batch', methods=['POST', 'OPTIONS'])
@token_required
def create_batch_expenses():
    """Create multiple expenses with batch validation"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        transactions = data.get('transactions', [])
        
        if not transactions:
            return jsonify({'error': 'No transactions provided'}), 400
        
        # Validate all transactions first
        is_valid, validation_results = ValidationService.validate_batch_transactions(transactions)
        
        if not is_valid:
            failed = [r for r in validation_results if not r['is_sufficient']]
            return jsonify({
                'error': 'Insufficient funds for some transactions',
                'validation_results': validation_results,
                'failed_transactions': failed
            }), 402
        
        # Process all transactions
        created_transactions = []
        for tx_data in transactions:
            transaction = Transaction(
                church_id=g.current_user.church_id,
                transaction_type='EXPENSE',
                amount=tx_data['amount'],
                account_id=tx_data['account_id'],
                description=tx_data['description'],
                category=tx_data.get('category'),
                payment_method=tx_data.get('payment_method', 'cash'),
                reference_number=tx_data.get('reference'),
                status='PENDING',
                created_by=g.current_user.id
            )
            db.session.add(transaction)
            created_transactions.append(transaction)
        
        db.session.commit()
        
        return jsonify({
            'message': f'{len(created_transactions)} expenses created successfully',
            'transactions': [t.to_dict() for t in created_transactions]
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating batch expenses: {str(e)}")
        return jsonify({'error': str(e)}), 500

@expense_bp.route('/accounts/<int:account_id>/balance', methods=['GET', 'OPTIONS'])
@token_required
def get_account_balance(account_id):
    """Get detailed account balance information with debugging"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Get account with lock to ensure data consistency
        account = Account.query.with_for_update().get(account_id)
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        
        # Calculate pending expenses
        pending_expenses = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter(
            Transaction.account_id == account_id,
            Transaction.transaction_type == 'EXPENSE',
            Transaction.status.in_(['PENDING', 'APPROVED'])
        ).scalar() or Decimal('0')
        
        # Get all recent transactions for debugging
        recent_transactions = Transaction.query.filter_by(
            account_id=account_id
        ).order_by(Transaction.created_at.desc()).limit(5).all()
        
        recent_tx_data = [{
            'id': t.id,
            'amount': float(t.amount),
            'type': t.transaction_type,
            'status': t.status,
            'date': t.created_at.isoformat() if t.created_at else None
        } for t in recent_transactions]
        
        current_balance = account.current_balance or Decimal('0')
        available_balance = current_balance - pending_expenses
        
        summary = {
            'id': account.id,
            'name': account.name,
            'type': account.type,
            'current_balance': float(current_balance),
            'pending_expenses': float(pending_expenses),
            'available_balance': float(available_balance),
            'recent_transactions': recent_tx_data,
            'debug_info': {
                'account_code': account.account_code,
                'is_active': account.is_active,
                'last_updated': account.updated_at.isoformat() if account.updated_at else None
            }
        }
        
        logger.info(f"Account balance retrieved - ID: {account_id}, Name: {account.name}, Current: {current_balance}, Available: {available_balance}")
        
        return jsonify(summary), 200
        
    except Exception as e:
        logger.error(f"Error getting account balance: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@expense_bp.route('/<int:expense_id>/check-funds', methods=['GET', 'OPTIONS'])
@token_required
def check_expense_funds(expense_id):
    """Check if a pending expense still has sufficient funds"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        expense = Transaction.query.get(expense_id)
        if not expense:
            return jsonify({'error': 'Expense not found'}), 404
        
        if expense.transaction_type != 'EXPENSE':
            return jsonify({'error': 'Not an expense transaction'}), 400
        
        is_sufficient, balance, available, message = ValidationService.check_sufficient_funds(
            expense.account_id, expense.amount, 'EXPENSE'
        )
        
        return jsonify({
            'expense_id': expense_id,
            'is_sufficient': is_sufficient,
            'current_balance': balance,
            'available_balance': available,
            'requested_amount': float(expense.amount),
            'message': message,
            'status': expense.status
        }), 200
        
    except Exception as e:
        logger.error(f"Error checking expense funds: {str(e)}")
        return jsonify({'error': str(e)}), 500

@expense_bp.route('', methods=['GET', 'OPTIONS'])
@expense_bp.route('/', methods=['GET', 'OPTIONS'])
@token_required
def get_expenses():
    """Get all expenses with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        status = request.args.get('status')
        category = request.args.get('category')
        account_id = request.args.get('account_id')
        start_date = request.args.get('startDate')
        end_date = request.args.get('endDate')
        search = request.args.get('search')
        
        query = Transaction.query.filter_by(
            church_id=church_id,
            transaction_type='EXPENSE'
        )
        
        if status and status != 'all':
            query = query.filter_by(status=status.upper())
        
        if category and category != 'all':
            query = query.filter_by(category=category)
        
        if account_id and account_id != 'all':
            query = query.filter_by(account_id=account_id)
        
        if start_date:
            query = query.filter(Transaction.transaction_date >= datetime.fromisoformat(start_date))
        
        if end_date:
            end = datetime.fromisoformat(end_date)
            end = end.replace(hour=23, minute=59, second=59)
            query = query.filter(Transaction.transaction_date <= end)
        
        if search:
            query = query.filter(
                db.or_(
                    Transaction.description.ilike(f'%{search}%'),
                    Transaction.reference_number.ilike(f'%{search}%')
                )
            )
        
        expenses = query.order_by(Transaction.transaction_date.desc()).all()
        
        # Calculate stats
        stats = {
            'total': len(expenses),
            'pending': sum(1 for e in expenses if e.status == 'PENDING'),
            'approved': sum(1 for e in expenses if e.status == 'APPROVED'),
            'rejected': sum(1 for e in expenses if e.status == 'REJECTED'),
            'posted': sum(1 for e in expenses if e.status == 'POSTED'),
            'totalAmount': sum(float(e.amount) for e in expenses)
        }
        
        return jsonify({
            'expenses': [e.to_dict() for e in expenses],
            'stats': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting expenses: {str(e)}")
        return jsonify({'error': str(e)}), 500

@expense_bp.route('/<int:expense_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_expense(expense_id):
    """Get a single expense by ID"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        expense = Transaction.query.get(expense_id)
        if not expense:
            return jsonify({'error': 'Expense not found'}), 404
        
        return jsonify(expense.to_dict()), 200
        
    except Exception as e:
        logger.error(f"Error getting expense: {str(e)}")
        return jsonify({'error': str(e)}), 500

@expense_bp.route('/<int:expense_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_expense(expense_id):
    """Update an expense"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        expense = Transaction.query.get(expense_id)
        if not expense:
            return jsonify({'error': 'Expense not found'}), 404
        
        if expense.status != 'PENDING':
            return jsonify({'error': 'Cannot update non-pending expense'}), 400
        
        data = request.get_json()
        new_amount = float(data.get('amount', expense.amount))
        
        # Check if amount increased and verify funds
        if new_amount > expense.amount:
            is_sufficient, balance, available, message = ValidationService.check_sufficient_funds(
                expense.account_id, new_amount - expense.amount, 'EXPENSE'
            )
            
            if not is_sufficient:
                return jsonify({
                    'error': 'Insufficient funds for increase',
                    'details': {
                        'message': message,
                        'current_balance': balance,
                        'available_balance': available,
                        'additional_needed': new_amount - expense.amount,
                        'original_amount': float(expense.amount)
                    }
                }), 402
        
        # Update fields
        expense.amount = new_amount
        expense.description = data.get('description', expense.description)
        expense.category = data.get('category', expense.category)
        expense.payment_method = data.get('payment_method', expense.payment_method)
        expense.reference_number = data.get('reference', expense.reference_number)
        
        if data.get('date'):
            expense.transaction_date = datetime.fromisoformat(data['date'])
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='UPDATE_EXPENSE',
            resource='transaction',
            resource_id=expense_id,
            data={'changes': data},
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Expense updated successfully',
            'expense': expense.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating expense: {str(e)}")
        return jsonify({'error': str(e)}), 500

@expense_bp.route('/<int:expense_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_expense(expense_id):
    """Delete an expense"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        expense = Transaction.query.get(expense_id)
        if not expense:
            return jsonify({'error': 'Expense not found'}), 404
        
        if expense.status != 'PENDING':
            return jsonify({'error': 'Cannot delete non-pending expense'}), 400
        
        db.session.delete(expense)
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='DELETE_EXPENSE',
            resource='transaction',
            resource_id=expense_id,
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Expense deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting expense: {str(e)}")
        return jsonify({'error': str(e)}), 500