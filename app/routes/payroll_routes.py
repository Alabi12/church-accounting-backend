# app/routes/payroll_routes.py
from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import PayrollRun, PayrollLine, Employee, User, AuditLog, JournalEntry, JournalLine, Account
from app.extensions import db
from datetime import datetime
from decimal import Decimal
import traceback
import logging
import os
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)
payroll_bp = Blueprint('payroll', __name__)

from app.routes.auth_routes import token_required

def get_current_user():
    try:
        user_id = get_jwt_identity()
        if user_id:
            return User.query.get(int(user_id))
    except Exception as e:
        logger.warning(f"Error getting user from JWT: {e}")
    return None


# ==================== PAYROLL RUN CRUD ====================

@payroll_bp.route('/runs', methods=['GET', 'OPTIONS'])
@token_required
def get_payroll_runs():
    """Get all payroll runs with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        status = request.args.get('status')
        
        query = PayrollRun.query.filter_by(church_id=church_id)
        
        if status and status != 'all':
            query = query.filter_by(status=status)
        
        runs = query.order_by(PayrollRun.created_at.desc()).all()
        
        return jsonify({
            'runs': [run.to_dict() for run in runs],
            'total': len(runs)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting payroll runs: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs', methods=['POST', 'OPTIONS'])
@token_required
def create_payroll_run():
    """Create a new payroll run (Accountant only)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin', 'accountant']:
            return jsonify({'error': 'Permission denied'}), 403
        
        data = request.get_json()
        
        # Generate run number
        year = datetime.now().year
        month = datetime.now().month
        count = PayrollRun.query.filter(
            PayrollRun.run_number.like(f'PR-{year}-{month:02d}%')
        ).count() + 1
        run_number = f"PR-{year}-{month:02d}-{count:03d}"
        
        payroll_run = PayrollRun(
            church_id=g.current_user.church_id,
            run_number=run_number,
            period_start=datetime.fromisoformat(data['period_start']).date(),
            period_end=datetime.fromisoformat(data['period_end']).date(),
            payment_date=datetime.fromisoformat(data['payment_date']).date(),
            status='DRAFT'
        )
        
        db.session.add(payroll_run)
        db.session.flush()
        
        # Add employees to payroll run
        employees = Employee.query.filter_by(church_id=g.current_user.church_id, is_active=True).all()
        
        total_gross = Decimal('0')
        total_deductions = Decimal('0')
        total_net = Decimal('0')
        
        for emp in employees:
            line = PayrollLine(
                payroll_run_id=payroll_run.id,
                employee_id=emp.id,
                basic_salary=emp.basic_salary or 0,
                allowances=emp.allowances or 0
            )
            db.session.add(line)
            
            total_gross += line.basic_salary + line.allowances
            total_deductions += line.paye_tax + line.ssnit_employee + line.provident_fund
            total_net += (line.basic_salary + line.allowances) - total_deductions
        
        payroll_run.gross_pay = total_gross
        payroll_run.total_deductions = total_deductions
        payroll_run.net_pay = total_net
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll run created',
            'run': payroll_run.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating payroll run: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==================== PAYROLL WORKFLOW ====================

@payroll_bp.route('/runs/<int:run_id>/submit', methods=['POST', 'OPTIONS'])
@token_required
def submit_payroll_run(run_id):
    """Submit payroll run for review (Accountant)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin', 'accountant']:
            return jsonify({'error': 'Permission denied'}), 403
        
        payroll_run = PayrollRun.query.get(run_id)
        if not payroll_run or payroll_run.church_id != g.current_user.church_id:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if not payroll_run.can_submit():
            return jsonify({'error': f'Cannot submit payroll run with status {payroll_run.status}'}), 400
        
        payroll_run.status = 'SUBMITTED'
        payroll_run.submitted_by = current_user.id
        payroll_run.submitted_at = datetime.utcnow()
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=current_user.id,
            action='SUBMIT_PAYROLL',
            resource='payroll_run',
            resource_id=run_id,
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll run submitted for review',
            'run': payroll_run.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting payroll: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/<int:run_id>/review', methods=['POST', 'OPTIONS'])
@token_required
def review_payroll_run(run_id):
    """Review payroll run (Accountant/Treasurer can review)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        data = request.get_json()
        
        payroll_run = PayrollRun.query.get(run_id)
        if not payroll_run or payroll_run.church_id != g.current_user.church_id:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if not payroll_run.can_review():
            return jsonify({'error': f'Cannot review payroll run with status {payroll_run.status}'}), 400
        
        payroll_run.status = 'REVIEWED'
        payroll_run.reviewed_by = current_user.id
        payroll_run.reviewed_at = datetime.utcnow()
        payroll_run.review_comments = data.get('comments')
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll run reviewed',
            'run': payroll_run.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error reviewing payroll: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/<int:run_id>/return', methods=['POST', 'OPTIONS'])
