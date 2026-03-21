# app/services/validation_service.py
from decimal import Decimal
from app.models import Account, Transaction
from app.extensions import db
import logging

logger = logging.getLogger(__name__)

class ValidationService:
    
    @staticmethod
    def check_sufficient_funds(account_id, amount, transaction_type='EXPENSE', exclude_transaction_id=None):
        """
        Check if account has sufficient funds for a transaction
        Returns: (is_sufficient, current_balance, available_balance, message)
        """
        account = Account.query.get(account_id)
        if not account:
            return False, 0, 0, "Account not found"
        
        # Get current balance
        current_balance = account.current_balance or Decimal('0')
        amount = Decimal(str(amount))
        
        # Calculate pending expenses that will reduce balance
        pending_query = Transaction.query.filter(
            Transaction.account_id == account_id,
            Transaction.transaction_type == 'EXPENSE',
            Transaction.status.in_(['PENDING', 'APPROVED'])
        )
        
        # Exclude current transaction if updating
        if exclude_transaction_id:
            pending_query = pending_query.filter(Transaction.id != exclude_transaction_id)
        
        pending_expenses = pending_query.with_entities(db.func.sum(Transaction.amount)).scalar() or Decimal('0')
        
        # Available balance = current balance - pending expenses
        available_balance = current_balance - pending_expenses
        
        logger.info(f"Balance check - Account: {account_id}, Current: {current_balance}, Pending: {pending_expenses}, Available: {available_balance}, Requested: {amount}")
        
        # For expenses/debits, check if available balance is sufficient
        if transaction_type.upper() in ['EXPENSE', 'DEBIT', 'WITHDRAWAL']:
            if available_balance < amount:
                deficit = amount - available_balance
                return (
                    False, 
                    float(current_balance), 
                    float(available_balance),
                    f"Insufficient funds! Required: {amount:.2f}, Available: {available_balance:.2f}, Deficit: {deficit:.2f}"
                )
        
        return True, float(current_balance), float(available_balance), "Sufficient funds available"
    
    @staticmethod
    def get_account_summary(account_id):
        """Get detailed account summary with balance information"""
        account = Account.query.get(account_id)
        if not account:
            return None
        
        # Calculate pending expenses
        pending_expenses = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.account_id == account_id,
            Transaction.transaction_type == 'EXPENSE',
            Transaction.status.in_(['PENDING', 'APPROVED'])
        ).scalar() or Decimal('0')
        
        # Calculate today's expenses that might not be in pending yet
        from datetime import date
        today = date.today()
        today_expenses = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.account_id == account_id,
            Transaction.transaction_type == 'EXPENSE',
            db.func.date(Transaction.created_at) == today
        ).scalar() or Decimal('0')
        
        current_balance = account.current_balance or Decimal('0')
        available_balance = current_balance - pending_expenses - today_expenses
        
        return {
            'id': account.id,
            'name': account.name,
            'type': account.type,
            'current_balance': float(current_balance),
            'pending_expenses': float(pending_expenses),
            'today_expenses': float(today_expenses),
            'available_balance': float(available_balance),
            'is_cash_account': 'cash' in account.name.lower() or 'petty' in account.name.lower(),
            'is_bank_account': 'bank' in account.name.lower() or 'checking' in account.name.lower() or 'savings' in account.name.lower()
        }