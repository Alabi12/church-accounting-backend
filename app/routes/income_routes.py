from flask import Blueprint, request, jsonify, g, make_response
from datetime import datetime, timedelta
import logging
import traceback
import csv
import io
from sqlalchemy import func, desc
from decimal import Decimal

from app.models import Transaction, Account, Member, AuditLog
from app.extensions import db
from app.routes.auth_routes import token_required

logger = logging.getLogger(__name__)
income_bp = Blueprint('income', __name__)

def generate_transaction_number():
    """Generate unique transaction number"""
    date_str = datetime.utcnow().strftime('%Y%m%d')
    last_txn = Transaction.query.filter(
        Transaction.transaction_number.like(f'INC{date_str}%')
    ).order_by(Transaction.id.desc()).first()
    
    if last_txn:
        last_num = int(last_txn.transaction_number[-4:])
        new_num = last_num + 1
    else:
        new_num = 1
    
    return f"INC{date_str}{new_num:04d}"

@income_bp.route('', methods=['GET', 'OPTIONS'])
@token_required
def get_income():
    """Get income transactions with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('perPage', 10, type=int)
        
        query = Transaction.query.filter_by(
            church_id=church_id,
            transaction_type='INCOME'
        )
        
        # Apply filters
        start_date = request.args.get('startDate')
        if start_date:
            query = query.filter(Transaction.transaction_date >= datetime.fromisoformat(start_date))
        
        end_date = request.args.get('endDate')
        if end_date:
            query = query.filter(Transaction.transaction_date <= datetime.fromisoformat(end_date))
        
        category = request.args.get('category')
        if category and category != '':
            query = query.filter_by(category=category)
        
        payment_method = request.args.get('paymentMethod')
        if payment_method and payment_method != '':
            query = query.filter_by(payment_method=payment_method)
        
        status = request.args.get('status')
        if status and status != '':
            query = query.filter_by(status=status.upper())
        
        member_id = request.args.get('memberId')
        if member_id and member_id != '':
            query = query.filter_by(member_id=member_id)
        
        search = request.args.get('search')
        if search:
            query = query.filter(
                db.or_(
                    Transaction.description.ilike(f'%{search}%'),
                    Transaction.reference_number.ilike(f'%{search}%')
                )
            )
        
        # Get paginated results
        paginated = query.order_by(
            Transaction.transaction_date.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        result = []
        for t in paginated.items:
            account = Account.query.get(t.account_id)
            member = Member.query.get(t.member_id) if t.member_id else None
            
            result.append({
                'id': t.id,
                'date': t.transaction_date.strftime('%Y-%m-%d'),  # FIXED: Use strftime instead of isoformat
                'transactionNumber': t.transaction_number,
                'category': t.category,
                'amount': float(t.amount),
                'description': t.description or '',
                'paymentMethod': t.payment_method,
                'reference': t.reference_number or '',
                'status': t.status,
                'notes': t.notes or '',
                'account': {
                    'id': account.id if account else None,
                    'name': account.name if account else 'Unknown',
                    'code': account.account_code if account else None
                } if account else None,
                'member': {
                    'id': member.id if member else None,
                    'name': member.get_full_name() if member else None,
                    'email': member.email if member else None
                } if member else None,
                'createdAt': t.created_at.strftime('%Y-%m-%d %H:%M:%S') if t.created_at else None
            })
        
        # Get summary stats
        total_amount = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME'
        ).scalar() or 0
        
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_amount = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.transaction_date >= month_start
        ).scalar() or 0
        
        return jsonify({
            'transactions': result,
            'total': paginated.total,
            'pages': paginated.pages,
            'currentPage': paginated.page,
            'summary': {
                'totalAmount': float(total_amount),
                'monthAmount': float(month_amount)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting income: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Failed to get income transactions'}), 500


@income_bp.route('/<int:income_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_income_by_id(income_id):
    """Get single income transaction by ID"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        transaction = Transaction.query.get(income_id)
        if not transaction:
            return jsonify({'error': 'Income not found'}), 404
        
        account = Account.query.get(transaction.account_id)
        member = Member.query.get(transaction.member_id) if transaction.member_id else None
        
        result = {
            'id': transaction.id,
            'date': transaction.transaction_date.strftime('%Y-%m-%d'),  # FIXED
            'transactionNumber': transaction.transaction_number,
            'category': transaction.category,
            'amount': float(transaction.amount),
            'description': transaction.description or '',
            'paymentMethod': transaction.payment_method,
            'reference': transaction.reference_number or '',
            'status': transaction.status,
            'notes': transaction.notes or '',
            'account': {
                'id': account.id if account else None,
                'name': account.name if account else 'Unknown',
                'code': account.account_code if account else None
            } if account else None,
            'member': {
                'id': member.id if member else None,
                'name': member.get_full_name() if member else None,
                'email': member.email if member else None
            } if member else None,
            'createdAt': transaction.created_at.strftime('%Y-%m-%d %H:%M:%S') if transaction.created_at else None
        }
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error getting income: {str(e)}")
        return jsonify({'error': 'Failed to get income'}), 500


