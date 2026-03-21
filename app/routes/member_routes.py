from flask import Blueprint, request, jsonify, g, make_response
from datetime import datetime, timedelta
import logging
import traceback
import csv
import io
from sqlalchemy import func, desc, and_

from app.models import Member, Transaction, AuditLog
from app.extensions import db
from app.routes.auth_routes import token_required

logger = logging.getLogger(__name__)
member_bp = Blueprint('member', __name__)

def generate_membership_number():
    """Generate unique membership number"""
    last_member = Member.query.order_by(Member.id.desc()).first()
    if last_member and last_member.membership_number:
        try:
            last_num = int(last_member.membership_number.split('-')[-1])
            new_num = last_num + 1
        except:
            new_num = 1
    else:
        new_num = 1
    
    return f"MEM-{datetime.utcnow().year}-{new_num:04d}"

@member_bp.route('', methods=['GET', 'OPTIONS'])
@token_required
def get_members():
    """Get members with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('perPage', 20, type=int)
        
        query = Member.query.filter_by(church_id=church_id)
        
        # Apply filters
        status = request.args.get('status')
        if status and status != 'all' and status != '':
            query = query.filter_by(status=status.upper())
        
        search = request.args.get('search')
        if search:
            query = query.filter(
                db.or_(
                    Member.first_name.ilike(f'%{search}%'),
                    Member.last_name.ilike(f'%{search}%'),
                    Member.email.ilike(f'%{search}%'),
                    Member.membership_number.ilike(f'%{search}%')
                )
            )
        
        is_tither = request.args.get('isTither')
        if is_tither == 'true':
            query = query.filter_by(is_tither=True)
        elif is_tither == 'false':
            query = query.filter_by(is_tither=False)
        
        # Get paginated results
        paginated = query.order_by(
            Member.last_name.asc(), Member.first_name.asc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        result = []
        for m in paginated.items:
            # Get giving summary
            total_given = db.session.query(func.sum(Transaction.amount)).filter(
                Transaction.member_id == m.id,
                Transaction.transaction_type == 'INCOME',
                Transaction.status == 'COMPLETED'
            ).scalar() or 0
            
            last_gift = Transaction.query.filter_by(
                member_id=m.id,
                transaction_type='INCOME'
            ).order_by(Transaction.transaction_date.desc()).first()
            
            result.append({
                'id': m.id,
                'firstName': m.first_name,
                'lastName': m.last_name,
                'fullName': m.get_full_name(),
                'email': m.email,
                'phone': m.phone,
                'address': m.address,
                'dateOfBirth': m.date_of_birth.strftime('%Y-%m-%d') if m.date_of_birth else None,
                'joinDate': m.join_date.strftime('%Y-%m-%d') if m.join_date else None,
                'membershipNumber': m.membership_number,
                'status': m.status,
                'givingPreference': m.giving_preference,
                'isTither': m.is_tither,
                'totalGiven': float(total_given),
                'lastGift': last_gift.transaction_date.strftime('%Y-%m-%d') if last_gift else None,
                'createdAt': m.created_at.strftime('%Y-%m-%d %H:%M:%S') if m.created_at else None
            })
        
        # Get summary stats
        total_members = Member.query.filter_by(church_id=church_id).count()
        active_members = Member.query.filter_by(church_id=church_id, status='ACTIVE').count()
        tithers = Member.query.filter_by(church_id=church_id, is_tither=True).count()
        
        # New members this month
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        new_members = Member.query.filter(
            Member.church_id == church_id,
            Member.join_date >= month_start
        ).count()
        
        return jsonify({
            'members': result,
            'total': paginated.total,
            'pages': paginated.pages,
            'currentPage': paginated.page,
            'summary': {
                'total': total_members,
                'active': active_members,
                'tithers': tithers,
                'newThisMonth': new_members
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting members: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Failed to get members'}), 500


@member_bp.route('/<int:member_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_member(member_id):
    """Get single member by ID"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        member = Member.query.get(member_id)
        if not member:
            return jsonify({'error': 'Member not found'}), 404
        
        # Get giving summary
        total_given = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.member_id == member.id,
            Transaction.transaction_type == 'INCOME',
            Transaction.status == 'COMPLETED'
        ).scalar() or 0
        
        last_gift = Transaction.query.filter_by(
            member_id=member.id,
            transaction_type='INCOME'
        ).order_by(Transaction.transaction_date.desc()).first()
        
        result = {
            'id': member.id,
            'firstName': member.first_name,
            'lastName': member.last_name,
            'fullName': member.get_full_name(),
            'email': member.email,
            'phone': member.phone,
            'address': member.address,
            'dateOfBirth': member.date_of_birth.strftime('%Y-%m-%d') if member.date_of_birth else None,
            'joinDate': member.join_date.strftime('%Y-%m-%d') if member.join_date else None,
            'membershipNumber': member.membership_number,
            'status': member.status,
            'givingPreference': member.giving_preference,
            'isTither': member.is_tither,
            'totalGiven': float(total_given),
            'lastGift': last_gift.transaction_date.strftime('%Y-%m-%d') if last_gift else None,
            'createdAt': member.created_at.strftime('%Y-%m-%d %H:%M:%S') if member.created_at else None
        }
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error getting member: {str(e)}")
        return jsonify({'error': 'Failed to get member'}), 500


