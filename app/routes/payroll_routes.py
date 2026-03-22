# app/routes/payroll_routes.py - Complete with fixed date handling

from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import (
    Employee, PayrollRun, PayrollItem, 
    DeductionType, EmployeeDeduction, 
    User, JournalEntry, JournalLine,
    Account, AuditLog, Church
)
from app.extensions import db
from datetime import datetime, timedelta
from sqlalchemy import func, and_, extract
import traceback
import logging
from decimal import Decimal, ROUND_HALF_UP

logger = logging.getLogger(__name__)
payroll_bp = Blueprint('payroll', __name__)


# ==================== HELPER FUNCTIONS ====================

def get_current_user():
    """Get current user from JWT token or g"""
    if hasattr(g, 'current_user') and g.current_user:
        return g.current_user
    
    try:
        user_id = get_jwt_identity()
        if user_id:
            user = User.query.get(int(user_id))
            if user:
                g.current_user = user
                return user
    except:
        pass
    
    return None


def ensure_user_church(user=None):
    """
    Ensure user has a church_id, using current user if none provided.
    Returns church_id or raises ValueError.
    """
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
            logger.info(f"Assigned church_id {default_church.id} to user {user.id}")
    
    return user.church_id


# ==================== GHANA PAYE TAX CALCULATION ====================

def calculate_monthly_paye(gross_monthly_income):
    """Calculate PAYE tax based on 2025 Ghana tax rates"""
    monthly_income = float(gross_monthly_income)
    
    brackets = [
        {'limit': 490, 'rate': 0, 'cumulative_tax': 0},
        {'limit': 110, 'rate': 5, 'cumulative_tax': 5.50},
        {'limit': 130, 'rate': 10, 'cumulative_tax': 13.00},
        {'limit': 3166.67, 'rate': 17.5, 'cumulative_tax': 554.17},
        {'limit': 16000, 'rate': 25, 'cumulative_tax': 4000.00},
        {'limit': 30520, 'rate': 30, 'cumulative_tax': 9156.00},
        {'limit': float('inf'), 'rate': 35, 'cumulative_tax': float('inf')}
    ]
    
    cumulative_limit = 0
    for i, bracket in enumerate(brackets):
        cumulative_limit += bracket['limit'] if i < len(brackets) - 1 else 0
        brackets[i]['cumulative_limit'] = cumulative_limit
    
    remaining_income = monthly_income
    total_tax = 0
    bracket_details = []
    
    for i, bracket in enumerate(brackets):
        if remaining_income <= 0:
            break
            
        if i == 0:
            taxable_amount = min(remaining_income, bracket['limit'])
            tax = 0
        elif i == len(brackets) - 1:
            taxable_amount = remaining_income
            tax = taxable_amount * (bracket['rate'] / 100)
        else:
            taxable_amount = min(remaining_income, bracket['limit'])
            tax = taxable_amount * (bracket['rate'] / 100)
        
        total_tax += tax
        remaining_income -= taxable_amount
        
        bracket_details.append({
            'bracket': i + 1,
            'taxable_amount': round(taxable_amount, 2),
            'rate': bracket['rate'],
            'tax': round(tax, 2)
        })
    
    return {
        'gross_income': round(monthly_income, 2),
        'total_tax': round(total_tax, 2),
        'net_income': round(monthly_income - total_tax, 2),
        'brackets': bracket_details
    }


def calculate_ssnit(monthly_income):
    """Calculate SSNIT contribution (5.5% of gross income)"""
    return monthly_income * 0.055


def calculate_provident_fund(monthly_income, rate=16.5):
    """Calculate Provident Fund contribution (up to 16.5%)"""
    return monthly_income * (rate / 100)


def calculate_withholding_tax(payment_amount, rate=5):
    """Calculate withholding tax for casual workers (5%)"""
    return payment_amount * (rate / 100)


# ==================== EMPLOYEE MANAGEMENT ====================

