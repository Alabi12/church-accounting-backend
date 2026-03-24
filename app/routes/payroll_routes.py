# app/routes/payroll_routes.py
from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import (
    Employee, PayrollRun, PayrollLine,
    DeductionType, EmployeeDeduction,
    User, JournalEntry, JournalLine,
    Account, AuditLog, Church
)
from app.extensions import db
from datetime import datetime, timedelta
from sqlalchemy import func, and_, extract, text
import traceback
import logging
from decimal import Decimal, ROUND_HALF_UP

# Import token_required from auth_routes
from app.routes.auth_routes import token_required

logger = logging.getLogger(__name__)
payroll_bp = Blueprint('payroll', __name__)


def get_current_user():
    try:
        user_id = get_jwt_identity()
        if user_id:
            return User.query.get(int(user_id))
    except Exception as e:
        logger.warning(f"Error getting user from JWT: {e}")
    return None


def ensure_user_church(user=None):
    """Make sure user has a church_id, assign default if not"""
    if user is None:
        user = get_current_user()
    
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


@payroll_bp.route('/debug-db', methods=['GET'])
@token_required
def debug_database():
    """Debug endpoint to check database connection"""
    try:
        db_url = str(db.engine.url)
        result = db.session.execute(text("SELECT id, employee_number, first_name, last_name, is_active FROM employees")).fetchall()
        
        return jsonify({
            'database_url': db_url,
            'employee_count': len(result),
            'employees': [{'id': r[0], 'code': r[1], 'name': f"{r[2]} {r[3]}", 'active': r[4]} for r in result]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/calculate', methods=['POST', 'OPTIONS'])
@token_required
def calculate_payroll():
    """Calculate payroll for a period"""
    try:
        church_id = ensure_user_church(g.current_user)
        data = request.get_json() or {}

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        period_start = data.get('period_start')
        period_end = data.get('period_end')

        if not period_start or not period_end:
            return jsonify({'error': 'period_start and period_end are required'}), 400

        # Get all active employees using raw SQL with text()
        employees = db.session.execute(
            text("SELECT id, employee_number, first_name, last_name, basic_salary FROM employees WHERE church_id = :church_id AND is_active = 1"),
            {'church_id': church_id}
        ).fetchall()
        
        print(f"Found {len(employees)} active employees")

        if not employees:
            return jsonify({
                'employee_count': 0,
                'items': [],
                'summary': {
                    'total_gross': 0,
                    'total_ssnit': 0,
                    'total_provident_fund': 0,
                    'total_paye': 0,
                    'total_withholding_tax': 0,
                    'total_deductions': 0,
                    'total_net': 0
                }
            }), 200

        payroll_items = []
        total_gross = 0
        total_ssnit = 0
        total_provident_fund = 0
        total_paye = 0
        total_withholding = 0
        total_net = 0

        for emp in employees:
            gross = float(emp[4]) if emp[4] else 0
            ssnit = gross * 0.055
            provident = gross * 0.05
            paye = gross * 0.1 if gross > 400 else 0
            deductions = ssnit + provident + paye
            net = gross - deductions
            
            payroll_items.append({
                'employee_id': emp[0],
                'employee_number': emp[1],
                'name': f"{emp[2]} {emp[3]}",
                'gross_pay': round(gross, 2),
                'ssnit': round(ssnit, 2),
                'provident_fund': round(provident, 2),
                'paye': round(paye, 2),
                'total_deductions': round(deductions, 2),
                'net_pay': round(net, 2)
            })
            
            total_gross += gross
            total_ssnit += ssnit
            total_provident_fund += provident
            total_paye += paye
            total_deductions = total_ssnit + total_provident_fund + total_paye
            total_net += net

        return jsonify({
            'employee_count': len(employees),
            'items': payroll_items,
            'summary': {
                'total_gross': round(total_gross, 2),
                'total_ssnit': round(total_ssnit, 2),
                'total_provident_fund': round(total_provident_fund, 2),
                'total_paye': round(total_paye, 2),
                'total_withholding_tax': round(total_withholding, 2),
                'total_deductions': round(total_deductions, 2),
                'total_net': round(total_net, 2)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error calculating payroll: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/test-orm', methods=['GET'])
@token_required
def test_orm():
    """Test ORM employee query"""
    try:
        employees = Employee.query.filter_by(is_active=True).all()
        
        return jsonify({
            'count': len(employees),
            'employees': [{
                'id': e.id,
                'number': e.employee_number,
                'name': f"{e.first_name} {e.last_name}",
                'basic_salary': float(e.basic_salary) if e.basic_salary else 0
            } for e in employees]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@payroll_bp.route('/test-basic', methods=['GET'])
@token_required
def test_basic():
    """Test endpoint to check basic_salary"""
    try:
        result = db.session.execute(
            text("SELECT id, employee_number, first_name, last_name, basic_salary FROM employees WHERE is_active = 1")
        ).fetchall()
        
        return jsonify({
            'count': len(result),
            'employees': [{'id': r[0], 'code': r[1], 'name': f"{r[2]} {r[3]}", 'salary': r[4]} for r in result]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== PAYROLL RUN MANAGEMENT ====================

@payroll_bp.route('/runs', methods=['POST', 'OPTIONS'])
@token_required
def create_payroll_run():
    """Create a new payroll run"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        period_start = data.get('period_start')
        period_end = data.get('period_end')
        payment_date = data.get('payment_date')
        
        if not period_start or not period_end or not payment_date:
            return jsonify({'error': 'period_start, period_end, and payment_date are required'}), 400
        
        # Generate run number
        year = datetime.now().year
        month = datetime.now().month
        count = PayrollRun.query.filter(
            PayrollRun.run_number.like(f'PR-{year}-{month:02d}%')
        ).count() + 1
        run_number = f"PR-{year}-{month:02d}-{count:03d}"
        
        # Create payroll run
        payroll_run = PayrollRun(
            church_id=church_id,
            run_number=run_number,
            period_start=datetime.fromisoformat(period_start.replace('Z', '+00:00')).date(),
            period_end=datetime.fromisoformat(period_end.replace('Z', '+00:00')).date(),
            payment_date=datetime.fromisoformat(payment_date.replace('Z', '+00:00')).date(),
            status='DRAFT'
        )
        
        db.session.add(payroll_run)
        db.session.flush()
        
        # Add all active employees to this payroll run
        employees = Employee.query.filter_by(
            church_id=church_id,
            is_active=True
        ).all()
        
        total_gross = 0
        total_deductions = 0
        total_net = 0
        
        for emp in employees:
            # Calculate gross pay
            gross = float(emp.basic_salary) if emp.basic_salary else 0
            
            # Calculate deductions
            ssnit = gross * 0.055
            provident = gross * 0.05
            paye = gross * 0.1 if gross > 400 else 0
            deductions = ssnit + provident + paye
            net = gross - deductions
            
            line = PayrollLine(
                payroll_run_id=payroll_run.id,
                employee_id=emp.id,
                basic_salary=gross,
                allowances=float(emp.allowances) if emp.allowances else 0,
                paye_tax=paye,
                ssnit_employee=ssnit,
                provident_fund=provident,
                gross_earnings=gross,
                total_deductions=deductions,
                net_pay=net
            )
            db.session.add(line)
            
            total_gross += gross
            total_deductions += deductions
            total_net += net
        
        payroll_run.gross_pay = total_gross
        payroll_run.total_deductions = total_deductions
        payroll_run.net_pay = total_net
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll run created successfully',
            'run': payroll_run.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating payroll run: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs', methods=['GET', 'OPTIONS'])
@token_required
def get_payroll_runs():
    """Get all payroll runs"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        status = request.args.get('status')
        
        query = PayrollRun.query.filter_by(church_id=church_id)
        
        if status:
            query = query.filter_by(status=status.upper())
        
        runs = query.order_by(PayrollRun.created_at.desc()).all()
        
        return jsonify({
            'runs': [run.to_dict() for run in runs],
            'total': len(runs)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting payroll runs: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/<int:run_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_payroll_run(run_id):
    """Get a specific payroll run"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        payroll_run = PayrollRun.query.filter_by(
            id=run_id,
            church_id=church_id
        ).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        return jsonify(payroll_run.to_dict()), 200
        
    except Exception as e:
        logger.error(f"Error getting payroll run: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/<int:run_id>/submit', methods=['POST', 'OPTIONS'])
@token_required
def submit_payroll_run(run_id):
    """Submit payroll run for review"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = get_current_user()
        
        payroll_run = PayrollRun.query.filter_by(
            id=run_id,
            church_id=church_id
        ).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if payroll_run.status != 'DRAFT':
            return jsonify({'error': f'Cannot submit payroll run with status {payroll_run.status}'}), 400
        
        payroll_run.status = 'SUBMITTED'
        payroll_run.submitted_by = current_user.id if current_user else None
        payroll_run.submitted_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll run submitted for review',
            'run': payroll_run.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting payroll run: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/<int:run_id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_payroll_run(run_id):
    """Approve payroll run"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = get_current_user()
        data = request.get_json() or {}
        
        payroll_run = PayrollRun.query.filter_by(
            id=run_id,
            church_id=church_id
        ).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if payroll_run.status != 'SUBMITTED':
            return jsonify({'error': f'Cannot approve payroll run with status {payroll_run.status}'}), 400
        
        payroll_run.status = 'APPROVED'
        payroll_run.approved_by = current_user.id if current_user else None
        payroll_run.approved_at = datetime.utcnow()
        payroll_run.approval_comments = data.get('comments')
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll run approved',
            'run': payroll_run.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving payroll run: {str(e)}")
        return jsonify({'error': str(e)}), 500

@payroll_bp.route('/runs/<int:run_id>/process', methods=['POST', 'OPTIONS'])
@token_required
def process_payroll_run(run_id):
    """Process payroll run (post to ledger)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = get_current_user()
        
        payroll_run = PayrollRun.query.filter_by(
            id=run_id,
            church_id=church_id
        ).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if payroll_run.status != 'APPROVED':
            return jsonify({'error': f'Cannot process payroll run with status {payroll_run.status}. Must be APPROVED.'}), 400
        
        # Create journal entry for payroll
        from app.models import JournalEntry, JournalLine, Account
        
        # Generate journal entry number
        year = datetime.now().year
        month = datetime.now().month
        count = JournalEntry.query.filter(
            JournalEntry.entry_number.like(f'JE-PR-{year}-{month:02d}%')
        ).count() + 1
        entry_number = f"JE-PR-{year}-{month:02d}-{count:03d}"
        
        # Get accounts
        # Salary Expense account (assuming account code 5100)
        salary_expense = Account.query.filter_by(
            church_id=church_id,
            account_code='5100'
        ).first()
        
        # If not found, create it
        if not salary_expense:
            salary_expense = Account(
                church_id=church_id,
                account_code='5100',
                name='Salary Expense',
                display_name='Salaries',
                account_type='EXPENSE',
                category='Staff Costs',
                normal_balance='debit',
                is_active=True
            )
            db.session.add(salary_expense)
            db.session.flush()
        
        # SSNIT Payable account
        ssnit_payable = Account.query.filter_by(
            church_id=church_id,
            account_code='2110'
        ).first()
        
        if not ssnit_payable:
            ssnit_payable = Account(
                church_id=church_id,
                account_code='2110',
                name='SSNIT Payable',
                display_name='SSNIT Payable',
                account_type='LIABILITY',
                category='Payables',
                normal_balance='credit',
                is_active=True
            )
            db.session.add(ssnit_payable)
            db.session.flush()
        
        # Provident Fund Payable account
        provident_payable = Account.query.filter_by(
            church_id=church_id,
            account_code='2120'
        ).first()
        
        if not provident_payable:
            provident_payable = Account(
                church_id=church_id,
                account_code='2120',
                name='Provident Fund Payable',
                display_name='Provident Fund Payable',
                account_type='LIABILITY',
                category='Payables',
                normal_balance='credit',
                is_active=True
            )
            db.session.add(provident_payable)
            db.session.flush()
        
        # PAYE Payable account
        paye_payable = Account.query.filter_by(
            church_id=church_id,
            account_code='2130'
        ).first()
        
        if not paye_payable:
            paye_payable = Account(
                church_id=church_id,
                account_code='2130',
                name='PAYE Payable',
                display_name='PAYE Payable',
                account_type='LIABILITY',
                category='Payables',
                normal_balance='credit',
                is_active=True
            )
            db.session.add(paye_payable)
            db.session.flush()
        
        # Bank/Cash account (assuming account code 1010)
        bank_account = Account.query.filter_by(
            church_id=church_id,
            account_code='1010'
        ).first()
        
        if not bank_account:
            bank_account = Account(
                church_id=church_id,
                account_code='1010',
                name='Cash in Hand',
                display_name='Cash',
                account_type='ASSET',
                category='Current Assets',
                normal_balance='debit',
                is_active=True
            )
            db.session.add(bank_account)
            db.session.flush()
        
        # Create journal entry
        journal_entry = JournalEntry(
            church_id=church_id,
            entry_number=entry_number,
            entry_date=payroll_run.payment_date,
            description=f"Payroll for period {payroll_run.period_start} to {payroll_run.period_end}",
            status='POSTED',
            created_by=current_user.id if current_user else None,
            posted_by=current_user.id if current_user else None,
            posted_at=datetime.utcnow()
        )
        db.session.add(journal_entry)
        db.session.flush()
        
        # Calculate totals from payroll lines
        total_gross = payroll_run.gross_pay
        total_ssnit = sum(float(line.ssnit_employee) for line in payroll_run.lines)
        total_provident = sum(float(line.provident_fund) for line in payroll_run.lines)
        total_paye = sum(float(line.paye_tax) for line in payroll_run.lines)
        total_net = payroll_run.net_pay
        
        # Add journal lines
        # Debit: Salary Expense (Gross Pay)
        line1 = JournalLine(
            journal_entry_id=journal_entry.id,
            account_id=salary_expense.id,
            debit=total_gross,
            credit=0,
            description="Gross salary expense"
        )
        db.session.add(line1)
        
        # Credit: SSNIT Payable
        if total_ssnit > 0:
            line2 = JournalLine(
                journal_entry_id=journal_entry.id,
                account_id=ssnit_payable.id,
                debit=0,
                credit=total_ssnit,
                description="SSNIT contribution payable"
            )
            db.session.add(line2)
        
        # Credit: Provident Fund Payable
        if total_provident > 0:
            line3 = JournalLine(
                journal_entry_id=journal_entry.id,
                account_id=provident_payable.id,
                debit=0,
                credit=total_provident,
                description="Provident fund payable"
            )
            db.session.add(line3)
        
        # Credit: PAYE Payable
        if total_paye > 0:
            line4 = JournalLine(
                journal_entry_id=journal_entry.id,
                account_id=paye_payable.id,
                debit=0,
                credit=total_paye,
                description="PAYE tax payable"
            )
            db.session.add(line4)
        
        # Credit: Bank/Cash (Net Pay)
        if total_net > 0:
            line5 = JournalLine(
                journal_entry_id=journal_entry.id,
                account_id=bank_account.id,
                debit=0,
                credit=total_net,
                description="Net salary payment"
            )
            db.session.add(line5)
        
        # Update payroll run
        payroll_run.status = 'PROCESSED'
        payroll_run.processed_by = current_user.id if current_user else None
        payroll_run.processed_at = datetime.utcnow()
        payroll_run.journal_entry_id = journal_entry.id
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll processed and posted to ledger',
            'run': payroll_run.to_dict(),
            'journal_entry_id': journal_entry.id,
            'journal_entry_number': entry_number
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing payroll run: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
