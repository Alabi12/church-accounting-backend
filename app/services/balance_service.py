# app/services/balance_service.py
from decimal import Decimal
from app.models import Account, Transaction
from app.extensions import db
import logging

logger = logging.getLogger(__name__)

class BalanceService:
    
    @staticmethod
    def update_account_balance(account_id, amount_change, operation='add'):
        """
        Update account balance
        operation: 'add' to increase, 'subtract' to decrease
        """
        try:
            account = Account.query.get(account_id)
            if not account:
                logger.error(f"Account {account_id} not found")
                return False
            
            amount_change = Decimal(str(amount_change))
            
            if operation == 'add':
                account.current_balance = (account.current_balance or Decimal('0')) + amount_change
                logger.info(f"Added {amount_change} to account {account_id}. New balance: {account.current_balance}")
            elif operation == 'subtract':
                account.current_balance = (account.current_balance or Decimal('0')) - amount_change
                logger.info(f"Subtracted {amount_change} from account {account_id}. New balance: {account.current_balance}")
            
            db.session.commit()
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating account balance: {str(e)}", exc_info=True)
            return False
    
    @staticmethod
    def process_transaction_balance(transaction, action='create'):
        """
        Update account balance based on transaction action
        action: 'create', 'approve', 'post', 'reject', 'delete'
        """
        try:
            account_id = transaction.account_id
            amount = Decimal(str(transaction.amount))
            
            if transaction.transaction_type == 'INCOME':
                if action in ['create', 'approve', 'post']:
                    # Income increases balance
                    return BalanceService.update_account_balance(account_id, amount, 'add')
                elif action in ['reject', 'delete']:
                    # Rejecting/deleting income decreases balance
                    return BalanceService.update_account_balance(account_id, amount, 'subtract')
                    
            elif transaction.transaction_type == 'EXPENSE':
                if action in ['create', 'approve', 'post']:
                    # Expense decreases balance
                    return BalanceService.update_account_balance(account_id, amount, 'subtract')
                elif action in ['reject', 'delete']:
                    # Rejecting/deleting expense increases balance back
                    return BalanceService.update_account_balance(account_id, amount, 'add')
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing transaction balance: {str(e)}", exc_info=True)
            return False
    
    @staticmethod
    def verify_balance_integrity(account_id):
        """Verify that calculated balance matches actual transactions"""
        try:
            account = Account.query.get(account_id)
            if not account:
                return False, "Account not found"
            
            # Calculate expected balance from all transactions
            income_total = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter(
                Transaction.account_id == account_id,
                Transaction.transaction_type == 'INCOME',
                Transaction.status.in_(['POSTED', 'APPROVED'])
            ).scalar() or Decimal('0')
            
            expense_total = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter(
                Transaction.account_id == account_id,
                Transaction.transaction_type == 'EXPENSE',
                Transaction.status.in_(['POSTED', 'APPROVED'])
            ).scalar() or Decimal('0')
            
            opening_balance = account.opening_balance or Decimal('0')
            expected_balance = opening_balance + income_total - expense_total
            actual_balance = account.current_balance or Decimal('0')
            
            is_match = abs(expected_balance - actual_balance) < Decimal('0.01')
            
            return is_match, {
                'opening_balance': float(opening_balance),
                'income_total': float(income_total),
                'expense_total': float(expense_total),
                'expected_balance': float(expected_balance),
                'actual_balance': float(actual_balance),
                'difference': float(expected_balance - actual_balance)
            }
            
        except Exception as e:
            logger.error(f"Error verifying balance integrity: {str(e)}", exc_info=True)
            return False, str(e)