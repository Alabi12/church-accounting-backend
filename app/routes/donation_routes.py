from flask import Blueprint, request, jsonify, g, make_response
from datetime import datetime, timedelta
import logging
from sqlalchemy import func, desc, and_
import csv
import io

from app.models import Transaction, Member, Account, AuditLog
from app.extensions import db
from app.routes.auth_routes import token_required, permission_required
from app.utils.validators import validate_date_range

logger = logging.getLogger(__name__)
donation_bp = Blueprint('donations', __name__)

# Donation categories
DONATION_CATEGORIES = ['TITHE', 'OFFERING', 'SPECIAL_OFFERING', 'DONATION', 'PLEDGE', 'MISSION']


@donation_bp.route('', methods=['GET', 'OPTIONS'])
@token_required
def get_donations():
    """Get donations list with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('perPage', 20, type=int)
        
        # Build query for income transactions with donation categories
        query = Transaction.query.filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES)
        )
        
        # Apply filters
        start_date = request.args.get('startDate')
        if start_date:
            query = query.filter(Transaction.transaction_date >= datetime.fromisoformat(start_date))
        
        end_date = request.args.get('endDate')
        if end_date:
            end = datetime.fromisoformat(end_date)
            end = end.replace(hour=23, minute=59, second=59)
            query = query.filter(Transaction.transaction_date <= end)
        
        category = request.args.get('category')
        if category:
            query = query.filter_by(category=category.upper())
        
        member_id = request.args.get('memberId', type=int)
        if member_id:
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
        
        # Format response
        donation_list = []
        for t in paginated.items:
            member = Member.query.get(t.member_id) if t.member_id else None
            account = Account.query.get(t.account_id)
            
            donation_list.append({
                'id': t.id,
                'date': t.transaction_date.isoformat(),
                'category': t.category,
                'amount': float(t.amount),
                'description': t.description,
                'memberId': t.member_id,
                'memberName': member.get_full_name() if member else 'Anonymous',
                'memberEmail': member.email if member else None,
                'paymentMethod': t.payment_method.lower() if t.payment_method else 'cash',
                'reference': t.reference_number,
                'status': t.status.lower(),
                'account': {
                    'id': account.id if account else None,
                    'name': account.name if account else None,
                    'code': account.account_code if account else None
                } if account else None,
                'createdAt': t.created_at.isoformat() if t.created_at else None
            })
        
        # Calculate total amount
        total_amount = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES)
        ).scalar() or 0
        
        return jsonify({
            'donations': donation_list,
            'total': paginated.total,
            'totalAmount': float(total_amount),
            'pages': paginated.pages,
            'currentPage': paginated.page
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting donations: {str(e)}")
        return jsonify({'error': 'Failed to get donations'}), 500


@donation_bp.route('', methods=['POST', 'OPTIONS'])
@token_required
def create_donation():
    """Create a new donation"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        church_id = g.current_user.church_id
        
        # Validate required fields
        required_fields = ['date', 'amount', 'category']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        if data['category'] not in DONATION_CATEGORIES:
            return jsonify({'error': 'Invalid donation category'}), 400
        
        # Find or create income account for this category
        account = Account.query.filter_by(
            church_id=church_id,
            type='INCOME',
            category=data['category'].upper()
        ).first()
        
        if not account:
            # Create account if it doesn't exist
            account = Account(
                church_id=church_id,
                account_code=f"INC{len(Account.query.all()) + 1:04d}",
                name=f"Donation - {data['category']}",
                type='INCOME',
                category=data['category'].upper(),
                description=f"Income account for {data['category']} donations",
                opening_balance=0,
                current_balance=0,
                is_active=True
            )
            db.session.add(account)
            db.session.flush()
        
        # Generate transaction number
        date_str = datetime.utcnow().strftime('%Y%m%d')
        last_txn = Transaction.query.filter(
            Transaction.transaction_number.like(f'DON{date_str}%')
        ).order_by(Transaction.id.desc()).first()
        
        if last_txn:
            last_num = int(last_txn.transaction_number[-4:])
            new_num = last_num + 1
        else:
            new_num = 1
        
        transaction_number = f"DON{date_str}{new_num:04d}"
        
        # Create transaction
        transaction = Transaction(
            church_id=church_id,
            transaction_number=transaction_number,
            transaction_date=datetime.fromisoformat(data['date']),
            transaction_type='INCOME',
            category=data['category'].upper(),
            amount=float(data['amount']),
            account_id=account.id,
            member_id=data.get('memberId'),
            description=data.get('description', ''),
            payment_method=data.get('paymentMethod', 'CASH').upper(),
            reference_number=data.get('reference'),
            status='POSTED',  # Donations can be posted immediately
            notes=data.get('notes'),
            created_by=g.current_user.id
        )
        
        db.session.add(transaction)
        
        # Update account balance
        from decimal import Decimal
        account.current_balance = account.current_balance + Decimal(str(transaction.amount))
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='CREATE_DONATION',
            resource='donation',
            resource_id=transaction.id,
            data={'amount': data['amount'], 'category': data['category']},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Donation recorded successfully',
            'id': transaction.id,
            'transactionNumber': transaction_number
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating donation: {str(e)}")
        return jsonify({'error': str(e)}), 500