@income_bp.route('', methods=['POST', 'OPTIONS'])
@token_required
def create_income():
    """Create new income transaction"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        logger.info(f"Received income data: {data}")
        
        # Validate required fields
        required_fields = ['amount', 'category', 'paymentMethod']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        # Get or create income account
        account_code = f"4{data['category'][:3]}"
        account = Account.query.filter_by(
            church_id=g.current_user.church_id,
            account_code=account_code,
            type='INCOME'
        ).first()
        
        if not account:
            account = Account(
                church_id=g.current_user.church_id,
                account_code=account_code,
                name=f"{data['category']} Income",
                type='INCOME',
                category='OPERATING_INCOME',
                is_active=True
            )
            db.session.add(account)
            db.session.flush()
            logger.info(f"Created new account: {account_code}")
        
        # Parse date
        transaction_date = datetime.utcnow()
        if data.get('date'):
            try:
                transaction_date = datetime.fromisoformat(data['date'])
            except:
                transaction_date = datetime.utcnow()
        
        # Create transaction
        transaction = Transaction(
            church_id=g.current_user.church_id,
            transaction_number=generate_transaction_number(),
            transaction_date=transaction_date,
            transaction_type='INCOME',
            category=data['category'],
            amount=Decimal(str(data['amount'])),
            account_id=account.id,
            member_id=data.get('memberId') if data.get('memberId') else None,
            description=data.get('description', ''),
            payment_method=data['paymentMethod'],
            reference_number=data.get('reference', ''),
            notes=data.get('notes', ''),
            status='COMPLETED',
            created_by=g.current_user.id
        )
        
        db.session.add(transaction)
        
        # Update account balance
        account.current_balance = account.current_balance + Decimal(str(data['amount']))
        
        db.session.commit()
        logger.info(f"Created income transaction: {transaction.transaction_number}")
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='CREATE_INCOME',
            resource='income',
            resource_id=transaction.id,
            data={'amount': data['amount'], 'category': data['category']},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Income recorded successfully',
            'id': transaction.id,
            'transactionNumber': transaction.transaction_number
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating income: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@income_bp.route('/<int:income_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_income(income_id):
    """Update income transaction"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        transaction = Transaction.query.get(income_id)
        if not transaction:
            return jsonify({'error': 'Income transaction not found'}), 404
        
        if transaction.status != 'COMPLETED':
            return jsonify({'error': 'Cannot update voided or pending transactions'}), 400
        
        data = request.get_json()
        logger.info(f"Updating income {income_id} with data: {data}")
        
        # Reverse old account balance
        old_account = Account.query.get(transaction.account_id)
        if old_account:
            old_account.current_balance = old_account.current_balance - transaction.amount
        
        # Update transaction fields
        if data.get('date'):
            try:
                transaction.transaction_date = datetime.fromisoformat(data['date'])
            except:
                pass
        
        transaction.description = data.get('description', transaction.description)
        transaction.payment_method = data.get('paymentMethod', transaction.payment_method)
        transaction.reference_number = data.get('reference', transaction.reference_number)
        transaction.notes = data.get('notes', transaction.notes)
        
        # Check if amount changed
        if 'amount' in data and float(data['amount']) != float(transaction.amount):
            old_amount = transaction.amount
            new_amount = Decimal(str(data['amount']))
            transaction.amount = new_amount
            
            # Update account with new amount
            if old_account:
                old_account.current_balance = old_account.current_balance + new_amount
        
        db.session.commit()
        logger.info(f"Updated income {income_id}")
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='UPDATE_INCOME',
            resource='income',
            resource_id=income_id,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Income updated successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating income: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@income_bp.route('/<int:income_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_income(income_id):
    """Delete income transaction"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        transaction = Transaction.query.get(income_id)
        if not transaction:
            return jsonify({'error': 'Income transaction not found'}), 404
        
        if transaction.status != 'COMPLETED':
            return jsonify({'error': 'Cannot delete voided or pending transactions'}), 400
        
        # Reverse account balance
        account = Account.query.get(transaction.account_id)
        if account:
            account.current_balance = account.current_balance - transaction.amount
        
        db.session.delete(transaction)
        db.session.commit()
        logger.info(f"Deleted income {income_id}")
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='DELETE_INCOME',
            resource='income',
            resource_id=income_id,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Income deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting income: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@income_bp.route('/summary', methods=['GET', 'OPTIONS'])
@token_required
def get_income_summary():
    """Get income summary for dashboard"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        today = datetime.utcnow().date()
        today_income = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.status == 'COMPLETED',
            func.date(Transaction.transaction_date) == today
        ).scalar() or 0
        
        month_start = today.replace(day=1)
        month_income = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.status == 'COMPLETED',
            Transaction.transaction_date >= month_start
        ).scalar() or 0
        
        year_start = today.replace(month=1, day=1)
        year_income = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.status == 'COMPLETED',
            Transaction.transaction_date >= year_start
        ).scalar() or 0
        
        return jsonify({
            'today': float(today_income),
            'this_month': float(month_income),
            'this_year': float(year_income)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting income summary: {str(e)}")
        return jsonify({'error': 'Failed to get income summary'}), 500


@income_bp.route('/analytics', methods=['GET', 'OPTIONS'])
@token_required
def get_income_analytics():
    """Get income analytics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        period = request.args.get('period', 'month')
        
        end_date = datetime.utcnow()
        if period == 'week':
            start_date = end_date - timedelta(days=7)
        elif period == 'month':
            start_date = end_date - timedelta(days=30)
        elif period == 'quarter':
            start_date = end_date - timedelta(days=90)
        elif period == 'year':
            start_date = end_date - timedelta(days=365)
        else:
            start_date = end_date - timedelta(days=30)
        
        # Get income by category
        by_category = db.session.query(
            Transaction.category,
            func.count(Transaction.id).label('count'),
            func.sum(Transaction.amount).label('total')
        ).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.status == 'COMPLETED',
            Transaction.transaction_date >= start_date
        ).group_by(Transaction.category).all()
        
        # Get daily trend - FIXED: Use strftime for date formatting
        daily_trend = db.session.query(
            func.date(Transaction.transaction_date).label('date'),
            func.sum(Transaction.amount).label('total')
        ).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.status == 'COMPLETED',
            Transaction.transaction_date >= start_date
        ).group_by(func.date(Transaction.transaction_date)).order_by('date').all()
        
        # Get top givers
        top_givers = db.session.query(
            Member,
            func.sum(Transaction.amount).label('total')
        ).join(
            Transaction, Transaction.member_id == Member.id
        ).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.status == 'COMPLETED',
            Transaction.transaction_date >= start_date
        ).group_by(Member.id).order_by(
            func.sum(Transaction.amount).desc()
        ).limit(10).all()
        
        # Format the daily trend data - FIXED: Convert date objects to strings
        formatted_daily_trend = []
        for day in daily_trend:
            # Check if day.date is a date object or string
            date_str = day.date
            if hasattr(day.date, 'strftime'):
                date_str = day.date.strftime('%Y-%m-%d')
            
            formatted_daily_trend.append({
                'date': date_str,
                'total': float(day.total)
            })
        
        return jsonify({
            'period': period,
            'by_category': [
                {
                    'category': cat.category,
                    'count': cat.count,
                    'total': float(cat.total)
                } for cat in by_category
            ],
            'daily_trend': formatted_daily_trend,  # Use formatted data
            'top_givers': [
                {
                    'member': {
                        'id': member[0].id,
                        'name': member[0].get_full_name(),
                        'email': member[0].email
                    },
                    'total': float(member[1])
                } for member in top_givers
            ]
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting income analytics: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Failed to get income analytics'}), 500


@income_bp.route('/categories', methods=['GET', 'OPTIONS'])
@token_required
def get_income_categories():
    """Get income categories"""
    if request.method == 'OPTIONS':
        return '', 200
    
    categories = [
        {'id': 'TITHE', 'name': 'Tithe'},
        {'id': 'OFFERING', 'name': 'Offering'},
        {'id': 'SPECIAL_OFFERING', 'name': 'Special Offering'},
        {'id': 'DONATION', 'name': 'Donation'},
        {'id': 'PLEDGE', 'name': 'Pledge Payment'},
        {'id': 'OTHER', 'name': 'Other'}
    ]
    
    return jsonify(categories), 200


@income_bp.route('/export', methods=['GET', 'OPTIONS'])
@token_required
def export_income():
    """Export income to CSV"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        # Build query
        query = Transaction.query.filter_by(
            church_id=church_id,
            transaction_type='INCOME'
        )
        
        # Apply filters
        start_date = request.args.get('startDate')
        if start_date:
            query = query.filter(Transaction.transaction_date >= datetime.fromisoformat(start_date))
        
        end_date = request.args.get('endDate')
        if end_date:
            query = query.filter(Transaction.transaction_date <= datetime.fromisoformat(end_date))
        
        category = request.args.get('category')
        if category and category != 'all':
            query = query.filter_by(category=category)
        
        status = request.args.get('status')
        if status and status != 'all':
            query = query.filter_by(status=status.upper())
        
        search = request.args.get('search')
        if search:
            query = query.filter(
                db.or_(
                    Transaction.description.ilike(f'%{search}%'),
                    Transaction.reference_number.ilike(f'%{search}%')
                )
            )
        
        incomes = query.order_by(Transaction.transaction_date.desc()).all()
        
        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        writer.writerow(['Date', 'Transaction #', 'Description', 'Category', 'Amount', 'Payment Method', 'Reference', 'Donor', 'Status', 'Notes'])
        
        # Write data
        for inc in incomes:
            member = Member.query.get(inc.member_id) if inc.member_id else None
            donor_name = member.get_full_name() if member else ''
            
            writer.writerow([
                inc.transaction_date.strftime('%Y-%m-%d'),
                inc.transaction_number,
                inc.description or '',
                inc.category,
                f"{inc.amount:.2f}",
                inc.payment_method,
                inc.reference_number or '',
                donor_name,
                inc.status,
                inc.notes or ''
            ])
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=income_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting income: {str(e)}")
        return jsonify({'error': 'Failed to export income'}), 500