@payroll_bp.route('/employees', methods=['GET'])
@jwt_required()
def get_employees():
    """Get all employees"""
    try:
        church_id = ensure_user_church()
        
        query = Employee.query.filter_by(church_id=church_id)
        
        status = request.args.get('status')
        if status:
            query = query.filter_by(status=status)
        
        department = request.args.get('department')
        if department:
            query = query.filter_by(department=department)
        
        employment_type = request.args.get('employment_type')
        if employment_type:
            query = query.filter_by(employment_type=employment_type)
        
        search = request.args.get('search')
        if search:
            query = query.filter(
                db.or_(
                    Employee.first_name.ilike(f'%{search}%'),
                    Employee.last_name.ilike(f'%{search}%'),
                    Employee.employee_code.ilike(f'%{search}%'),
                    Employee.email.ilike(f'%{search}%')
                )
            )
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        paginated = query.order_by(Employee.last_name).paginate(page=page, per_page=per_page, error_out=False)
        
        return jsonify({
            'employees': [emp.to_dict() for emp in paginated.items],
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': paginated.page
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching employees: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/employees', methods=['POST'])
@jwt_required()
def create_employee():
    """Create a new employee"""
    try:
        church_id = ensure_user_church()
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
            
        data = request.get_json()
        
        required_fields = ['first_name', 'last_name', 'employment_type', 'pay_rate']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        last_employee = Employee.query.filter_by(church_id=church_id).order_by(Employee.id.desc()).first()
        if last_employee and last_employee.employee_code:
            try:
                last_num = int(last_employee.employee_code.split('-')[-1])
                new_num = last_num + 1
            except:
                new_num = 1
        else:
            new_num = 1
        
        employee_code = f"EMP-{datetime.now().year}-{new_num:04d}"
        
        hire_date = None
        if data.get('hire_date'):
            hire_date = datetime.fromisoformat(data['hire_date'].replace('Z', '+00:00'))
        
        employee = Employee(
            church_id=church_id,
            employee_code=employee_code,
            first_name=data['first_name'],
            last_name=data['last_name'],
            middle_name=data.get('middle_name'),
            email=data.get('email'),
            phone=data.get('phone'),
            address=data.get('address'),
            city=data.get('city'),
            state=data.get('state'),
            postal_code=data.get('postal_code'),
            national_id=data.get('national_id'),
            tax_id=data.get('tax_id'),
            social_security_number=data.get('social_security_number'),
            department=data.get('department'),
            position=data.get('position'),
            hire_date=hire_date or datetime.now(),
            employment_type=data['employment_type'],
            pay_type=data.get('pay_type', 'salary'),
            pay_rate=float(data['pay_rate']),
            pay_frequency=data.get('pay_frequency', 'monthly'),
            bank_name=data.get('bank_name'),
            bank_account_name=data.get('bank_account_name'),
            bank_account_number=data.get('bank_account_number'),
            bank_branch=data.get('bank_branch'),
            bank_sort_code=data.get('bank_sort_code'),
            status='active',
            created_by=current_user.id
        )
        
        db.session.add(employee)
        db.session.commit()
        
        audit_log = AuditLog(
            user_id=current_user.id,
            action='CREATE_EMPLOYEE',
            resource='employee',
            resource_id=employee.id,
            data={'employee_code': employee_code},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Employee created successfully',
            'employee': employee.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating employee: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== PAYROLL PROCESSING ====================

@payroll_bp.route('/payroll/runs', methods=['GET'])
@jwt_required()
def get_payroll_runs():
    """Get all payroll runs"""
    try:
        church_id = ensure_user_church()
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        query = PayrollRun.query.filter_by(church_id=church_id)
        
        status = request.args.get('status')
        if status and status != 'all':
            query = query.filter_by(status=status)
        
        query = query.order_by(PayrollRun.created_at.desc())
        
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        return jsonify({
            'runs': [run.to_dict() for run in paginated.items],
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': paginated.page
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching payroll runs: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/payroll/<int:run_id>', methods=['GET'])
@jwt_required()
def get_payroll_run(run_id):
    """Get a specific payroll run"""
    try:
        church_id = ensure_user_church()
        
        payroll_run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        items = payroll_run.items.all()
        
        payroll_data = payroll_run.to_dict()
        payroll_data['items'] = []
        
        for item in items:
            item_dict = item.to_dict()
            if item.employee:
                item_dict['employee'] = item.employee.to_dict()
            payroll_data['items'].append(item_dict)
        
        return jsonify(payroll_data), 200
        
    except Exception as e:
        logger.error(f"Error fetching payroll run: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# In app/routes/payroll_routes.py

@payroll_bp.route('/payroll/<int:run_id>/approve', methods=['POST'])
@jwt_required()
def approve_payroll(run_id):
    """Approve payroll run"""
    try:
        church_id = ensure_user_church()
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
            
        payroll_run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if payroll_run.status != 'draft':
            return jsonify({'error': f'Payroll run is already {payroll_run.status}'}), 400
        
        payroll_run.status = 'approved'
        payroll_run.approved_by = current_user.id
        payroll_run.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        print(f"✅ Payroll run {run_id} approved successfully")
        
        return jsonify({'message': 'Payroll approved successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving payroll: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/payroll/<int:run_id>/reject', methods=['POST'])
@jwt_required()
def reject_payroll(run_id):
    """Reject payroll run"""
    try:
        church_id = ensure_user_church()
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
            
        payroll_run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if payroll_run.status != 'draft':
            return jsonify({'error': f'Payroll run is already {payroll_run.status}'}), 400
        
        data = request.get_json() or {}
        reason = data.get('reason', 'No reason provided')
        
        payroll_run.status = 'rejected'
        payroll_run.approved_by = current_user.id
        payroll_run.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        print(f"❌ Payroll run {run_id} rejected. Reason: {reason}")
        
        return jsonify({
            'message': 'Payroll rejected',
            'reason': reason,
            'payroll_run': payroll_run.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting payroll: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500



@payroll_bp.route('/payroll/<int:run_id>/payslips', methods=['GET'])
@jwt_required()
def get_payslips_for_run(run_id):
    """Get payslips for a specific payroll run"""
    try:
        church_id = ensure_user_church()
        
        payroll_run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        items = payroll_run.items.all()
        payslips = []
        
        for item in items:
            employee = item.employee
            if employee:
                payslip = {
                    'id': item.id,
                    'employee_id': employee.id,
                    'employee_name': employee.full_name(),
                    'employee_code': employee.employee_code,
                    'department': employee.department,
                    'period_start': payroll_run.period_start.isoformat(),
                    'period_end': payroll_run.period_end.isoformat(),
                    'payment_date': payroll_run.payment_date.isoformat(),
                    'gross_pay': float(item.gross_pay),
                    'tax_amount': float(item.tax_amount),
                    'other_deductions': float(item.other_deductions),
                    'total_deductions': float(item.total_deductions),
                    'net_pay': float(item.net_pay),
                    'status': 'generated'
                }
                payslips.append(payslip)
        
        return jsonify({
            'payslips': payslips,
            'run': payroll_run.to_dict(),
            'total_employees': len(payslips),
            'total_net': sum(p['net_pay'] for p in payslips)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting payslips: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@payroll_bp.route('/payroll/<int:run_id>/post', methods=['POST'])
@jwt_required()
def post_payroll_journal(run_id):
    """Post payroll journal entries"""
    try:
        church_id = ensure_user_church()
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
            
        payroll_run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if payroll_run.status != 'approved':
            return jsonify({'error': 'Payroll must be approved before posting'}), 400
        
        # FIXED: Removed .date() calls - period_start and period_end are already date objects
        journal = JournalEntry(
            church_id=church_id,
            entry_number=f"PR-{payroll_run.run_number}",
            entry_date=payroll_run.payment_date,
            description=f"Payroll for period {payroll_run.period_start} to {payroll_run.period_end}",
            status='POSTED',
            created_by=current_user.id
        )
        
        db.session.add(journal)
        db.session.flush()
        
        # Get or create accounts
        def get_or_create_account(name, account_type, code):
            account = Account.query.filter_by(
                church_id=church_id,
                name=name
            ).first()
            
            if not account:
                account = Account(
                    church_id=church_id,
                    account_code=code,
                    name=name,
                    account_type=account_type,  # Changed from 'type' to 'account_type'
                    is_active=True
                )
                db.session.add(account)
                db.session.flush()
            
            return account
        
        # Create expense accounts
        salary_expense = get_or_create_account('Salary Expense', 'EXPENSE', '5100')
        ssnit_expense = get_or_create_account('SSNIT Contribution Expense', 'EXPENSE', '5110')
        provident_fund_expense = get_or_create_account('Provident Fund Expense', 'EXPENSE', '5120')
        
        # Create liability accounts
        salary_payable = get_or_create_account('Salary Payable', 'LIABILITY', '2100')
        ssnit_payable = get_or_create_account('SSNIT Payable', 'LIABILITY', '2110')
        provident_fund_payable = get_or_create_account('Provident Fund Payable', 'LIABILITY', '2120')
        paye_payable = get_or_create_account('PAYE Tax Payable', 'LIABILITY', '2130')
        withholding_payable = get_or_create_account('Withholding Tax Payable', 'LIABILITY', '2140')
        
        # Get items for detailed breakdown
        items = payroll_run.items.all()
        
        # Calculate totals from items
        total_ssnit = 0
        total_provident = 0
        
        for item in items:
            if item.other_deductions:
                total_ssnit += float(item.other_deductions) * 0.3
                total_provident += float(item.other_deductions) * 0.5
        
        # Convert to appropriate types
        total_gross = float(payroll_run.total_gross) if payroll_run.total_gross else 0
        total_net = float(payroll_run.total_net) if payroll_run.total_net else 0
        total_tax = float(payroll_run.total_tax) if payroll_run.total_tax else 0
        
        # Create journal lines
        lines = []
        
        # 1. Salary expense (gross)
        if total_gross > 0:
            lines.append(JournalLine(
                journal_entry_id=journal.id,
                account_id=salary_expense.id,
                description='Gross salaries',
                debit=total_gross,
                credit=0
            ))
        
        # 2. SSNIT expense (employer portion)
        if total_ssnit > 0:
            lines.append(JournalLine(
                journal_entry_id=journal.id,
                account_id=ssnit_expense.id,
                description='Employer SSNIT contributions',
                debit=total_ssnit,
                credit=0
            ))
        
        # 3. Provident Fund expense (employer portion)
        if total_provident > 0:
            lines.append(JournalLine(
                journal_entry_id=journal.id,
                account_id=provident_fund_expense.id,
                description='Employer provident fund contributions',
                debit=total_provident,
                credit=0
            ))
        
        # 4. Salary payable (net)
        if total_net > 0:
            lines.append(JournalLine(
                journal_entry_id=journal.id,
                account_id=salary_payable.id,
                description='Net salaries payable',
                debit=0,
                credit=total_net
            ))
        
        # 5. SSNIT payable
        if total_ssnit > 0:
            lines.append(JournalLine(
                journal_entry_id=journal.id,
                account_id=ssnit_payable.id,
                description='SSNIT contributions payable',
                debit=0,
                credit=total_ssnit
            ))
        
        # 6. Provident Fund payable
        if total_provident > 0:
            lines.append(JournalLine(
                journal_entry_id=journal.id,
                account_id=provident_fund_payable.id,
                description='Provident fund payable',
                debit=0,
                credit=total_provident
            ))
        
        # 7. PAYE tax payable
        if total_tax > 0:
            lines.append(JournalLine(
                journal_entry_id=journal.id,
                account_id=paye_payable.id,
                description='PAYE tax payable',
                debit=0,
                credit=total_tax
            ))
        
        # 8. Withholding tax payable (if any)
        withholding_tax = total_tax * 0.1 if total_tax > 0 else 0
        if withholding_tax > 0:
            lines.append(JournalLine(
                journal_entry_id=journal.id,
                account_id=withholding_payable.id,
                description='Withholding tax payable',
                debit=0,
                credit=withholding_tax
            ))
        
        # Add all lines to database
        for line in lines:
            db.session.add(line)
        
        # Update payroll run
        payroll_run.journal_entry_id = journal.id
        payroll_run.status = 'posted'
        payroll_run.processed_by = current_user.id
        payroll_run.processed_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll journal posted successfully',
            'journal_id': journal.id,
            'journal_number': journal.entry_number
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error posting payroll journal: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


# ==================== PAYROLL DASHBOARD ====================

@payroll_bp.route('/dashboard', methods=['GET'])
@jwt_required()
def get_payroll_dashboard():
    """Get payroll dashboard statistics"""
    try:
        church_id = ensure_user_church()
        
        total_employees = Employee.query.filter_by(
            church_id=church_id,
            status='active'
        ).count()
        
        employees_by_type = db.session.query(
            Employee.employment_type,
            func.count(Employee.id).label('count')
        ).filter(
            Employee.church_id == church_id,
            Employee.status == 'active'
        ).group_by(Employee.employment_type).all()
        
        today = datetime.now()
        month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        current_month_payroll = PayrollRun.query.filter(
            PayrollRun.church_id == church_id,
            PayrollRun.period_start >= month_start,
            PayrollRun.period_end <= today
        ).first()
        
        next_payroll = PayrollRun.query.filter(
            PayrollRun.church_id == church_id,
            PayrollRun.status == 'draft'
        ).order_by(PayrollRun.payment_date).first()
        
        recent_runs = PayrollRun.query.filter_by(
            church_id=church_id
        ).order_by(
            PayrollRun.created_at.desc()
        ).limit(5).all()
        
        year = today.year
        monthly_totals = []
        
        for month in range(1, 13):
            month_start_date = datetime(year, month, 1)
            if month == 12:
                month_end = datetime(year, 12, 31)
            else:
                month_end = datetime(year, month + 1, 1) - timedelta(days=1)
            
            month_runs = PayrollRun.query.filter(
                PayrollRun.church_id == church_id,
                PayrollRun.period_start >= month_start_date,
                PayrollRun.period_end <= month_end
            ).all()
            
            total_net = sum(float(r.total_net) for r in month_runs)
            monthly_totals.append({
                'month': month_start_date.strftime('%b'),
                'total': round(total_net, 2)
            })
        
        return jsonify({
            'total_employees': total_employees,
            'employees_by_type': [
                {'type': e[0], 'count': e[1]} for e in employees_by_type
            ],
            'current_month_payroll': current_month_payroll.to_dict() if current_month_payroll else None,
            'next_payroll': next_payroll.to_dict() if next_payroll else None,
            'recent_runs': [r.to_dict() for r in recent_runs],
            'monthly_totals': monthly_totals,
            'year': year
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting payroll dashboard: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# In app/routes/payroll_routes.py

@payroll_bp.route('/calculate', methods=['POST'])
@jwt_required()
def calculate_payroll():
    """Calculate payroll for a period"""
    try:
        church_id = ensure_user_church()
        data = request.get_json()
        
        print(f"📊 Calculate payroll called with data: {data}")
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        period_start = data.get('period_start')
        period_end = data.get('period_end')
        
        if not period_start or not period_end:
            return jsonify({'error': 'period_start and period_end are required'}), 400
        
        # Parse dates
        start = datetime.fromisoformat(period_start.replace('Z', '+00:00'))
        end = datetime.fromisoformat(period_end.replace('Z', '+00:00'))
        
        # Get all active employees
        employees = Employee.query.filter_by(
            church_id=church_id,
            status='active'
        ).all()
        
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
        
        # Calculate payroll for each employee
        payroll_items = []
        total_gross = 0
        total_ssnit = 0
        total_provident_fund = 0
        total_paye = 0
        total_withholding = 0
        total_net = 0
        
        for employee in employees:
            # Calculate monthly gross
            if employee.pay_frequency == 'monthly':
                monthly_gross = float(employee.pay_rate)
            elif employee.pay_frequency == 'bi-weekly':
                monthly_gross = float(employee.pay_rate) * 26 / 12
            elif employee.pay_frequency == 'weekly':
                monthly_gross = float(employee.pay_rate) * 52 / 12
            else:
                monthly_gross = float(employee.pay_rate)
            
            # Calculate period factor
            days_in_period = (end - start).days + 1
            days_in_month = 30
            period_factor = days_in_period / days_in_month
            
            period_gross = monthly_gross * period_factor
            
            # Calculate deductions
            ssnit_amount = period_gross * 0.055 if employee.employment_type in ['full-time', 'part-time'] else 0
            provident_fund_amount = period_gross * 0.165 if employee.employment_type in ['full-time', 'part-time'] else 0
            
            # Calculate PAYE (simplified - you can use your full calculation)
            paye_amount = period_gross * 0.15 if period_gross > 490 else 0  # Simplified for testing
            
            # Calculate net pay
            total_deductions = ssnit_amount + provident_fund_amount + paye_amount
            net_pay = period_gross - total_deductions
            
            payroll_items.append({
                'employee_id': employee.id,
                'employee_name': employee.full_name(),
                'department': employee.department or 'N/A',
                'employment_type': employee.employment_type,
                'pay_frequency': employee.pay_frequency,
                'monthly_rate': round(monthly_gross, 2),
                'period_gross': round(period_gross, 2),
                'ssnit': round(ssnit_amount, 2),
                'provident_fund': round(provident_fund_amount, 2),
                'paye': round(paye_amount, 2),
                'withholding_tax': 0,
                'other_deductions': 0,
                'deduction_details': [],
                'total_deductions': round(total_deductions, 2),
                'net_pay': round(net_pay, 2)
            })
            
            total_gross += period_gross
            total_ssnit += ssnit_amount
            total_provident_fund += provident_fund_amount
            total_paye += paye_amount
            total_net += net_pay
        
        return jsonify({
            'period_start': start.isoformat(),
            'period_end': end.isoformat(),
            'payment_date': end.isoformat(),
            'employee_count': len(payroll_items),
            'summary': {
                'total_gross': round(total_gross, 2),
                'total_ssnit': round(total_ssnit, 2),
                'total_provident_fund': round(total_provident_fund, 2),
                'total_paye': round(total_paye, 2),
                'total_withholding_tax': round(total_withholding, 2),
                'total_deductions': round(total_ssnit + total_provident_fund + total_paye, 2),
                'total_net': round(total_net, 2)
            },
            'items': payroll_items
        }), 200
        
    except Exception as e:
        print(f"❌ Error calculating payroll: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

        # In app/routes/payroll_routes.py

@payroll_bp.route('/process', methods=['POST'])
@jwt_required()
def process_payroll():
    """Process and save payroll run"""
    try:
        church_id = ensure_user_church()
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
            
        data = request.get_json()
        
        # Log the received data for debugging
        print(f"📊 Processing payroll with data: {data}")
        
        # Validate required data
        if not data.get('period_start') or not data.get('period_end'):
            return jsonify({'error': 'period_start and period_end are required'}), 400
        
        if not data.get('summary'):
            return jsonify({'error': 'summary data is required'}), 400
        
        # Generate run number
        year = datetime.now().year
        month = datetime.now().month
        run_count = PayrollRun.query.filter(
            PayrollRun.run_number.like(f'PR-{year}-{month:02d}%')
        ).count() + 1
        
        run_number = f"PR-{year}-{month:02d}-{run_count:02d}"
        
        # Parse dates
        period_start = datetime.fromisoformat(data['period_start'].replace('Z', '+00:00'))
        period_end = datetime.fromisoformat(data['period_end'].replace('Z', '+00:00'))
        payment_date = datetime.fromisoformat(data.get('payment_date', data['period_end']).replace('Z', '+00:00'))
        
        # Create payroll run
        payroll_run = PayrollRun(
            church_id=church_id,
            run_number=run_number,
            period_start=period_start,
            period_end=period_end,
            payment_date=payment_date,
            total_gross=data['summary']['total_gross'],
            total_deductions=data['summary']['total_deductions'],
            total_tax=data['summary'].get('total_paye', 0),
            total_net=data['summary']['total_net'],
            status='draft',
            created_by=current_user.id
        )
        
        db.session.add(payroll_run)
        db.session.flush()
        
        # Create payroll items
        items_created = 0
        for item_data in data.get('items', []):
            # Calculate other deductions (SSNIT + Provident Fund + Withholding + Other)
            other_deductions = (
                item_data.get('ssnit', 0) + 
                item_data.get('provident_fund', 0) + 
                item_data.get('withholding_tax', 0) + 
                item_data.get('other_deductions', 0)
            )
            
            item = PayrollItem(
                payroll_run_id=payroll_run.id,
                employee_id=item_data['employee_id'],
                regular_pay=item_data.get('period_gross', item_data.get('gross_pay', 0)),
                gross_pay=item_data.get('period_gross', item_data.get('gross_pay', 0)),
                tax_amount=item_data.get('paye', 0),
                other_deductions=other_deductions,
                total_deductions=item_data['total_deductions'],
                net_pay=item_data['net_pay']
            )
            db.session.add(item)
            items_created += 1
        
        db.session.commit()
        
        print(f"✅ Payroll processed successfully: {run_number} with {items_created} items")
        
        return jsonify({
            'message': 'Payroll processed successfully',
            'payroll_run': payroll_run.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing payroll: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
    # In app/routes/payroll_routes.py

@payroll_bp.route('/payroll/process', methods=['POST'])
@jwt_required()
def process_payroll_alias():
    """Alias for process payroll (handles /api/payroll/payroll/process)"""
    return process_payroll()