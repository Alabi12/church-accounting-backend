from flask import Blueprint, make_response, request, jsonify, g
from datetime import datetime
import logging
import traceback
import json
from sqlalchemy import func
from decimal import Decimal

from app.models import JournalEntry, JournalLine, Account, AuditLog, User, Church
from app.extensions import db
from app.routes.auth_routes import token_required

logger = logging.getLogger(__name__)
journal_bp = Blueprint('journal', __name__)


def ensure_user_church(user=None):
    """Make sure user has a church_id, assign default if not"""
    if user is None:
        user = g.current_user if hasattr(g, 'current_user') else None
    
    if not user:
        default_church = Church.query.first()
        if default_church:
            return default_church.id
        raise ValueError("No authenticated user and no default church found")
    
    if not user.church_id:
        default_church = Church.query.first()
        if default_church:
            user.church_id = default_church.id
            db.session.add(user)
            db.session.commit()
    return user.church_id


def generate_entry_number(church_id):
    """Generate a unique journal entry number"""
    today = datetime.utcnow()
    year = today.strftime('%Y')
    month = today.strftime('%m')
    
    # Get the last entry number for this church this month
    last_entry = JournalEntry.query.filter(
        JournalEntry.church_id == church_id,
        JournalEntry.entry_number.like(f'JE-{year}{month}%')
    ).order_by(JournalEntry.id.desc()).first()
    
    if last_entry:
        last_num = int(last_entry.entry_number[-4:])
        new_num = last_num + 1
    else:
        new_num = 1
    
    return f"JE-{year}{month}{new_num:04d}"