@token_required
def return_payroll_run(run_id):
    """Return payroll run for corrections (Accountant/Treasurer)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        data = request.get_json()
        reason = data.get('reason', 'No reason provided')
        
        payroll_run = PayrollRun.query.get(run_id)
        if not payroll_run or payroll_run.church_id != g.current_user.church_id:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if not payroll_run.can_return():
            return jsonify({'error': f'Cannot return payroll run with status {payroll_run.status}'}), 400
        
        payroll_run.status = 'RETURNED'
        payroll_run.returned_by = current_user.id
        payroll_run.returned_at = datetime.utcnow()
        payroll_run.return_reason = reason
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll run returned for corrections',
            'run': payroll_run.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error returning payroll: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/<int:run_id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_payroll_run(run_id):
    """Approve payroll run (Treasurer only)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin', 'treasurer']:
            return jsonify({'error': 'Only treasurer can approve payroll'}), 403
        
        data = request.get_json()
        
        payroll_run = PayrollRun.query.get(run_id)
        if not payroll_run or payroll_run.church_id != g.current_user.church_id:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if not payroll_run.can_approve():
            return jsonify({'error': f'Cannot approve payroll run with status {payroll_run.status}'}), 400
        
        payroll_run.status = 'APPROVED'
        payroll_run.approved_by = current_user.id
        payroll_run.approved_at = datetime.utcnow()
        payroll_run.approval_comments = data.get('comments')
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll run approved',
            'run': payroll_run.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving payroll: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/<int:run_id>/process', methods=['POST', 'OPTIONS'])
@token_required
def process_payroll_run(run_id):
    """Process payroll run (Accountant only) - Posts to ledger"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin', 'accountant']:
            return jsonify({'error': 'Permission denied'}), 403
        
        payroll_run = PayrollRun.query.get(run_id)
        if not payroll_run or payroll_run.church_id != g.current_user.church_id:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if not payroll_run.can_process():
            return jsonify({'error': f'Cannot process payroll run with status {payroll_run.status}'}), 400
        
        # Create journal entry
        journal_entry = JournalEntry(
            church_id=g.current_user.church_id,
            entry_number=f"JE-PR-{payroll_run.run_number}",
            entry_date=datetime.utcnow().date(),
            description=f"Payroll for period {payroll_run.period_start} to {payroll_run.period_end}",
            status='POSTED',
            created_by=current_user.id
        )
        db.session.add(journal_entry)
        db.session.flush()
        
        # Post to ledger accounts
        # Debit: Salary Expense
        salary_expense = Account.query.filter_by(
            church_id=g.current_user.church_id,
            account_code='5100'
        ).first()
        
        # Credit: Bank/Cash
        bank_account = Account.query.filter_by(
            church_id=g.current_user.church_id,
            account_type='ASSET',
            category='Bank'
        ).first()
        
        if salary_expense and bank_account:
            line = JournalLine(
                journal_entry_id=journal_entry.id,
                account_id=salary_expense.id,
                debit=payroll_run.gross_pay,
                credit=0
            )
            db.session.add(line)
            
            line2 = JournalLine(
                journal_entry_id=journal_entry.id,
                account_id=bank_account.id,
                debit=0,
                credit=payroll_run.net_pay
            )
            db.session.add(line2)
        
        payroll_run.status = 'PROCESSED'
        payroll_run.processed_by = current_user.id
        payroll_run.processed_at = datetime.utcnow()
        payroll_run.journal_entry_id = journal_entry.id
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll processed and posted to ledger',
            'run': payroll_run.to_dict(),
            'journal_entry_id': journal_entry.id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing payroll: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/<int:run_id>/upload-proof', methods=['POST', 'OPTIONS'])
@token_required
def upload_payment_proof(run_id):
    """Upload proof of payment attachment (Accountant)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        payroll_run = PayrollRun.query.get(run_id)
        if not payroll_run or payroll_run.church_id != g.current_user.church_id:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        # Save file
        upload_dir = os.path.join('uploads', 'payroll_proofs')
        os.makedirs(upload_dir, exist_ok=True)
        
        filename = secure_filename(f"{payroll_run.run_number}_{file.filename}")
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)
        
        payroll_run.attachment_path = filepath
        payroll_run.attachment_filename = file.filename
        payroll_run.attachment_uploaded_by = current_user.id
        payroll_run.attachment_uploaded_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payment proof uploaded',
            'filename': file.filename
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error uploading proof: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/<int:run_id>/verify-proof', methods=['POST', 'OPTIONS'])
@token_required
def verify_payment_proof(run_id):
    """Verify payment proof (Treasurer)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin', 'treasurer']:
            return jsonify({'error': 'Only treasurer can verify payment proof'}), 403
        
        payroll_run = PayrollRun.query.get(run_id)
        if not payroll_run or payroll_run.church_id != g.current_user.church_id:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if not payroll_run.attachment_path:
            return jsonify({'error': 'No payment proof uploaded yet'}), 400
        
        payroll_run.attachment_verified = True
        payroll_run.attachment_verified_by = current_user.id
        payroll_run.attachment_verified_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payment proof verified',
            'verified': True
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error verifying proof: {str(e)}")
        return jsonify({'error': str(e)}), 500