@member_bp.route('', methods=['POST', 'OPTIONS'])
@token_required
def create_member():
    """Create new member"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        logger.info(f"Creating member with data: {data}")
        
        # Validate required fields
        required_fields = ['firstName', 'lastName']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        # Check if email already exists
        if data.get('email'):
            existing = Member.query.filter_by(
                church_id=g.current_user.church_id,
                email=data['email']
            ).first()
            if existing:
                return jsonify({'error': 'Email already exists'}), 400
        
        # Parse dates
        join_date = datetime.utcnow().date()
        if data.get('joinDate'):
            try:
                join_date = datetime.fromisoformat(data['joinDate']).date()
            except:
                join_date = datetime.utcnow().date()
        
        date_of_birth = None
        if data.get('dateOfBirth'):
            try:
                date_of_birth = datetime.fromisoformat(data['dateOfBirth']).date()
            except:
                pass
        
        # Create member
        member = Member(
            church_id=g.current_user.church_id,
            first_name=data['firstName'],
            last_name=data['lastName'],
            email=data.get('email'),
            phone=data.get('phone'),
            address=data.get('address'),
            date_of_birth=date_of_birth,
            join_date=join_date,
            membership_number=generate_membership_number(),
            status=data.get('status', 'ACTIVE'),
            giving_preference=data.get('givingPreference'),
            is_tither=data.get('isTither', False)
        )
        
        db.session.add(member)
        db.session.commit()
        
        logger.info(f"Created member: {member.membership_number}")
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='CREATE_MEMBER',
            resource='member',
            resource_id=member.id,
            data={'name': member.get_full_name()},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Member created successfully',
            'id': member.id,
            'membershipNumber': member.membership_number
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating member: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@member_bp.route('/<int:member_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_member(member_id):
    """Update member"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        member = Member.query.get(member_id)
        if not member:
            return jsonify({'error': 'Member not found'}), 404
        
        data = request.get_json()
        logger.info(f"Updating member {member_id} with data: {data}")
        
        # Update fields
        member.first_name = data.get('firstName', member.first_name)
        member.last_name = data.get('lastName', member.last_name)
        member.email = data.get('email', member.email)
        member.phone = data.get('phone', member.phone)
        member.address = data.get('address', member.address)
        member.status = data.get('status', member.status)
        member.giving_preference = data.get('givingPreference', member.giving_preference)
        member.is_tither = data.get('isTither', member.is_tither)
        
        if data.get('dateOfBirth'):
            try:
                member.date_of_birth = datetime.fromisoformat(data['dateOfBirth']).date()
            except:
                pass
        
        db.session.commit()
        logger.info(f"Updated member {member_id}")
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='UPDATE_MEMBER',
            resource='member',
            resource_id=member_id,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Member updated successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating member: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@member_bp.route('/<int:member_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_member(member_id):
    """Delete member"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        member = Member.query.get(member_id)
        if not member:
            return jsonify({'error': 'Member not found'}), 404
        
        # Check if member has transactions
        has_transactions = Transaction.query.filter_by(member_id=member_id).first()
        if has_transactions:
            return jsonify({'error': 'Cannot delete member with existing transactions'}), 400
        
        db.session.delete(member)
        db.session.commit()
        logger.info(f"Deleted member {member_id}")
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='DELETE_MEMBER',
            resource='member',
            resource_id=member_id,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Member deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting member: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@member_bp.route('/<int:member_id>/giving', methods=['GET', 'OPTIONS'])
@token_required
def get_member_giving(member_id):
    """Get member giving history"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        member = Member.query.get(member_id)
        if not member:
            return jsonify({'error': 'Member not found'}), 404
        
        start_date = request.args.get('startDate')
        end_date = request.args.get('endDate')
        
        query = Transaction.query.filter_by(
            member_id=member_id,
            transaction_type='INCOME'
        )
        
        if start_date:
            query = query.filter(Transaction.transaction_date >= datetime.fromisoformat(start_date))
        
        if end_date:
            query = query.filter(Transaction.transaction_date <= datetime.fromisoformat(end_date))
        
        transactions = query.order_by(Transaction.transaction_date.desc()).all()
        
        total_given = sum(t.amount for t in transactions)
        
        # Group by category
        by_category = {}
        for t in transactions:
            if t.category not in by_category:
                by_category[t.category] = 0
            by_category[t.category] += t.amount
        
        return jsonify({
            'member': {
                'id': member.id,
                'name': member.get_full_name(),
                'membershipNumber': member.membership_number
            },
            'totalGiven': float(total_given),
            'byCategory': [
                {'category': cat, 'amount': float(amount)}
                for cat, amount in by_category.items()
            ],
            'transactions': [
                {
                    'id': t.id,
                    'date': t.transaction_date.strftime('%Y-%m-%d'),
                    'amount': float(t.amount),
                    'category': t.category,
                    'description': t.description,
                    'transactionNumber': t.transaction_number
                } for t in transactions
            ]
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting member giving: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Failed to get member giving history'}), 500


@member_bp.route('/analytics', methods=['GET', 'OPTIONS'])
@token_required
def get_members_analytics():
    """Get members analytics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        period = request.args.get('period', 'month')
        
        end_date = datetime.utcnow()
        if period == 'month':
            start_date = end_date - timedelta(days=30)
        elif period == 'quarter':
            start_date = end_date - timedelta(days=90)
        elif period == 'year':
            start_date = end_date - timedelta(days=365)
        else:
            start_date = end_date - timedelta(days=30)
        
        # Member status distribution
        status_counts = db.session.query(
            Member.status,
            func.count(Member.id).label('count')
        ).filter(
            Member.church_id == church_id
        ).group_by(Member.status).all()
        
        status_distribution = [
            {'name': status, 'value': count}
            for status, count in status_counts
        ]
        
        # Member growth over time
        growth_data = db.session.query(
            func.strftime('%Y-%m', Member.join_date).label('month'),
            func.count(Member.id).label('count')
        ).filter(
            Member.church_id == church_id,
            Member.join_date >= start_date
        ).group_by('month').order_by('month').all()
        
        growth = [
            {'month': item.month, 'newMembers': item.count}
            for item in growth_data
        ]
        
        # Tither statistics
        total_members = Member.query.filter_by(church_id=church_id).count()
        tither_count = Member.query.filter_by(church_id=church_id, is_tither=True).count()
        tither_percentage = (tither_count / total_members * 100) if total_members > 0 else 0
        
        return jsonify({
            'period': period,
            'statusDistribution': status_distribution,
            'growthData': growth,
            'titherStats': {
                'total': tither_count,
                'percentage': round(tither_percentage, 1)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting members analytics: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Failed to get members analytics'}), 500


@member_bp.route('/export', methods=['GET', 'OPTIONS'])
@token_required
def export_members():
    """Export members to CSV"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        # Build query
        query = Member.query.filter_by(church_id=church_id)
        
        # Apply filters
        status = request.args.get('status')
        if status and status != 'all':
            query = query.filter_by(status=status.upper())
        
        is_tither = request.args.get('isTither')
        if is_tither == 'true':
            query = query.filter_by(is_tither=True)
        elif is_tither == 'false':
            query = query.filter_by(is_tither=False)
        
        search = request.args.get('search')
        if search:
            query = query.filter(
                db.or_(
                    Member.first_name.ilike(f'%{search}%'),
                    Member.last_name.ilike(f'%{search}%'),
                    Member.email.ilike(f'%{search}%')
                )
            )
        
        members = query.order_by(Member.last_name, Member.first_name).all()
        
        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        writer.writerow(['Membership #', 'First Name', 'Last Name', 'Email', 'Phone', 'Address', 'Join Date', 'Status', 'Tither', 'Giving Preference'])
        
        # Write data
        for m in members:
            writer.writerow([
                m.membership_number,
                m.first_name,
                m.last_name,
                m.email or '',
                m.phone or '',
                m.address or '',
                m.join_date.strftime('%Y-%m-%d') if m.join_date else '',
                m.status,
                'Yes' if m.is_tither else 'No',
                m.giving_preference or ''
            ])
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=members_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting members: {str(e)}")
        return jsonify({'error': 'Failed to export members'}), 500