@donation_bp.route('/summary', methods=['GET', 'OPTIONS'])
@token_required
def get_donation_summary():
    """Get donation summary statistics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        year = request.args.get('year', datetime.utcnow().year, type=int)
        
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)
        
        # Get total donations
        total_donations = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        # Get total number of transactions
        total_transactions = db.session.query(func.count(Transaction.id)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        # Get unique donors count
        unique_donors = db.session.query(func.count(func.distinct(Transaction.member_id))).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED',
            Transaction.member_id.isnot(None)
        ).scalar() or 0
        
        # Get largest gift
        largest_gift = db.session.query(func.max(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        # Get donations by category
        category_results = db.session.query(
            Transaction.category,
            func.sum(Transaction.amount).label('total'),
            func.count(Transaction.id).label('count')
        ).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED'
        ).group_by(Transaction.category).all()
        
        categories = []
        for r in category_results:
            categories.append({
                'name': r.category.replace('_', ' ').title(),
                'total': float(r.total),
                'count': r.count
            })
        
        # Get monthly breakdown
        monthly_results = db.session.query(
            func.strftime('%m', Transaction.transaction_date).label('month'),
            func.sum(Transaction.amount).label('total'),
            func.count(Transaction.id).label('count')
        ).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED'
        ).group_by('month').order_by('month').all()
        
        monthly_breakdown = []
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        for r in monthly_results:
            month_idx = int(r.month) - 1
            monthly_breakdown.append({
                'month': month_names[month_idx],
                'total': float(r.total),
                'count': r.count
            })
        
        # Get top donors
        top_donors = db.session.query(
            Member,
            func.sum(Transaction.amount).label('total'),
            func.count(Transaction.id).label('count')
        ).join(
            Transaction, Transaction.member_id == Member.id
        ).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED',
            Member.is_active == True
        ).group_by(Member.id).order_by(desc('total')).limit(10).all()
        
        top_donors_list = []
        for donor, total, count in top_donors:
            top_donors_list.append({
                'id': donor.id,
                'name': donor.get_full_name(),
                'email': donor.email,
                'total': float(total),
                'count': count,
                'average': float(total) / count if count > 0 else 0
            })
        
        return jsonify({
            'year': year,
            'totalDonations': float(total_donations),
            'totalTransactions': total_transactions,
            'uniqueDonors': unique_donors,
            'largestGift': float(largest_gift),
            'averageGift': float(total_donations / total_transactions) if total_transactions > 0 else 0,
            'categories': categories,
            'monthlyBreakdown': monthly_breakdown,
            'topDonors': top_donors_list
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting donation summary: {str(e)}")
        return jsonify({'error': 'Failed to get donation summary'}), 500


@donation_bp.route('/export', methods=['GET', 'OPTIONS'])
@token_required
def export_donations():
    """Export donations as CSV"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        year = request.args.get('year', datetime.utcnow().year, type=int)
        start_date = request.args.get('startDate')
        end_date = request.args.get('endDate')
        format = request.args.get('format', 'csv')
        
        # Build query
        query = Transaction.query.filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.status == 'POSTED'
        )
        
        if year and not start_date:
            start_date = datetime(year, 1, 1)
            end_date = datetime(year, 12, 31, 23, 59, 59)
            query = query.filter(
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date
            )
        elif start_date and end_date:
            start = datetime.fromisoformat(start_date)
            end = datetime.fromisoformat(end_date)
            end = end.replace(hour=23, minute=59, second=59)
            query = query.filter(
                Transaction.transaction_date >= start,
                Transaction.transaction_date <= end
            )
        
        donations = query.order_by(Transaction.transaction_date.desc()).all()
        
        if format == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write headers
            writer.writerow(['Date', 'Member', 'Category', 'Amount', 'Payment Method', 'Reference', 'Description'])
            
            # Write data
            for d in donations:
                member = Member.query.get(d.member_id) if d.member_id else None
                writer.writerow([
                    d.transaction_date.strftime('%Y-%m-%d'),
                    member.get_full_name() if member else 'Anonymous',
                    d.category,
                    f"{float(d.amount):.2f}",
                    d.payment_method or 'N/A',
                    d.reference_number or '',
                    d.description or ''
                ])
            
            output.seek(0)
            
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename=donations_{year or "export"}.csv'
            
            return response
        
        else:
            return jsonify({'error': 'Unsupported format'}), 400
        
    except Exception as e:
        logger.error(f"Error exporting donations: {str(e)}")
        return jsonify({'error': 'Failed to export donations'}), 500


