from flask import Blueprint, request, jsonify, g
from datetime import datetime
import logging
import traceback
from app.models import ApprovalRequest, Approval, ApprovalComment, ApprovalWorkflow, JournalEntry, JournalLine, Budget, User, Account
from app.extensions import db
from app.routes.auth_routes import token_required

logger = logging.getLogger(__name__)
approval_bp = Blueprint('approval', __name__)

# Helper function to check if user can approve
def can_approve(user, request_item):
    # Super admin and admin can approve anything
    if user.role in ['super_admin', 'admin']:
        return True
    
    # Check if user is the current approver based on workflow
    # This is simplified - you'd implement proper workflow logic
    if request_item.entity_type == 'journal_entry' and user.role == 'treasurer':
        return True
    if request_item.entity_type == 'budget' and user.role == 'pastor':
        return True
    if request_item.entity_type == 'expense' and user.role == 'treasurer':
        return True
    
    return False

@approval_bp.route('/accounting/approvals/pending', methods=['GET', 'OPTIONS'])
@token_required
def get_pending_approvals():
    """Get pending approvals for current user"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        user = g.current_user
        church_id = user.church_id
        entity_type = request.args.get('entity_type')
        
        print(f"\n{'='*60}")
        print(f"📥 GET PENDING APPROVALS")
        print(f"{'='*60}")
        print(f"👤 User ID: {user.id}, Role: {user.role}")
        print(f"📌 Entity type filter: {entity_type}")
        
        # Build query for pending approval requests
        query = ApprovalRequest.query.filter_by(
            church_id=church_id,
            status='PENDING'
        )
        
        if entity_type:
            query = query.filter_by(entity_type=entity_type)
        
        pending_requests = query.order_by(ApprovalRequest.requested_at.desc()).all()
        print(f"📊 Found {len(pending_requests)} total pending requests")
        
        approvals = []
        for req in pending_requests:
            print(f"\n🔍 Processing request ID {req.id}:")
            print(f"  Entity type: {req.entity_type}")
            print(f"  Entity ID: {req.entity_id}")
            
            if can_approve(user, req):
                print(f"  ✅ User can approve this request")
                
                entity = None
                amount = 0
                description = f'{req.entity_type} #{req.entity_id}'
                lines = []
                
                if req.entity_type == 'journal_entry':
                    entity = JournalEntry.query.get(req.entity_id)
                    if entity:
                        print(f"  ✅ Found journal entry: {entity.entry_number}")
                        print(f"  📊 Entry status: {entity.status}")
                        
                        # Calculate amount from lines
                        if entity.lines and len(entity.lines) > 0:
                            # Use either debit sum or credit sum (they should be equal)
                            amount = sum(float(line.debit) for line in entity.lines)
                            print(f"  📊 Entry amount: {amount}")
                            
                            # Get line details for display
                            for line in entity.lines:
                                account = Account.query.get(line.account_id)
                                lines.append({
                                    'account_id': line.account_id,
                                    'account_name': account.name if account else 'Unknown',
                                    'account_code': account.account_code if account else '',
                                    'debit': float(line.debit),
                                    'credit': float(line.credit),
                                    'description': line.description or ''
                                })
                        else:
                            print(f"  ⚠️ No lines found for this entry")
                        
                        description = entity.description or description
                
                elif req.entity_type == 'budget':
                    entity = Budget.query.get(req.entity_id)
                    if entity:
                        amount = float(entity.amount) if entity.amount else 0
                        description = entity.name or description
                
                # Get requester info
                requester = User.query.get(req.requested_by)
                requester_name = f"{requester.first_name} {requester.last_name}" if requester else 'Unknown'
                
                approval_data = {
                    'id': req.id,
                    'entity_id': req.entity_id,
                    'entity_type': req.entity_type,
                    'description': description,
                    'amount': float(amount),
                    'status': req.status,
                    'current_step': req.current_step,
                    'total_steps': req.total_steps,
                    'requester': requester_name,
                    'requester_id': req.requested_by,
                    'submitted_at': req.requested_at.isoformat() if req.requested_at else None,
                    'notes': entity.notes if entity and hasattr(entity, 'notes') else None,
                    'metadata': {
                        'description': description,
                        'total_amount': float(amount),
                        'lines': lines if req.entity_type == 'journal_entry' else []
                    }
                }
                
                approvals.append(approval_data)
                print(f"  ✅ Added approval data - Amount: {amount}")
            else:
                print(f"  ❌ User cannot approve this request (role: {user.role})")
        
        print(f"\n✅ Returning {len(approvals)} approvals")
        return jsonify({'approvals': approvals}), 200
        
    except Exception as e:
        print(f"❌ Error getting pending approvals: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': 'Failed to get pending approvals'}), 500
        
@approval_bp.route('/accounting/approvals/<int:request_id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_request(request_id):
    """Approve a request"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        user = g.current_user
        data = request.get_json() or {}
        comments = data.get('comments', '')
        
        print(f"\n{'='*60}")
        print(f"📤 APPROVE REQUEST {request_id}")
        print(f"{'='*60}")
        print(f"👤 User ID: {user.id}, Role: {user.role}")
        
        approval_req = ApprovalRequest.query.get(request_id)
        if not approval_req:
            print(f"❌ Approval request {request_id} not found")
            return jsonify({'error': 'Approval request not found'}), 404
        
        print(f"📌 Request: {approval_req.entity_type} #{approval_req.entity_id}")
        print(f"📊 Current status: {approval_req.status}")
        
        if not can_approve(user, approval_req):
            print(f"❌ User {user.id} not authorized to approve this request")
            return jsonify({'error': 'You are not authorized to approve this request'}), 403
        
        # Create approval record
        approval = Approval(
            request_id=request_id,
            approver_id=user.id,
            step_number=approval_req.current_step + 1,
            status='APPROVED',
            comments=comments,
            actioned_at=datetime.utcnow()
        )
        db.session.add(approval)
        
        # Update request
        approval_req.current_step += 1
        if approval_req.current_step >= approval_req.total_steps:
            approval_req.status = 'APPROVED'
            approval_req.completed_at = datetime.utcnow()
            
            # Update entity status
            if approval_req.entity_type == 'journal_entry':
                entry = JournalEntry.query.get(approval_req.entity_id)
                if entry:
                    entry.status = 'APPROVED'
                    entry.approval_status = 'APPROVED'
                    print(f"✅ Updated journal entry {entry.id} status to APPROVED")
            elif approval_req.entity_type == 'budget':
                budget = Budget.query.get(approval_req.entity_id)
                if budget:
                    budget.status = 'APPROVED'
                    print(f"✅ Updated budget {budget.id} status to APPROVED")
        
        db.session.commit()
        print(f"✅ Request {request_id} approved successfully")
        
        return jsonify({
            'message': 'Request approved successfully',
            'status': approval_req.status,
            'entity_id': approval_req.entity_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error approving request: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@approval_bp.route('/accounting/approvals/<int:request_id>/reject', methods=['POST', 'OPTIONS'])
@token_required
def reject_request(request_id):
    """Reject a request"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        user = g.current_user
        data = request.get_json() or {}
        comments = data.get('comments', '')
        
        if not comments:
            return jsonify({'error': 'Rejection reason is required'}), 400
        
        print(f"\n{'='*60}")
        print(f"📤 REJECT REQUEST {request_id}")
        print(f"{'='*60}")
        
        approval_req = ApprovalRequest.query.get(request_id)
        if not approval_req:
            return jsonify({'error': 'Approval request not found'}), 404
        
        if not can_approve(user, approval_req):
            return jsonify({'error': 'You are not authorized to reject this request'}), 403
        
        # Create approval record
        approval = Approval(
            request_id=request_id,
            approver_id=user.id,
            step_number=approval_req.current_step + 1,
            status='REJECTED',
            comments=comments,
            actioned_at=datetime.utcnow()
        )
        db.session.add(approval)
        
        # Update request
        approval_req.status = 'REJECTED'
        approval_req.completed_at = datetime.utcnow()
        
        # Update entity status
        if approval_req.entity_type == 'journal_entry':
            entry = JournalEntry.query.get(approval_req.entity_id)
            if entry:
                entry.status = 'REJECTED'
                entry.approval_status = 'REJECTED'
                print(f"✅ Updated journal entry {entry.id} status to REJECTED")
        elif approval_req.entity_type == 'budget':
            budget = Budget.query.get(approval_req.entity_id)
            if budget:
                budget.status = 'REJECTED'
        
        db.session.commit()
        
        return jsonify({
            'message': 'Request rejected',
            'status': approval_req.status,
            'entity_id': approval_req.entity_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error rejecting request: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@approval_bp.route('/accounting/approvals/<int:request_id>/return', methods=['POST', 'OPTIONS'])
@token_required
def return_request(request_id):
    """Return a request for correction"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        user = g.current_user
        data = request.get_json() or {}
        comments = data.get('comments', '')
        
        if not comments:
            return jsonify({'error': 'Return reason is required'}), 400
        
        print(f"\n{'='*60}")
        print(f"📤 RETURN REQUEST {request_id}")
        print(f"{'='*60}")
        
        approval_req = ApprovalRequest.query.get(request_id)
        if not approval_req:
            return jsonify({'error': 'Approval request not found'}), 404
        
        if not can_approve(user, approval_req):
            return jsonify({'error': 'You are not authorized to return this request'}), 403
        
        # Create approval record
        approval = Approval(
            request_id=request_id,
            approver_id=user.id,
            step_number=approval_req.current_step + 1,
            status='RETURNED',
            comments=comments,
            actioned_at=datetime.utcnow()
        )
        db.session.add(approval)
        
        # Update request
        approval_req.status = 'RETURNED'
        
        # Update entity status
        if approval_req.entity_type == 'journal_entry':
            entry = JournalEntry.query.get(approval_req.entity_id)
            if entry:
                entry.status = 'RETURNED'
                entry.approval_status = 'RETURNED'
                print(f"✅ Updated journal entry {entry.id} status to RETURNED")
        elif approval_req.entity_type == 'budget':
            budget = Budget.query.get(approval_req.entity_id)
            if budget:
                budget.status = 'RETURNED'
        
        db.session.commit()
        
        return jsonify({
            'message': 'Request returned for correction',
            'status': approval_req.status,
            'entity_id': approval_req.entity_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error returning request: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@approval_bp.route('/accounting/approvals/submit', methods=['POST', 'OPTIONS'])
@token_required
def submit_for_approval():
    """Submit an entity for approval"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        print("\n" + "="*60)
        print("📥 SUBMIT FOR APPROVAL - REQUEST RECEIVED")
        print("="*60)
        
        user = g.current_user
        print(f"👤 User ID: {user.id}")
        print(f"👤 User Role: {user.role}")
        print(f"👤 User Church ID: {user.church_id}")
        
        data = request.get_json()
        print(f"📦 Request data: {data}")
        
        entity_type = data.get('entity_type')
        entity_id = data.get('entity_id')
        notes = data.get('notes', '')
        
        print(f"📌 Entity Type: {entity_type}")
        print(f"📌 Entity ID: {entity_id}")
        print(f"📌 Notes: {notes}")
        
        if not entity_type or not entity_id:
            print("❌ Missing entity type or ID")
            return jsonify({'error': 'Entity type and ID are required'}), 400
        
        # Check if entity exists
        entity = None
        if entity_type == 'journal_entry':
            print("🔍 Looking for journal entry...")
            entity = JournalEntry.query.get(entity_id)
            if entity:
                print(f"✅ Found journal entry: {entity.entry_number}")
                print(f"📊 Current status: {entity.status}")
                
                # Check if entry can be submitted
                if entity.status not in ['DRAFT', 'RETURNED']:
                    print(f"❌ Cannot submit entry with status {entity.status}")
                    return jsonify({'error': f'Cannot submit entry with status {entity.status}'}), 400
                
                entity.status = 'PENDING'
                entity.approval_status = 'PENDING'
            else:
                print(f"❌ Journal entry {entity_id} not found")
                return jsonify({'error': 'Journal entry not found'}), 404
                
        elif entity_type == 'budget':
            print("🔍 Looking for budget...")
            entity = Budget.query.get(entity_id)
            if entity:
                print(f"✅ Found budget: {entity.name}")
                print(f"📊 Current status: {entity.status}")
                
                if entity.status not in ['DRAFT', 'RETURNED']:
                    print(f"❌ Cannot submit budget with status {entity.status}")
                    return jsonify({'error': f'Cannot submit budget with status {entity.status}'}), 400
                
                entity.status = 'PENDING'
            else:
                print(f"❌ Budget {entity_id} not found")
                return jsonify({'error': 'Budget not found'}), 404
        else:
            print(f"❌ Invalid entity type: {entity_type}")
            return jsonify({'error': 'Invalid entity type'}), 400
        
        # Create approval request
        print("📝 Creating approval request...")
        approval_req = ApprovalRequest(
            church_id=user.church_id,
            entity_type=entity_type,
            entity_id=entity_id,
            current_step=0,
            total_steps=1,  # Simplified - would come from workflow config
            status='PENDING',
            requested_by=user.id,
            requested_at=datetime.utcnow()
        )
        db.session.add(approval_req)
        db.session.flush()  # Get the ID
        
        # Create initial approval record
        approval = Approval(
            request_id=approval_req.id,
            step_number=1,
            status='PENDING',
            approver_id=None,
            comments=notes if notes else None
        )
        db.session.add(approval)
        
        print(f"✅ Approval request created with ID: {approval_req.id}")
        
        # Commit the transaction
        print("💾 Committing to database...")
        db.session.commit()
        print("✅ Database commit successful")
        
        return jsonify({
            'message': 'Submitted for approval',
            'request_id': approval_req.id,
            'entity_id': entity_id,
            'entity_type': entity_type,
            'status': 'PENDING'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ ERROR: {str(e)}")
        print(f"❌ Error type: {type(e).__name__}")
        print("❌ Traceback:")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@approval_bp.route('/accounting/approvals/history', methods=['GET', 'OPTIONS'])
@token_required
def get_approval_history():
    """Get approval history for an entity"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        entity_type = request.args.get('entity_type')
        entity_id = request.args.get('entity_id', type=int)
        
        if not entity_type or not entity_id:
            return jsonify({'error': 'Entity type and ID are required'}), 400
        
        approval_req = ApprovalRequest.query.filter_by(
            entity_type=entity_type,
            entity_id=entity_id
        ).first()
        
        if not approval_req:
            return jsonify({'history': []}), 200
        
        approvals = Approval.query.filter_by(request_id=approval_req.id).order_by(Approval.step_number).all()
        
        history = []
        for approval in approvals:
            approver = User.query.get(approval.approver_id)
            history.append({
                'action': approval.status,
                'user': approver.full_name if approver else 'Unknown',
                'comments': approval.comments,
                'timestamp': approval.actioned_at.isoformat() if approval.actioned_at else None
            })
        
        return jsonify({'history': history}), 200
        
    except Exception as e:
        logger.error(f"Error getting approval history: {str(e)}")
        return jsonify({'error': str(e)}), 500