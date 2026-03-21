from flask import Blueprint, make_response, request, jsonify, g
from datetime import datetime
import logging
import traceback
import json
from sqlalchemy import func
from decimal import Decimal

from app.models import JournalEntry, JournalLine, Account, AuditLog, User
from app.extensions import db
from app.routes.auth_routes import token_required

logger = logging.getLogger(__name__)
journal_bp = Blueprint('journal', __name__)

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


@journal_bp.route('/journal_entries', methods=['GET', 'OPTIONS'])
@token_required
def get_journal_entries():
    """Get journal entries with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
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
            # Build entry dict
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
            
            # Safely add poster info
            if hasattr(entry, 'posted_by') and entry.posted_by is not None:
                poster = User.query.get(entry.posted_by)
                entry_dict['posted_by_name'] = poster.username if poster else 'Unknown'
            else:
                entry_dict['posted_by_name'] = None
                
            if hasattr(entry, 'posted_at') and entry.posted_at:
                entry_dict['posted_at'] = entry.posted_at.isoformat()
            else:
                entry_dict['posted_at'] = None
            
            # Safely add approver info
            if hasattr(entry, 'approved_by') and entry.approved_by is not None:
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
        
        # Generate entry number
        entry_number = generate_entry_number(user.church_id)
        
        # Parse entry date
        try:
            entry_date = datetime.fromisoformat(data['entry_date'].replace('Z', '+00:00'))
        except Exception as e:
            return jsonify({'error': f'Invalid date format: {str(e)}'}), 400
        
        # Create the journal entry
        entry = JournalEntry(
            church_id=user.church_id,
            entry_number=entry_number,
            entry_date=entry_date,
            description=data['description'],
            reference=data.get('reference', ''),
            status='DRAFT',  # Start as DRAFT
            created_by=user.id,
            created_at=datetime.utcnow()
        )
        
        db.session.add(entry)
        db.session.flush()  # Get the entry ID
        
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
        
        # Check for sufficient funds if submitting for approval
        if data.get('submit_for_approval', False):
            is_valid, balance_errors = validate_transaction_balances(data.get('lines', []))
            if not is_valid:
                db.session.rollback()
                return jsonify({
                    'error': 'Insufficient funds',
                    'details': balance_errors,
                    'code': 'INSUFFICIENT_FUNDS'
                }), 400
            
            # Update entry status to PENDING
            entry.status = 'PENDING'
            
            # ===== CREATE APPROVAL REQUEST =====
            try:
                # Import ApprovalRequest model
                from app.models import ApprovalRequest
                
                # Create approval request
                approval_request = ApprovalRequest(
                    church_id=user.church_id,
                    entity_type='journal_entry',
                    entity_id=entry.id,
                    requester_id=user.id,
                    status='PENDING',
                    submitted_at=datetime.utcnow(),
                    # You may need to set these based on your workflow
                    current_step=1,
                    total_steps=2,  # Accountant -> Treasurer
                    description=f"Journal Entry: {entry.description}",
                    amount=total_debit  # Total amount
                )
                
                db.session.add(approval_request)
                print(f"✅ Created approval request for journal entry {entry.id}")
                
            except ImportError as e:
                print(f"⚠️ Could not import ApprovalRequest model: {e}")
            except Exception as e:
                print(f"⚠️ Error creating approval request: {e}")
                # Continue even if approval request fails
                pass
        
        db.session.commit()
        
        # Log audit
        try:
            audit_log = AuditLog(
                user_id=user.id,
                action='CREATE_JOURNAL_ENTRY',
                resource='journal',
                resource_id=entry.id,
                data={'entry_number': entry.entry_number},
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string
            )
            db.session.add(audit_log)
            db.session.commit()
        except Exception as e:
            print(f"⚠️ Could not create audit log: {e}")
            pass
        
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

@journal_bp.route('/journal_entries/<int:entry_id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_journal_entry(entry_id):
    """Approve a journal entry (Treasurer action)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        user_id = g.current_user.id
        data = request.get_json() or {}
        
        comments = data.get('comments', '')
        
        # Find the journal entry
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        # Check if entry is in PENDING status
        if entry.status != 'PENDING':
            return jsonify({'error': f'Cannot approve entry with status: {entry.status}. Only PENDING entries can be approved.'}), 400
        
        print("="*50)
        print(f"✅ APPROVING JOURNAL ENTRY: {entry.entry_number}")
        print("="*50)
        
        # Update entry status to APPROVED
        entry.status = 'APPROVED'
        entry.approved_by = user_id
        entry.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=user_id,
            action='APPROVE_JOURNAL_ENTRY',
            resource='journal',
            resource_id=entry.id,
            data={'entry_number': entry.entry_number, 'comments': comments},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        print(f"✅ Journal entry approved successfully")
        
        return jsonify({
            'message': 'Journal entry approved successfully',
            'entry': {
                'id': entry.id,
                'entry_number': entry.entry_number,
                'status': 'APPROVED'
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving journal entry: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@journal_bp.route('/journal_entries/<int:entry_id>/reject', methods=['POST', 'OPTIONS'])
@token_required
def reject_journal_entry(entry_id):
    """Reject a journal entry"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        user_id = g.current_user.id
        data = request.get_json() or {}
        
        reason = data.get('reason', 'No reason provided')
        
        # Find the journal entry
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        # Check if entry is in PENDING status
        if entry.status != 'PENDING':
            return jsonify({'error': f'Cannot reject entry with status: {entry.status}. Only PENDING entries can be rejected.'}), 400
        
        print("="*50)
        print(f"❌ REJECTING JOURNAL ENTRY: {entry.entry_number}")
        print("="*50)
        
        # Update entry status to REJECTED
        entry.status = 'REJECTED'
        entry.rejected_by = user_id
        entry.rejected_at = datetime.utcnow()
        entry.rejection_reason = reason
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=user_id,
            action='REJECT_JOURNAL_ENTRY',
            resource='journal',
            resource_id=entry.id,
            data={'entry_number': entry.entry_number, 'reason': reason},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        print(f"✅ Journal entry rejected successfully")
        
        return jsonify({
            'message': 'Journal entry rejected successfully',
            'entry': {
                'id': entry.id,
                'entry_number': entry.entry_number,
                'status': 'REJECTED'
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting journal entry: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@journal_bp.route('/journal_entries/<int:entry_id>/return', methods=['POST', 'OPTIONS'])
@token_required
def return_journal_entry(entry_id):
    """Return a journal entry for correction"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        user_id = g.current_user.id
        data = request.get_json() or {}
        
        feedback = data.get('feedback', 'Please correct and resubmit')
        
        # Find the journal entry
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        # Check if entry is in PENDING status
        if entry.status != 'PENDING':
            return jsonify({'error': f'Cannot return entry with status: {entry.status}. Only PENDING entries can be returned.'}), 400
        
        print("="*50)
        print(f"🔄 RETURNING JOURNAL ENTRY: {entry.entry_number}")
        print("="*50)
        
        # Update entry status to RETURNED
        entry.status = 'RETURNED'
        entry.returned_by = user_id
        entry.returned_at = datetime.utcnow()
        entry.return_feedback = feedback
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=user_id,
            action='RETURN_JOURNAL_ENTRY',
            resource='journal',
            resource_id=entry.id,
            data={'entry_number': entry.entry_number, 'feedback': feedback},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        print(f"✅ Journal entry returned for correction")
        
        return jsonify({
            'message': 'Journal entry returned for correction',
            'entry': {
                'id': entry.id,
                'entry_number': entry.entry_number,
                'status': 'RETURNED'
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error returning journal entry: {str(e)}")
        logger.error(traceback.format_exc())
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
        church_id = g.current_user.church_id
        
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        # Build entry dictionary
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
        
        # Add lines
        if hasattr(entry, 'lines'):
            entry_dict['lines'] = [line.to_dict() for line in entry.lines]
            entry_dict['total_debit'] = sum(float(line.debit) for line in entry.lines)
            entry_dict['total_credit'] = sum(float(line.credit) for line in entry.lines)
            entry_dict['is_balanced'] = abs(entry_dict['total_debit'] - entry_dict['total_credit']) < 0.01
        
        # Add creator info
        creator = User.query.get(entry.created_by)
        entry_dict['created_by_name'] = creator.username if creator else 'Unknown'
        
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
        
        # Add void info
        if hasattr(entry, 'voided_by') and entry.voided_by:
            voider = User.query.get(entry.voided_by)
            entry_dict['voided_by_name'] = voider.username if voider else 'Unknown'
        else:
            entry_dict['voided_by_name'] = None
            
        if hasattr(entry, 'voided_at') and entry.voided_at:
            entry_dict['voided_at'] = entry.voided_at.isoformat()
        else:
            entry_dict['voided_at'] = None
            
        if hasattr(entry, 'void_reason') and entry.void_reason:
            entry_dict['void_reason'] = entry.void_reason
        else:
            entry_dict['void_reason'] = None
        
        return jsonify(entry_dict), 200
        
    except Exception as e:
        logger.error(f"Error getting journal entry: {str(e)}")
        logger.error(traceback.format_exc())
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
        
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=user.church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        # Check if entry can be updated
        if entry.status not in ['DRAFT', 'RETURNED']:
            return jsonify({'error': f'Cannot update entry with status {entry.status}'}), 400
        
        # Parse entry date
        try:
            entry_date = datetime.fromisoformat(data['entry_date'].replace('Z', '+00:00'))
        except Exception as e:
            return jsonify({'error': f'Invalid date format: {str(e)}'}), 400
        
        # Update entry fields
        entry.entry_date = entry_date
        entry.description = data['description']
        entry.reference = data.get('reference', '')
        
        # Delete existing lines
        JournalLine.query.filter_by(journal_entry_id=entry.id).delete()
        
        # Add new lines
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
        
        # Check for sufficient funds if submitting for approval
        if data.get('submit_for_approval', False):
            is_valid, balance_errors = validate_transaction_balances(data.get('lines', []))
            if not is_valid:
                db.session.rollback()
                return jsonify({
                    'error': 'Insufficient funds',
                    'details': balance_errors,
                    'code': 'INSUFFICIENT_FUNDS'
                }), 400
            entry.status = 'PENDING'
        
        entry.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=user.id,
            action='UPDATE_JOURNAL_ENTRY',
            resource='journal',
            resource_id=entry.id,
            data={'entry_number': entry.entry_number},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        print(f"✅ Journal entry updated: {entry.entry_number}")
        
        return jsonify({
            'message': 'Journal entry updated successfully',
            'entry': {
                'id': entry.id,
                'entry_number': entry.entry_number,
                'status': entry.status
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error updating journal entry: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def delete_journal_entry_by_id(entry_id):
    """Delete a draft journal entry"""
    try:
        church_id = g.current_user.church_id
        user_id = g.current_user.id
        
        # Find the journal entry
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        if entry.status != 'DRAFT':
            return jsonify({'error': f'Can only delete draft entries. Current status: {entry.status}'}), 400
        
        # Delete the entry (cascade will delete lines)
        db.session.delete(entry)
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=user_id,
            action='DELETE_JOURNAL_ENTRY',
            resource='journal',
            resource_id=entry_id,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Journal entry deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting journal entry: {str(e)}")
        return jsonify({'error': str(e)}), 500


@journal_bp.route('/journal_entries/<int:entry_id>/post', methods=['POST', 'OPTIONS'])
@token_required
def post_journal_entry(entry_id):
    """Post a journal entry - this updates account balances"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        user_id = g.current_user.id
        
        # Find the journal entry
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        # Allow posting from APPROVED status only
        if entry.status != 'APPROVED':
            return jsonify({'error': f'Cannot post entry with status: {entry.status}. Only APPROVED entries can be posted.'}), 400
        
        print("="*50)
        print(f"POSTING JOURNAL ENTRY: {entry.entry_number}")
        print("="*50)
        
        # Update account balances
        for line in entry.lines:
            account = Account.query.get(line.account_id)
            if not account:
                return jsonify({'error': f'Account {line.account_id} not found'}), 404
            
            old_balance = float(account.current_balance)
            
            # Apply debit or credit based on account type
            if line.debit > 0:
                # Debit increases asset/expense
                if account.account_type in ['ASSET', 'EXPENSE']:
                    account.current_balance += line.debit
                else:
                    account.current_balance -= line.debit
                print(f"  Debit {float(line.debit)} to {account.name}: {old_balance} -> {float(account.current_balance)}")
            else:
                # Credit increases liability/equity/revenue, decreases asset/expense
                if account.account_type in ['LIABILITY', 'EQUITY', 'REVENUE']:
                    account.current_balance += line.credit
                else:
                    account.current_balance -= line.credit
                print(f"  Credit {float(line.credit)} to {account.name}: {old_balance} -> {float(account.current_balance)}")
        
        # Update entry status
        entry.status = 'POSTED'
        entry.posted_by = user_id
        entry.posted_at = datetime.utcnow()
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=user_id,
            action='POST_JOURNAL_ENTRY',
            resource='journal',
            resource_id=entry.id,
            data={'entry_number': entry.entry_number},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        print(f"✅ Journal entry posted successfully")
        
        return jsonify({
            'message': 'Journal entry posted successfully',
            'entry': {
                'id': entry.id,
                'entry_number': entry.entry_number,
                'status': 'POSTED'
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error posting journal entry: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@journal_bp.route('/journal_entries/<int:entry_id>/void', methods=['POST', 'OPTIONS'])
@token_required
def void_journal_entry(entry_id):
    """Void a journal entry - reverses the effect on accounts"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        user_id = g.current_user.id
        data = request.get_json() or {}
        
        reason = data.get('reason', 'No reason provided')
        
        # Find the journal entry
        entry = JournalEntry.query.filter_by(
            id=entry_id,
            church_id=church_id
        ).first()
        
        if not entry:
            return jsonify({'error': 'Journal entry not found'}), 404
        
        if entry.status != 'POSTED':
            return jsonify({'error': f'Can only void posted entries. Current status: {entry.status}'}), 400
        
        print("="*50)
        print(f"VOIDING JOURNAL ENTRY: {entry.entry_number}")
        print("="*50)
        
        # Reverse account balances
        for line in entry.lines:
            account = Account.query.get(line.account_id)
            if not account:
                return jsonify({'error': f'Account {line.account_id} not found'}), 404
            
            old_balance = float(account.current_balance)
            
            # Reverse the effect
            if line.debit > 0:
                # Original was debit, so credit to reverse
                if account.account_type in ['ASSET', 'EXPENSE']:
                    account.current_balance -= line.debit
                else:
                    account.current_balance += line.debit
                print(f"  Reverse debit {float(line.debit)} to {account.name}: {old_balance} -> {float(account.current_balance)}")
            else:
                # Original was credit, so debit to reverse
                if account.account_type in ['LIABILITY', 'EQUITY', 'REVENUE']:
                    account.current_balance -= line.credit
                else:
                    account.current_balance += line.credit
                print(f"  Reverse credit {float(line.credit)} to {account.name}: {old_balance} -> {float(account.current_balance)}")
        
        # Update entry status
        entry.status = 'VOID'
        entry.voided_by = user_id
        entry.voided_at = datetime.utcnow()
        entry.void_reason = reason
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=user_id,
            action='VOID_JOURNAL_ENTRY',
            resource='journal',
            resource_id=entry.id,
            data={'entry_number': entry.entry_number, 'reason': reason},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        print(f"✅ Journal entry voided successfully")
        
        return jsonify({
            'message': 'Journal entry voided successfully',
            'entry': {
                'id': entry.id,
                'entry_number': entry.entry_number,
                'status': 'VOID'
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error voiding journal entry: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@journal_bp.route('/journal/accounts', methods=['GET', 'OPTIONS'])
@token_required
def get_journal_accounts():
    """Get accounts for journal entry selection"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        accounts = Account.query.filter_by(
            church_id=church_id,
            is_active=True
        ).order_by(Account.account_code).all()
        
        account_list = []
        for acc in accounts:
            account_list.append({
                'id': acc.id,
                'code': acc.account_code,
                'name': acc.name,
                'type': acc.account_type,
                'balance': float(acc.current_balance)
            })
        
        return jsonify({'accounts': account_list}), 200
        
    except Exception as e:
        logger.error(f"Error getting accounts: {str(e)}")
        return jsonify({'error': 'Failed to get accounts'}), 500


@journal_bp.route('/journal/validate', methods=['POST', 'OPTIONS'])
@token_required
def validate_journal_entry():
    """Validate a journal entry without saving"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        church_id = g.current_user.church_id
        
        if not data.get('lines') or len(data['lines']) < 2:
            return jsonify({
                'valid': False,
                'error': 'At least two journal lines are required'
            }), 400
        
        total_debit = Decimal('0')
        total_credit = Decimal('0')
        line_errors = []
        
        for i, line in enumerate(data['lines']):
            account_id = line.get('account_id')
            debit = Decimal(str(line.get('debit', 0)))
            credit = Decimal(str(line.get('credit', 0)))
            
            # Validate account
            if not account_id:
                line_errors.append(f'Line {i+1}: Account ID is required')
                continue
            
            account = Account.query.filter_by(
                id=account_id,
                church_id=church_id,
                is_active=True
            ).first()
            
            if not account:
                line_errors.append(f'Line {i+1}: Account not found or inactive')
                continue
            
            # Validate debit/credit
            if debit > 0 and credit > 0:
                line_errors.append(f'Line {i+1}: Cannot have both debit and credit')
            
            if debit == 0 and credit == 0:
                line_errors.append(f'Line {i+1}: Must have either debit or credit amount')
            
            total_debit += debit
            total_credit += credit
        
        if line_errors:
            return jsonify({
                'valid': False,
                'errors': line_errors
            }), 400
        
        if total_debit != total_credit:
            return jsonify({
                'valid': False,
                'error': f'Journal entry does not balance: Debits ({float(total_debit)}) must equal Credits ({float(total_credit)})'
            }), 400
        
        return jsonify({
            'valid': True,
            'total_debit': float(total_debit),
            'total_credit': float(total_credit)
        }), 200
        
    except Exception as e:
        logger.error(f"Error validating journal entry: {str(e)}")
        return jsonify({'valid': False, 'error': str(e)}), 500


@journal_bp.route('/journal_entries/export', methods=['GET', 'OPTIONS'])
@token_required
def export_journal_entries():
    """Export journal entries to CSV"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        # Get filter parameters
        start_date = request.args.get('startDate')
        end_date = request.args.get('endDate')
        status = request.args.get('status')
        
        # Build query
        query = JournalEntry.query.filter_by(church_id=church_id)
        
        if start_date:
            query = query.filter(JournalEntry.entry_date >= datetime.fromisoformat(start_date))
        
        if end_date:
            end = datetime.fromisoformat(end_date)
            end = end.replace(hour=23, minute=59, second=59)
            query = query.filter(JournalEntry.entry_date <= end)
        
        if status:
            query = query.filter(JournalEntry.status == status.upper())
        
        # Order by date
        entries = query.order_by(JournalEntry.entry_date.desc()).all()
        
        # Create CSV
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        writer.writerow([
            'Entry Number', 'Date', 'Description', 'Reference', 
            'Status', 'Total Debit', 'Total Credit', 'Created By', 'Created At'
        ])
        
        # Write data
        for entry in entries:
            creator = User.query.get(entry.created_by)
            writer.writerow([
                entry.entry_number,
                entry.entry_date.strftime('%Y-%m-%d'),
                entry.description or '',
                entry.reference or '',
                entry.status,
                sum(float(line.debit) for line in entry.lines),
                sum(float(line.credit) for line in entry.lines),
                creator.username if creator else 'Unknown',
                entry.created_at.strftime('%Y-%m-%d %H:%M:%S') if entry.created_at else ''
            ])
        
        # Prepare response
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=journal_entries_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting journal entries: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Failed to export journal entries'}), 500


# ============ Helper for insufficient fund ===============
def check_sufficient_balance(account_id, amount, transaction_type, lines_data=None):
    """
    Check if an account has sufficient balance for a transaction.
    
    Args:
        account_id: The account ID to check
        amount: The amount to be deducted
        transaction_type: 'debit' or 'credit'
        lines_data: Optional - full lines data for complex transactions
    """
    account = Account.query.get(account_id)
    if not account:
        return {'has_balance': False, 'message': f'Account {account_id} not found'}
    
    current_balance = float(account.current_balance)
    
    # For cash and bank accounts (ASSET type)
    if account.account_type == 'ASSET':
        # If we're crediting (decreasing) the account
        if transaction_type == 'credit' and amount > current_balance:
            return {
                'has_balance': False,
                'message': f'Insufficient funds in {account.name}. Available: GHS {current_balance:,.2f}, Required: GHS {amount:,.2f}'
            }
    
    return {'has_balance': True, 'message': 'Sufficient balance'}

def validate_transaction_balances(lines_data):
    """
    Validate that all accounts have sufficient balance for the transaction.
    Returns (is_valid, error_messages)
    """
    errors = []
    
    for i, line in enumerate(lines_data):
        account_id = line.get('account_id')
        if not account_id:
            errors.append(f"Line {i+1}: Account ID is required")
            continue
            
        debit = float(line.get('debit', 0))
        credit = float(line.get('credit', 0))
        
        account = Account.query.get(account_id)
        if not account:
            errors.append(f"Line {i+1}: Account {account_id} not found")
            continue
        
        # Check if this line will decrease an asset account (cash/bank)
        if credit > 0 and account.account_type == 'ASSET':
            current_balance = float(account.current_balance or 0)
            if credit > current_balance:
                errors.append(
                    f"Insufficient funds in {account.name}. "
                    f"Available: GHS {current_balance:,.2f}, Required: GHS {credit:,.2f}"
                )
    
    return len(errors) == 0, errors