@donation_bp.route('/categories', methods=['GET', 'OPTIONS'])
@token_required
def get_donation_categories():
    """Get donation categories"""
    if request.method == 'OPTIONS':
        return '', 200
    
    categories = [
        {'id': 'TITHE', 'name': 'Tithe'},
        {'id': 'OFFERING', 'name': 'Offering'},
        {'id': 'SPECIAL_OFFERING', 'name': 'Special Offering'},
        {'id': 'DONATION', 'name': 'Donation'},
        {'id': 'PLEDGE', 'name': 'Pledge'},
        {'id': 'MISSION', 'name': 'Mission'},
    ]
    
    return jsonify(categories), 200


@donation_bp.route('/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_donation_stats():
    """Get donation statistics for dashboard"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        # Current year
        current_year = datetime.utcnow().year
        year_start = datetime(current_year, 1, 1)
        
        # This year's donations
        year_donations = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= year_start,
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        # This month's donations
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_donations = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= month_start,
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        # Today's donations
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        today_donations = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= today_start,
            Transaction.transaction_date <= today_end,
            Transaction.status == 'POSTED'
        ).scalar() or 0
        
        return jsonify({
            'today': float(today_donations),
            'thisMonth': float(month_donations),
            'thisYear': float(year_donations)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting donation stats: {str(e)}")
        return jsonify({'error': 'Failed to get donation stats'}), 500


@donation_bp.route('/member/<int:member_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_member_donations(member_id):
    """Get donations for a specific member"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        # Verify member belongs to this church
        member = Member.query.filter_by(id=member_id, church_id=church_id).first()
        if not member:
            return jsonify({'error': 'Member not found'}), 404
        
        year = request.args.get('year', datetime.utcnow().year, type=int)
        
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)
        
        donations = Transaction.query.filter(
            Transaction.church_id == church_id,
            Transaction.member_id == member_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED'
        ).order_by(Transaction.transaction_date.desc()).all()
        
        total = sum(float(d.amount) for d in donations)
        
        donation_list = []
        for d in donations:
            donation_list.append({
                'id': d.id,
                'date': d.transaction_date.isoformat(),
                'category': d.category,
                'amount': float(d.amount),
                'description': d.description,
                'paymentMethod': d.payment_method,
                'reference': d.reference_number
            })
        
        return jsonify({
            'memberId': member.id,
            'memberName': member.get_full_name(),
            'year': year,
            'total': float(total),
            'count': len(donations),
            'donations': donation_list
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting member donations: {str(e)}")
        return jsonify({'error': 'Failed to get member donations'}), 500


@donation_bp.route('/top-donors', methods=['GET', 'OPTIONS'])
@token_required
def get_top_donors():
    """Get top donors for a given period"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        limit = request.args.get('limit', 10, type=int)
        year = request.args.get('year', datetime.utcnow().year, type=int)
        
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)
        
        top_donors = db.session.query(
            Member,
            func.sum(Transaction.amount).label('total'),
            func.count(Transaction.id).label('count')
        ).join(
            Transaction, Transaction.member_id == Member.id
        ).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED',
            Member.is_active == True
        ).group_by(Member.id).order_by(desc('total')).limit(limit).all()
        
        donor_list = []
        for donor, total, count in top_donors:
            donor_list.append({
                'id': donor.id,
                'name': donor.get_full_name(),
                'email': donor.email,
                'total': float(total),
                'count': count,
                'average': float(total) / count if count > 0 else 0
            })
        
        return jsonify(donor_list), 200
        
    except Exception as e:
        logger.error(f"Error getting top donors: {str(e)}")
        return jsonify({'error': 'Failed to get top donors'}), 500


@donation_bp.route('/monthly', methods=['GET', 'OPTIONS'])
@token_required
def get_monthly_breakdown():
    """Get monthly donation breakdown"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        year = request.args.get('year', datetime.utcnow().year, type=int)
        
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)
        
        results = db.session.query(
            func.strftime('%m', Transaction.transaction_date).label('month'),
            func.sum(Transaction.amount).label('total'),
            func.count(Transaction.id).label('count')
        ).filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED'
        ).group_by('month').order_by('month').all()
        
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        monthly_data = []
        for r in results:
            month_idx = int(r.month) - 1
            monthly_data.append({
                'month': month_names[month_idx],
                'total': float(r.total),
                'count': r.count
            })
        
        return jsonify(monthly_data), 200
        
    except Exception as e:
        logger.error(f"Error getting monthly breakdown: {str(e)}")
        return jsonify({'error': 'Failed to get monthly breakdown'}), 500