@journal_bp.route('/journal_entries/direct-post', methods=['POST'])
@token_required
def create_direct_journal_entry():
    """Create and post a journal entry directly (bypass approval)"""
    try:
        user = g.current_user
        data = request.get_json()
        
        church_id = user.church_id if user.church_id else 1
        
        print(f"\n{'='*60}")
        print(f"📥 CREATE DIRECT JOURNAL ENTRY")
        print(f"{'='*60}")
        print(f"Request data: {json.dumps(data, indent=2)}")
        
        # Validate required fields
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        if not data.get('entry_date'):
            return jsonify({'error': 'Entry date is required'}), 400
            
        if not data.get('description'):
            return jsonify({'error': 'Description is required'}), 400
            
        if not data.get('lines') or len(data['lines']) < 2:
            return jsonify({'error': 'At least two journal lines are required'}), 400
        
        # Generate entry number
        entry_number = generate_entry_number(church_id)
        
        # Parse entry date
        try:
            entry_date = datetime.fromisoformat(data['entry_date'].replace('Z', '+00:00'))
        except Exception as e:
            return jsonify({'error': f'Invalid date format: {str(e)}'}), 400
        
        # Create the journal entry with POSTED status directly
        entry = JournalEntry(
            church_id=church_id,
            entry_number=entry_number,
            entry_date=entry_date,
            description=data['description'],
            reference=data.get('reference', ''),
            status='POSTED',
            created_by=user.id,
            created_at=datetime.utcnow(),
            posted_by=user.id,
            posted_at=datetime.utcnow()
        )
        
        db.session.add(entry)
        db.session.flush()
        
        # Add journal lines and update account balances
        total_debit = 0
        total_credit = 0
        
        for line_data in data['lines']:
            if not line_data.get('account_id'):
                db.session.rollback()
                return jsonify({'error': 'account_id is required for each line'}), 400
            
            debit = float(line_data.get('debit', 0))
            credit = float(line_data.get('credit', 0))
            
            if debit > 0 and credit > 0:
                db.session.rollback()
                return jsonify({'error': 'A line cannot have both debit and credit'}), 400
            if debit == 0 and credit == 0:
                db.session.rollback()
                return jsonify({'error': 'Each line must have either debit or credit'}), 400
            
            total_debit += debit
            total_credit += credit
            
            # Update account balance
            account = Account.query.get(line_data['account_id'])
            if account:
                old_balance = float(account.current_balance) if account.current_balance else 0
                if debit > 0:
                    if account.account_type in ['ASSET', 'EXPENSE']:
                        account.current_balance = old_balance + debit
                    else:
                        account.current_balance = old_balance - debit
                else:
                    if account.account_type in ['LIABILITY', 'EQUITY', 'REVENUE']:
                        account.current_balance = old_balance + credit
                    else:
                        account.current_balance = old_balance - credit
                print(f"  Updated {account.name}: {old_balance} → {float(account.current_balance)}")
            
            line = JournalLine(
                journal_entry_id=entry.id,
                account_id=line_data['account_id'],
                debit=debit,
                credit=credit,
                description=line_data.get('description', '')
            )
            db.session.add(line)
        
        # Check if balanced
        if abs(total_debit - total_credit) > 0.01:
            db.session.rollback()
            return jsonify({'error': f'Journal entry does not balance: Debits ({total_debit}) must equal Credits ({total_credit})'}), 400
        
        db.session.commit()
        
        print(f"✅ Journal entry created and posted: {entry.entry_number}")
        
        return jsonify({
            'message': 'Journal entry created and posted successfully',
            'id': entry.id,
            'entry_number': entry.entry_number,
            'status': 'POSTED'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error creating direct journal entry: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@journal_bp.route('/journal_entries/<int:entry_id>/submit', methods=['POST'])
@token_required
def submit_journal_entry(entry_id):
    """Submit a DRAFT journal entry for approval"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        entry = JournalEntry.query.filter_by(
            id=entry_id, church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        if entry.status != 'DRAFT':
            return jsonify({'error': f'Cannot submit entry with status {entry.status}'}), 400
        
        # Update status to PENDING
        entry.status = 'PENDING'
        db.session.commit()
        
        print(f"✅ Journal entry {entry.entry_number} submitted for approval")
        
        return jsonify({
            'message': 'Journal entry submitted for approval',
            'id': entry.id,
            'status': entry.status
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting journal entry: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@journal_bp.route('/journal_entries', methods=['GET', 'OPTIONS'])
@token_required
def get_journal_entries():
    """Get journal entries with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Build query
        query = JournalEntry.query.filter_by(church_id=church_id)
        
        # Apply filters
        start_date = request.args.get('start_date')
        if start_date:
            query = query.filter(JournalEntry.entry_date >= datetime.fromisoformat(start_date))
        
        end_date = request.args.get('end_date')
        if end_date:
            end = datetime.fromisoformat(end_date)
            end = end.replace(hour=23, minute=59, second=59)
            query = query.filter(JournalEntry.entry_date <= end)
        
        status = request.args.get('status')
        if status:
            query = query.filter(JournalEntry.status == status.upper())
        
        search = request.args.get('search')
        if search:
            query = query.filter(
                db.or_(
                    JournalEntry.entry_number.ilike(f'%{search}%'),
                    JournalEntry.description.ilike(f'%{search}%'),
                    JournalEntry.reference.ilike(f'%{search}%')
                )
            )
        
        # Order by date descending, then id descending
        query = query.order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
        
        # Paginate
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        entries = []
        for entry in paginated.items:
            entry_dict = {
                'id': entry.id,
                'entry_number': entry.entry_number,
                'entry_date': entry.entry_date.isoformat() if entry.entry_date else None,
                'description': entry.description,
                'reference': entry.reference,
                'status': entry.status,
                'created_by': entry.created_by,
                'created_at': entry.created_at.isoformat() if entry.created_at else None,
            }
            
            # Add creator info
            creator = User.query.get(entry.created_by)
            entry_dict['created_by_name'] = creator.username if creator else 'Unknown'
            
            # Add lines
            if hasattr(entry, 'lines') and entry.lines:
                entry_dict['lines'] = [line.to_dict() for line in entry.lines]
                entry_dict['total_debit'] = sum(float(line.debit) for line in entry.lines)
                entry_dict['total_credit'] = sum(float(line.credit) for line in entry.lines)
                entry_dict['is_balanced'] = abs(entry_dict['total_debit'] - entry_dict['total_credit']) < 0.01
            
            # Add poster info
            if hasattr(entry, 'posted_by') and entry.posted_by:
                poster = User.query.get(entry.posted_by)
                entry_dict['posted_by_name'] = poster.username if poster else 'Unknown'
            else:
                entry_dict['posted_by_name'] = None
                
            if hasattr(entry, 'posted_at') and entry.posted_at:
                entry_dict['posted_at'] = entry.posted_at.isoformat()
            else:
                entry_dict['posted_at'] = None
            
            # Add approver info
            if hasattr(entry, 'approved_by') and entry.approved_by:
                approver = User.query.get(entry.approved_by)
                entry_dict['approved_by_name'] = approver.username if approver else 'Unknown'
            else:
                entry_dict['approved_by_name'] = None
                
            if hasattr(entry, 'approved_at') and entry.approved_at:
                entry_dict['approved_at'] = entry.approved_at.isoformat()
            else:
                entry_dict['approved_at'] = None
            
            entries.append(entry_dict)
        
        return jsonify({
            'entries': entries,
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': paginated.page,
            'per_page': per_page
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting journal entries: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Failed to get journal entries'}), 500


@journal_bp.route('/journal_entries', methods=['POST', 'OPTIONS'])
@token_required
def create_journal_entry():
    """Create a new journal entry"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        user = g.current_user
        data = request.get_json()
        
        print(f"\n{'='*60}")
        print(f"📥 CREATE JOURNAL ENTRY")
        print(f"{'='*60}")
        print(f"Request data: {json.dumps(data, indent=2)}")
        
        # Validate required fields
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        if not data.get('entry_date'):
            return jsonify({'error': 'Entry date is required'}), 400
            
        if not data.get('description'):
            return jsonify({'error': 'Description is required'}), 400
            
        if not data.get('lines') or len(data['lines']) < 2:
            return jsonify({'error': 'At least two journal lines are required'}), 400
        
        church_id = user.church_id if user.church_id else 1
        entry_number = generate_entry_number(church_id)
        
        try:
            entry_date = datetime.fromisoformat(data['entry_date'].replace('Z', '+00:00'))
        except Exception as e:
            return jsonify({'error': f'Invalid date format: {str(e)}'}), 400
        
        # Create the journal entry
        entry = JournalEntry(
            church_id=church_id,
            entry_number=entry_number,
            entry_date=entry_date,
            description=data['description'],
            reference=data.get('reference', ''),
            status='DRAFT',
            created_by=user.id,
            created_at=datetime.utcnow()
        )
        
        db.session.add(entry)
        db.session.flush()
        
        # Add journal lines
        total_debit = 0
        total_credit = 0
        
        for line_data in data['lines']:
            debit = float(line_data.get('debit', 0))
            credit = float(line_data.get('credit', 0))
            
            total_debit += debit
            total_credit += credit
            
            line = JournalLine(
                journal_entry_id=entry.id,
                account_id=line_data['account_id'],
                debit=debit,
                credit=credit,
                description=line_data.get('description', '')
            )
            db.session.add(line)
        
        # Check if balanced
        if abs(total_debit - total_credit) > 0.01:
            db.session.rollback()
            return jsonify({'error': f'Journal entry does not balance: Debits ({total_debit}) must equal Credits ({total_credit})'}), 400
        
        # Handle submit for approval
        if data.get('submit_for_approval', False):
            entry.status = 'PENDING'
        
        db.session.commit()
        
        print(f"✅ Journal entry created: {entry.entry_number} with status: {entry.status}")
        
        return jsonify({
            'message': 'Journal entry created successfully',
            'entry': {
                'id': entry.id,
                'entry_number': entry.entry_number,
                'status': entry.status
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error creating journal entry: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@journal_bp.route('/journal_entries/<int:entry_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_journal_entry(entry_id):
    """Handle GET, PUT, DELETE for a single journal entry"""
    if request.method == 'OPTIONS':
        return '', 200
    
    if request.method == 'GET':
        return get_journal_entry_by_id(entry_id)
    elif request.method == 'PUT':
        return update_journal_entry_by_id(entry_id)
    elif request.method == 'DELETE':
        return delete_journal_entry_by_id(entry_id)


def get_journal_entry_by_id(entry_id):
    """Get a single journal entry by ID"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        entry_dict = {
            'id': entry.id,
            'entry_number': entry.entry_number,
            'entry_date': entry.entry_date.isoformat() if entry.entry_date else None,
            'description': entry.description,
            'reference': entry.reference,
            'status': entry.status,
            'created_by': entry.created_by,
            'created_at': entry.created_at.isoformat() if entry.created_at else None,
        }
        
        if hasattr(entry, 'lines'):
            entry_dict['lines'] = [line.to_dict() for line in entry.lines]
            entry_dict['total_debit'] = sum(float(line.debit) for line in entry.lines)
            entry_dict['total_credit'] = sum(float(line.credit) for line in entry.lines)
            entry_dict['is_balanced'] = abs(entry_dict['total_debit'] - entry_dict['total_credit']) < 0.01
        
        creator = User.query.get(entry.created_by)
        entry_dict['created_by_name'] = creator.username if creator else 'Unknown'
        
        if hasattr(entry, 'posted_by') and entry.posted_by:
            poster = User.query.get(entry.posted_by)
            entry_dict['posted_by_name'] = poster.username if poster else 'Unknown'
        
        if hasattr(entry, 'posted_at') and entry.posted_at:
            entry_dict['posted_at'] = entry.posted_at.isoformat()
        
        if hasattr(entry, 'approved_by') and entry.approved_by:
            approver = User.query.get(entry.approved_by)
            entry_dict['approved_by_name'] = approver.username if approver else 'Unknown'
        
        if hasattr(entry, 'approved_at') and entry.approved_at:
            entry_dict['approved_at'] = entry.approved_at.isoformat()
        
        return jsonify(entry_dict), 200
        
    except Exception as e:
        logger.error(f"Error getting journal entry: {str(e)}")
        return jsonify({'error': 'Failed to get journal entry'}), 500


def update_journal_entry_by_id(entry_id):
    """Update a journal entry by ID"""
    try:
        user = g.current_user
        data = request.get_json()
        
        print(f"\n{'='*60}")
        print(f"📥 UPDATE JOURNAL ENTRY {entry_id}")
        print(f"{'='*60}")
        print(f"Request data: {json.dumps(data, indent=2)}")
        
        church_id = user.church_id if user.church_id else 1
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        if entry.status not in ['DRAFT', 'RETURNED']:
            return jsonify({'error': f'Cannot update entry with status {entry.status}'}), 400
        
        try:
            entry_date = datetime.fromisoformat(data['entry_date'].replace('Z', '+00:00'))
            entry.entry_date = entry_date
        except Exception as e:
            return jsonify({'error': f'Invalid date format: {str(e)}'}), 400
        
        entry.description = data['description']
        entry.reference = data.get('reference', '')
        
        # Delete existing lines
        JournalLine.query.filter_by(journal_entry_id=entry.id).delete()
        
        total_debit = 0
        total_credit = 0
        
        for line_data in data['lines']:
            debit = float(line_data.get('debit', 0))
            credit = float(line_data.get('credit', 0))
            
            total_debit += debit
            total_credit += credit
            
            line = JournalLine(
                journal_entry_id=entry.id,
                account_id=line_data['account_id'],
                debit=debit,
                credit=credit,
                description=line_data.get('description', '')
            )
            db.session.add(line)
        
        if abs(total_debit - total_credit) > 0.01:
            db.session.rollback()
            return jsonify({'error': f'Journal entry does not balance'}), 400
        
        if data.get('submit_for_approval', False):
            entry.status = 'PENDING'
        elif entry.status == 'DRAFT':
            entry.status = 'DRAFT'
        
        entry.updated_at = datetime.utcnow()
        db.session.commit()
        
        print(f"✅ Journal entry updated: {entry.entry_number}")
        
        return jsonify({
            'message': 'Journal entry updated successfully',
            'id': entry.id,
            'status': entry.status
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error updating journal entry: {str(e)}")
        return jsonify({'error': str(e)}), 500


def delete_journal_entry_by_id(entry_id):
    """Delete a draft journal entry"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        if entry.status != 'DRAFT':
            return jsonify({'error': f'Can only delete draft entries. Current status: {entry.status}'}), 400
        
        db.session.delete(entry)
        db.session.commit()
        
        return jsonify({'message': 'Journal entry deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting journal entry: {str(e)}")
        return jsonify({'error': str(e)}), 500


@journal_bp.route('/journal_entries/<int:entry_id>/post', methods=['POST'])
@token_required
def post_journal_entry(entry_id):
    """Post a journal entry - this updates account balances"""
    try:
        from decimal import Decimal
        
        church_id = ensure_user_church(g.current_user)
        user_id = g.current_user.id
        
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        if entry.status != 'APPROVED':
            return jsonify({'error': f'Cannot post entry with status: {entry.status}. Only APPROVED entries can be posted.'}), 400
        
        print(f"\n{'='*50}")
        print(f"POSTING JOURNAL ENTRY: {entry.entry_number}")
        print(f"{'='*50}")
        
        # Update account balances
        for line in entry.lines:
            account = Account.query.get(line.account_id)
            if not account:
                return jsonify({'error': f'Account {line.account_id} not found'}), 404
            
            # Convert all values to float
            old_balance = float(account.current_balance) if account.current_balance else 0.0
            debit = float(line.debit) if line.debit else 0.0
            credit = float(line.credit) if line.credit else 0.0
            
            print(f"  {account.name}: old={old_balance}, debit={debit}, credit={credit}")
            
            # Apply debit or credit based on account type
            if debit > 0:
                if account.account_type in ['ASSET', 'EXPENSE']:
                    new_balance = old_balance + debit
                else:
                    new_balance = old_balance - debit
                print(f"    Debit {debit} → {new_balance}")
            else:
                if account.account_type in ['LIABILITY', 'EQUITY', 'REVENUE']:
                    new_balance = old_balance + credit
                else:
                    new_balance = old_balance - credit
                print(f"    Credit {credit} → {new_balance}")
            
            # Update the account balance
            account.current_balance = new_balance
        
        # Update entry status
        entry.status = 'POSTED'
        entry.posted_by = user_id
        entry.posted_at = datetime.utcnow()
        
        db.session.commit()
        
        print(f"✅ Journal entry posted successfully")
        
        return jsonify({
            'message': 'Journal entry posted successfully',
            'id': entry.id,
            'status': 'POSTED'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error posting journal entry: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    

@journal_bp.route('/journal_entries/<int:entry_id>/approve', methods=['POST'])
@token_required
def approve_journal_entry(entry_id):
    """Approve a journal entry"""
    try:
        church_id = ensure_user_church(g.current_user)
        user_id = g.current_user.id
        
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        if entry.status != 'PENDING':
            return jsonify({'error': f'Cannot approve entry with status: {entry.status}'}), 400
        
        entry.status = 'APPROVED'
        entry.approved_by = user_id
        entry.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        print(f"✅ Journal entry approved: {entry.entry_number}")
        
        return jsonify({
            'message': 'Journal entry approved successfully',
            'id': entry.id,
            'status': 'APPROVED'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving journal entry: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Helper functions
def check_sufficient_balance(account_id, amount, transaction_type):
    """Check if an account has sufficient balance"""
    account = Account.query.get(account_id)
    if not account:
        return {'has_balance': False, 'message': f'Account not found'}
    
    current_balance = float(account.current_balance)
    
    if transaction_type == 'credit' and amount > current_balance:
        return {
            'has_balance': False,
            'message': f'Insufficient funds in {account.name}. Available: GHS {current_balance:,.2f}, Required: GHS {amount:,.2f}'
        }
    
    return {'has_balance': True, 'message': 'Sufficient balance'}


def validate_transaction_balances(lines_data):
    """Validate that all accounts have sufficient balance"""
    errors = []
    
    for i, line in enumerate(lines_data):
        account_id = line.get('account_id')
        credit = float(line.get('credit', 0))
        
        if credit > 0:
            account = Account.query.get(account_id)
            if account and account.account_type == 'ASSET':
                current_balance = float(account.current_balance or 0)
                if credit > current_balance:
                    errors.append(
                        f"Insufficient funds in {account.name}. "
                        f"Available: GHS {current_balance:,.2f}, Required: GHS {credit:,.2f}"
                    )
    
    return len(errors) == 0, errors