@donation_bp.route('/quarterly', methods=['GET', 'OPTIONS'])
@token_required
def get_quarterly_breakdown():
    """Get quarterly donation breakdown"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        year = request.args.get('year', datetime.utcnow().year, type=int)
        
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)
        
        # Get all transactions
        transactions = Transaction.query.filter(
            Transaction.church_id == church_id,
            Transaction.transaction_type == 'INCOME',
            Transaction.category.in_(DONATION_CATEGORIES),
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            Transaction.status == 'POSTED'
        ).all()
        
        # Group by quarter
        quarters = {1: {'total': 0, 'count': 0}, 
                    2: {'total': 0, 'count': 0},
                    3: {'total': 0, 'count': 0}, 
                    4: {'total': 0, 'count': 0}}
        
        for t in transactions:
            quarter = (t.transaction_date.month - 1) // 3 + 1
            quarters[quarter]['total'] += float(t.amount)
            quarters[quarter]['count'] += 1
        
        quarterly_data = []
        for q in range(1, 5):
            quarterly_data.append({
                'quarter': f'Q{q}',
                'total': quarters[q]['total'],
                'count': quarters[q]['count']
            })
        
        return jsonify(quarterly_data), 200
        
    except Exception as e:
        logger.error(f"Error getting quarterly breakdown: {str(e)}")
        return jsonify({'error': 'Failed to get quarterly breakdown'}), 500