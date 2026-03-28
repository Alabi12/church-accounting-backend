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


# ============== HELPER FUNCTIONS ==========================

def get_current_user():
    """Get current user from JWT token"""
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


def safe_float(value):
    """Safely convert a value to float, returning 0 if None or invalid"""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def safe_date_iso(date_obj):
    """Safely convert a date to ISO format string"""
    if date_obj is None:
        return None
    try:
        if isinstance(date_obj, datetime):
            return date_obj.isoformat()
        return date_obj.isoformat()
    except Exception:
        return None


def calculate_paye_tax(gross_salary, year=None):
    """
    Calculate PAYE tax based on tax brackets for the given year
    """
    gross = float(gross_salary)
    
    if year is None:
        year = datetime.now().year
    
    try:
        # Try to get tax brackets from database
        brackets_data = db.session.execute(
            text("""
                SELECT bracket_from, bracket_to, rate
                FROM tax_tables 
                WHERE tax_year = :year
                ORDER BY bracket_from
            """),
            {'year': year}
        ).fetchall()
        
        if brackets_data:
            # Calculate tax using brackets
            tax = 0
            remaining = gross
            
            for row in brackets_data:
                bracket_min = float(row[0])
                bracket_max = float(row[1]) if row[1] else float('inf')
                rate = float(row[2]) / 100  # Convert percentage to decimal
                
                if gross > bracket_min:
                    taxable = min(gross, bracket_max) - bracket_min
                    if taxable > 0:
                        tax += taxable * rate
                else:
                    break
            
            return round(tax, 2)
    except Exception as e:
        logger.warning(f"Could not fetch tax brackets for calculation: {e}")
    
    # Fallback to hardcoded Ghana tax brackets (2024-2025)
    if gross <= 402:
        return 0
    elif gross <= 490:
        return (gross - 402) * 0.05
    elif gross <= 644:
        return 4.40 + (gross - 490) * 0.10
    elif gross <= 971:
        return 19.80 + (gross - 644) * 0.175
    elif gross <= 1632:
        return 77.00 + (gross - 971) * 0.25
    elif gross <= 3227:
        return 242.25 + (gross - 1632) * 0.30
    else:
        return 720.75 + (gross - 3227) * 0.35


# ==================== DASHBOARD ENDPOINT ====================

months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


@payroll_bp.route('/dashboard', methods=['GET', 'OPTIONS'])
@token_required
def payroll_dashboard():
    """Get payroll dashboard statistics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({'error': 'User not found'}), 404
        
        church_id = ensure_user_church(g.current_user)
        
        # Get total active employees
        total_employees = Employee.query.filter_by(
            church_id=church_id, 
            is_active=True
        ).count()
        
        # Get latest payroll run
        latest_run = PayrollRun.query.filter_by(
            church_id=church_id
        ).order_by(PayrollRun.created_at.desc()).first()
        
        # Get recent payroll runs (last 5)
        recent_runs = PayrollRun.query.filter_by(
            church_id=church_id
        ).order_by(PayrollRun.created_at.desc()).limit(5).all()
        
        # Get total payroll amount for current month
        current_month = datetime.now().month
        current_year = datetime.now().year
        
        # Get current month payroll run
        current_month_run = PayrollRun.query.filter(
            PayrollRun.church_id == church_id,
            extract('month', PayrollRun.period_start) == current_month,
            extract('year', PayrollRun.period_start) == current_year
        ).first()
        
        # Calculate current month totals
        current_month_payroll = None
        if current_month_run:
            lines = PayrollLine.query.filter_by(payroll_run_id=current_month_run.id).all()
            total_gross = sum(safe_float(line.gross_earnings) for line in lines)
            total_deductions = sum(safe_float(line.total_deductions) for line in lines)
            total_net = sum(safe_float(line.net_pay) for line in lines)
            current_month_payroll = {
                'id': current_month_run.id,
                'run_number': current_month_run.run_number,
                'employee_count': len(lines),
                'total_gross': round(total_gross, 2),
                'total_deductions': round(total_deductions, 2),
                'total_net': round(total_net, 2)
            }
        
        # Get employees by type (employment_type)
        employees_by_type = db.session.query(
            Employee.employment_type,
            func.count(Employee.id).label('count')
        ).filter(
            Employee.church_id == church_id,
            Employee.is_active == True
        ).group_by(Employee.employment_type).all()
        
        employees_by_type_list = [
            {'type': emp_type or 'FULL_TIME', 'count': count}
            for emp_type, count in employees_by_type
        ]
        
        # Get monthly totals for the year
        monthly_totals = []
        for month in range(1, 13):
            month_start = datetime(current_year, month, 1).date()
            if month == 12:
                month_end = datetime(current_year + 1, 1, 1).date() - timedelta(days=1)
            else:
                month_end = datetime(current_year, month + 1, 1).date() - timedelta(days=1)
            
            # Find payroll run for this month
            month_run = PayrollRun.query.filter(
                PayrollRun.church_id == church_id,
                PayrollRun.period_start >= month_start,
                PayrollRun.period_end <= month_end
            ).first()
            
            if month_run:
                lines = PayrollLine.query.filter_by(payroll_run_id=month_run.id).all()
                total_net = sum(safe_float(line.net_pay) for line in lines)
                monthly_totals.append({
                    'month': months[month - 1],
                    'total': round(total_net, 2)
                })
            else:
                monthly_totals.append({
                    'month': months[month - 1],
                    'total': 0
                })
        
        # Get next scheduled payment (next payroll run with payment date in future)
        next_payroll = PayrollRun.query.filter(
            PayrollRun.church_id == church_id,
            PayrollRun.payment_date >= datetime.now().date(),
            PayrollRun.status != 'PROCESSED'
        ).order_by(PayrollRun.payment_date).first()
        
        next_payroll_data = None
        if next_payroll:
            next_payroll_data = {
                'payment_date': safe_date_iso(next_payroll.payment_date),
                'status': next_payroll.status.lower() if next_payroll.status else 'draft'
            }
        
        # Format recent runs
        recent_runs_list = []
        for run in recent_runs:
            lines = PayrollLine.query.filter_by(payroll_run_id=run.id).all()
            total_gross = sum(safe_float(line.gross_earnings) for line in lines)
            total_deductions = sum(safe_float(line.total_deductions) for line in lines)
            total_net = sum(safe_float(line.net_pay) for line in lines)
            
            recent_runs_list.append({
                'id': run.id,
                'run_number': run.run_number,
                'period_start': safe_date_iso(run.period_start),
                'period_end': safe_date_iso(run.period_end),
                'status': run.status.lower() if run.status else 'draft',
                'total_gross': round(total_gross, 2),
                'total_deductions': round(total_deductions, 2),
                'total_net': round(total_net, 2)
            })
        
        return jsonify({
            'total_employees': total_employees,
            'current_month_payroll': current_month_payroll,
            'next_payroll': next_payroll_data,
            'recent_runs': recent_runs_list,
            'employees_by_type': employees_by_type_list,
            'monthly_totals': monthly_totals
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting payroll dashboard: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== DEBUG ENDPOINTS ====================

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
            'employees': [{'id': r[0], 'code': r[1], 'name': f"{r[2]} {r[3]}", 'active': bool(r[4])} for r in result]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== EMPLOYEE MANAGEMENT ====================

@payroll_bp.route('/employees', methods=['GET', 'OPTIONS'])
@token_required
def get_employees():
    """Get all employees with optional filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({'error': 'User not found'}), 404
        
        church_id = ensure_user_church(g.current_user)
        
        # Get query parameters
        status = request.args.get('status', 'active')
        department = request.args.get('department')
        search = request.args.get('search')
        
        query = Employee.query.filter_by(church_id=church_id)
        
        if status == 'active':
            query = query.filter_by(is_active=True)
        elif status == 'inactive':
            query = query.filter_by(is_active=False)
        
        if department:
            query = query.filter_by(department=department)
        
        if search:
            query = query.filter(
                (Employee.first_name.ilike(f'%{search}%')) |
                (Employee.last_name.ilike(f'%{search}%')) |
                (Employee.email.ilike(f'%{search}%')) |
                (Employee.employee_number.ilike(f'%{search}%'))
            )
        
        employees = query.order_by(Employee.first_name).all()
        
        employees_list = []
        for emp in employees:
            employees_list.append({
                'id': emp.id,
                'employee_number': emp.employee_number or '',
                'first_name': emp.first_name or '',
                'last_name': emp.last_name or '',
                'full_name': f"{emp.first_name or ''} {emp.last_name or ''}".strip(),
                'email': emp.email or '',
                'phone': emp.phone or '',
                'position': emp.position or '',
                'department': emp.department or '',
                'employment_type': emp.employment_type or 'FULL_TIME',
                'hire_date': safe_date_iso(emp.hire_date),
                'basic_salary': safe_float(emp.basic_salary),
                'allowances': safe_float(emp.allowances),
                'is_active': bool(emp.is_active),
                'bank_name': emp.bank_name or '',
                'bank_account_number': emp.bank_account_number or '',
                'bank_branch': emp.bank_branch or '',
                'ssnit_number': emp.ssnit_number or '',
                'tax_id': emp.tax_id or ''
            })
        
        return jsonify({
            'employees': employees_list,
            'total': len(employees_list)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting employees: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/employees/<int:employee_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_employee(employee_id):
    """Get a specific employee"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({'error': 'User not found'}), 404
        
        church_id = ensure_user_church(g.current_user)
        
        employee = Employee.query.filter_by(
            id=employee_id, 
            church_id=church_id
        ).first()
        
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        
        return jsonify({
            'id': employee.id,
            'employee_number': employee.employee_number or '',
            'first_name': employee.first_name or '',
            'last_name': employee.last_name or '',
            'full_name': f"{employee.first_name or ''} {employee.last_name or ''}".strip(),
            'email': employee.email or '',
            'phone': employee.phone or '',
            'position': employee.position or '',
            'department': employee.department or '',
            'employment_type': employee.employment_type or 'FULL_TIME',
            'hire_date': safe_date_iso(employee.hire_date),
            'basic_salary': safe_float(employee.basic_salary),
            'allowances': safe_float(employee.allowances),
            'is_active': bool(employee.is_active),
            'bank_name': employee.bank_name or '',
            'bank_account_number': employee.bank_account_number or '',
            'bank_branch': employee.bank_branch or '',
            'ssnit_number': employee.ssnit_number or '',
            'tax_id': employee.tax_id or ''
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting employee: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/employees', methods=['POST', 'OPTIONS'])
@token_required
def create_employee():
    """Create a new employee"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Only admin can create employees'}), 403
        
        church_id = ensure_user_church(g.current_user)
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Generate employee number if not provided
        employee_number = data.get('employee_number')
        if not employee_number:
            year = datetime.now().year
            count = Employee.query.filter(
                Employee.employee_number.like(f'EMP-{year}%')
            ).count() + 1
            employee_number = f"EMP-{year}-{count:04d}"
        
        employee = Employee(
            church_id=church_id,
            employee_number=employee_number,
            first_name=data.get('first_name'),
            last_name=data.get('last_name'),
            email=data.get('email'),
            phone=data.get('phone'),
            position=data.get('position'),
            department=data.get('department'),
            employment_type=data.get('employment_type', 'FULL_TIME'),
            hire_date=datetime.fromisoformat(data.get('hire_date')).date() if data.get('hire_date') else datetime.now().date(),
            basic_salary=data.get('basic_salary', 0),
            allowances=data.get('allowances', 0),
            bank_name=data.get('bank_name'),
            bank_account_number=data.get('bank_account_number'),
            bank_branch=data.get('bank_branch'),
            ssnit_number=data.get('ssnit_number'),
            tax_id=data.get('tax_id'),
            is_active=data.get('is_active', True)
        )
        
        db.session.add(employee)
        db.session.commit()
        
        return jsonify({
            'message': 'Employee created successfully',
            'employee': {
                'id': employee.id,
                'employee_number': employee.employee_number,
                'first_name': employee.first_name,
                'last_name': employee.last_name,
                'full_name': f"{employee.first_name} {employee.last_name}".strip()
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating employee: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/employees/<int:employee_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_employee(employee_id):
    """Update an employee"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Only admin can update employees'}), 403
        
        church_id = ensure_user_church(g.current_user)
        
        employee = Employee.query.filter_by(
            id=employee_id, 
            church_id=church_id
        ).first()
        
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        
        data = request.get_json()
        
        # Update fields
        updatable_fields = [
            'first_name', 'last_name', 'email', 'phone', 'position', 'department',
            'employment_type', 'basic_salary', 'allowances', 'bank_name',
            'bank_account_number', 'bank_branch', 'ssnit_number', 'tax_id', 'is_active'
        ]
        
        for field in updatable_fields:
            if field in data and data[field] is not None:
                setattr(employee, field, data[field])
        
        if 'hire_date' in data and data['hire_date']:
            employee.hire_date = datetime.fromisoformat(data['hire_date']).date()
        
        employee.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'message': 'Employee updated successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating employee: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/employees/<int:employee_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_employee(employee_id):
    """Delete an employee"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Only admin can delete employees'}), 403
        
        church_id = ensure_user_church(g.current_user)
        
        employee = Employee.query.filter_by(
            id=employee_id, 
            church_id=church_id
        ).first()
        
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        
        db.session.delete(employee)
        db.session.commit()
        
        return jsonify({'message': 'Employee deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting employee: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/departments', methods=['GET', 'OPTIONS'])
@token_required
def get_departments():
    """Get unique departments from employees"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        departments = db.session.query(Employee.department).filter(
            Employee.church_id == church_id,
            Employee.department.isnot(None),
            Employee.department != ''
        ).distinct().all()
        
        return jsonify({
            'departments': [d[0] for d in departments if d[0]]
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting departments: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==================== PAYROLL CALCULATION ====================

@payroll_bp.route('/calculate', methods=['POST', 'OPTIONS'])
@token_required
def calculate_payroll():
    """Calculate payroll for a period"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        data = request.get_json() or {}

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        period_start = data.get('period_start')
        period_end = data.get('period_end')
        employee_ids = data.get('employee_ids', [])

        if not period_start or not period_end:
            return jsonify({'error': 'period_start and period_end are required'}), 400

        # Get employees
        query = Employee.query.filter_by(church_id=church_id, is_active=True)
        if employee_ids:
            query = query.filter(Employee.id.in_(employee_ids))
        
        employees = query.all()
        
        if not employees:
            return jsonify({
                'payroll_items': [],
                'total_employees': 0,
                'summary': {
                    'total_gross': 0,
                    'total_ssnit': 0,
                    'total_provident_fund': 0,
                    'total_paye': 0,
                    'total_deductions': 0,
                    'total_net': 0
                },
                'period': {
                    'start': period_start,
                    'end': period_end
                }
            }), 200

        payroll_items = []
        total_gross = 0
        total_ssnit = 0
        total_provident_fund = 0
        total_paye = 0
        total_deductions = 0
        total_net = 0

        for emp in employees:
            gross = safe_float(emp.basic_salary) + safe_float(emp.allowances)
            ssnit = gross * 0.055
            provident = gross * 0.05
            paye = calculate_paye_tax(gross)
            deductions = ssnit + provident + paye
            net = gross - deductions
            
            payroll_items.append({
                'employee_id': emp.id,
                'employee_number': emp.employee_number or '',
                'employee_name': f"{emp.first_name or ''} {emp.last_name or ''}".strip(),
                'position': emp.position or '',
                'department': emp.department or '',
                'gross_salary': round(gross, 2),
                'deductions': {
                    'ssnit_employee': round(ssnit, 2),
                    'provident_fund': round(provident, 2),
                    'paye_tax': round(paye, 2),
                    'total': round(deductions, 2)
                },
                'net_salary': round(net, 2)
            })
            
            total_gross += gross
            total_ssnit += ssnit
            total_provident_fund += provident
            total_paye += paye
            total_deductions += deductions
            total_net += net
        
        return jsonify({
            'payroll_items': payroll_items,
            'total_employees': len(employees),
            'summary': {
                'total_gross': round(total_gross, 2),
                'total_ssnit': round(total_ssnit, 2),
                'total_provident_fund': round(total_provident_fund, 2),
                'total_paye': round(total_paye, 2),
                'total_deductions': round(total_deductions, 2),
                'total_net': round(total_net, 2)
            },
            'period': {
                'start': period_start,
                'end': period_end
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error calculating payroll: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== PAYROLL SUMMARY ====================

@payroll_bp.route('/summary', methods=['GET', 'OPTIONS'])
@token_required
def get_payroll_summary():
    """Get payroll summary for a period"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        period_start = request.args.get('period_start')
        period_end = request.args.get('period_end')
        
        if not period_start or not period_end:
            return jsonify({'error': 'period_start and period_end are required'}), 400
        
        start_date = datetime.fromisoformat(period_start.replace('Z', '+00:00')).date()
        end_date = datetime.fromisoformat(period_end.replace('Z', '+00:00')).date()
        
        # Get active employees
        employees = Employee.query.filter_by(
            church_id=church_id, is_active=True
        ).all()
        
        # Calculate totals
        total_gross_pay = 0
        total_ssnit = 0
        total_paye = 0
        
        for emp in employees:
            gross = safe_float(emp.basic_salary) + safe_float(emp.allowances)
            ssnit = gross * 0.055
            paye = calculate_paye_tax(gross)
            
            total_gross_pay += gross
            total_ssnit += ssnit
            total_paye += paye
        
        total_net_pay = total_gross_pay - total_ssnit - total_paye
        
        return jsonify({
            'period': {
                'start': period_start,
                'end': period_end
            },
            'total_gross_pay': round(total_gross_pay, 2),
            'total_ssnit': round(total_ssnit, 2),
            'total_paye': round(total_paye, 2),
            'total_net_pay': round(total_net_pay, 2),
            'total_employees': len(employees)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting payroll summary: {str(e)}")
        traceback.print_exc()
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
            gross = safe_float(emp.basic_salary) + safe_float(emp.allowances)
            ssnit = gross * 0.055
            provident = gross * 0.05
            paye = calculate_paye_tax(gross)
            deductions = ssnit + provident + paye
            net = gross - deductions
            
            line = PayrollLine(
                payroll_run_id=payroll_run.id,
                employee_id=emp.id,
                basic_salary=gross,
                allowances=safe_float(emp.allowances),
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
        
        payroll_run.total_gross = total_gross
        payroll_run.total_deductions = total_deductions
        payroll_run.total_net = total_net
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll run created successfully',
            'run': {
                'id': payroll_run.id,
                'run_number': payroll_run.run_number,
                'period_start': safe_date_iso(payroll_run.period_start),
                'period_end': safe_date_iso(payroll_run.period_end),
                'payment_date': safe_date_iso(payroll_run.payment_date),
                'status': payroll_run.status,
                'total_gross': safe_float(payroll_run.total_gross),
                'total_deductions': safe_float(payroll_run.total_deductions),
                'total_net': safe_float(payroll_run.total_net),
                'created_at': safe_date_iso(payroll_run.created_at)
            }
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
        
        runs_list = []
        for run in runs:
            employee_count = PayrollLine.query.filter_by(payroll_run_id=run.id).count()
            
            runs_list.append({
                'id': run.id,
                'run_number': run.run_number,
                'period_start': safe_date_iso(run.period_start),
                'period_end': safe_date_iso(run.period_end),
                'payment_date': safe_date_iso(run.payment_date),
                'status': run.status.lower() if run.status else 'draft',
                'total_gross': safe_float(run.total_gross),
                'total_deductions': safe_float(run.total_deductions),
                'total_net': safe_float(run.total_net),
                'employee_count': employee_count,
                'created_at': safe_date_iso(run.created_at)
            })
        
        return jsonify({
            'runs': runs_list,
            'total': len(runs_list)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting payroll runs: {str(e)}")
        traceback.print_exc()
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
        
        return jsonify({
            'id': payroll_run.id,
            'run_number': payroll_run.run_number,
            'period_start': safe_date_iso(payroll_run.period_start),
            'period_end': safe_date_iso(payroll_run.period_end),
            'payment_date': safe_date_iso(payroll_run.payment_date),
            'status': payroll_run.status,
            'total_gross': safe_float(payroll_run.total_gross),
            'total_deductions': safe_float(payroll_run.total_deductions),
            'total_net': safe_float(payroll_run.total_net),
            'created_at': safe_date_iso(payroll_run.created_at),
            'items': [{
                'id': line.id,
                'employee_id': line.employee_id,
                'employee_name': f"{line.employee.first_name} {line.employee.last_name}" if line.employee else 'Unknown',
                'basic_salary': safe_float(line.basic_salary),
                'allowances': safe_float(line.allowances),
                'gross_pay': safe_float(line.gross_earnings),
                'paye_tax': safe_float(line.paye_tax),
                'ssnit': safe_float(line.ssnit_employee),
                'provident_fund': safe_float(line.provident_fund),
                'net_pay': safe_float(line.net_pay)
            } for line in payroll_run.lines]
        }), 200
        
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
            'run': {
                'id': payroll_run.id,
                'run_number': payroll_run.run_number,
                'status': payroll_run.status
            }
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
            'run': {
                'id': payroll_run.id,
                'run_number': payroll_run.run_number,
                'status': payroll_run.status
            }
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
        
        # Update payroll run status
        payroll_run.status = 'PROCESSED'
        payroll_run.processed_by = current_user.id if current_user else None
        payroll_run.processed_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll processed successfully',
            'run': {
                'id': payroll_run.id,
                'run_number': payroll_run.run_number,
                'status': payroll_run.status
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing payroll run: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==================== TAX TABLES MANAGEMENT ====================

@payroll_bp.route('/tax-tables', methods=['GET', 'OPTIONS'])
@token_required
def get_tax_tables():
    """Get tax tables for PAYE calculation"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        year = request.args.get('year', datetime.now().year, type=int)
        
        # Default Ghana tax brackets
        tax_brackets = [
            {'min_income': 0, 'max_income': 402, 'rate': 0, 'base_tax': 0},
            {'min_income': 402, 'max_income': 490, 'rate': 0.05, 'base_tax': 0},
            {'min_income': 490, 'max_income': 644, 'rate': 0.10, 'base_tax': 4.40},
            {'min_income': 644, 'max_income': 971, 'rate': 0.175, 'base_tax': 19.80},
            {'min_income': 971, 'max_income': 1632, 'rate': 0.25, 'base_tax': 77.00},
            {'min_income': 1632, 'max_income': 3227, 'rate': 0.30, 'base_tax': 242.25},
            {'min_income': 3227, 'max_income': None, 'rate': 0.35, 'base_tax': 720.75}
        ]
        
        return jsonify({
            'year': year,
            'tax_brackets': tax_brackets,
            'ssnit_rates': {
                'employee_rate': 0.055,
                'employer_rate': 0.13,
                'max_earnings': None
            },
            'currency': 'GHS',
            'is_default': True
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting tax tables: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/deduction-types', methods=['GET', 'OPTIONS'])
@token_required
def get_deduction_types():
    """Get deduction types"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        deduction_types = [
            {'id': 1, 'name': 'PAYE Tax', 'code': 'PAYE', 'is_percentage': True, 'rate': 0.10, 'description': 'Pay As You Earn tax'},
            {'id': 2, 'name': 'SSNIT', 'code': 'SSNIT', 'is_percentage': True, 'rate': 0.055, 'description': 'Social Security contribution'},
            {'id': 3, 'name': 'Provident Fund', 'code': 'PROVIDENT', 'is_percentage': True, 'rate': 0.05, 'description': 'Employee provident fund'},
            {'id': 4, 'name': 'Health Insurance', 'code': 'HEALTH', 'is_percentage': False, 'description': 'Health insurance premium'},
            {'id': 5, 'name': 'Loan Repayment', 'code': 'LOAN', 'is_percentage': False, 'description': 'Staff loan repayment'},
            {'id': 6, 'name': 'Union Dues', 'code': 'UNION', 'is_percentage': False, 'description': 'Trade union dues'},
        ]
        
        return jsonify({
            'deduction_types': deduction_types,
            'total': len(deduction_types)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting deduction types: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==================== TEST ENDPOINTS ====================

@payroll_bp.route('/test-payroll-runs', methods=['GET'])
@token_required
def test_payroll_runs():
    """Test endpoint to debug payroll runs"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        result = db.session.execute(
            text("SELECT id, run_number, status FROM payroll_runs WHERE church_id = :church_id"),
            {'church_id': church_id}
        ).fetchall()
        
        runs = []
        for row in result:
            runs.append({
                'id': row[0],
                'run_number': row[1],
                'status': row[2]
            })
        
        return jsonify({
            'success': True,
            'count': len(runs),
            'runs': runs,
            'church_id': church_id
        }), 200
        
    except Exception as e:
        print(f"ERROR in test endpoint: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500

# Add to payroll_routes.py after the other endpoints

@payroll_bp.route('/payslips', methods=['GET', 'OPTIONS'])
@token_required
def get_payslips():
    """Get all payslips with optional filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        run_id = request.args.get('run_id', type=int)
        employee_id = request.args.get('employee_id', type=int)
        
        # If no Payslip model exists yet, we need to generate them on the fly
        # For now, let's return payslip data from payroll runs
        
        # Get payroll runs
        query = PayrollRun.query.filter_by(church_id=church_id)
        
        if run_id:
            query = query.filter_by(id=run_id)
        
        runs = query.order_by(PayrollRun.created_at.desc()).all()
        
        payslips_list = []
        for run in runs:
            # Get lines for this run
            lines = PayrollLine.query.filter_by(payroll_run_id=run.id).all()
            
            for line in lines:
                employee = Employee.query.get(line.employee_id)
                if employee:
                    # Filter by employee if specified
                    if employee_id and employee.id != employee_id:
                        continue
                    
                    payslips_list.append({
                        'id': line.id,
                        'employee_id': employee.id,
                        'employee_name': f"{employee.first_name or ''} {employee.last_name or ''}".strip(),
                        'employee_code': employee.employee_number,
                        'payroll_run_id': run.id,
                        'run_number': run.run_number,
                        'period_start': safe_date_iso(run.period_start),
                        'period_end': safe_date_iso(run.period_end),
                        'payment_date': safe_date_iso(run.payment_date),
                        'gross_pay': safe_float(line.gross_earnings),
                        'net_pay': safe_float(line.net_pay),
                        'basic_salary': safe_float(line.basic_salary),
                        'allowances': safe_float(line.allowances),
                        'deductions': {
                            'ssnit': safe_float(line.ssnit_employee),
                            'provident_fund': safe_float(line.provident_fund),
                            'paye_tax': safe_float(line.paye_tax),
                            'total': safe_float(line.total_deductions)
                        },
                        'generated_at': safe_date_iso(run.created_at),
                        'status': run.status.lower() if run.status else 'draft',
                        'email_sent': False
                    })
        
        return jsonify({
            'payslips': payslips_list,
            'total': len(payslips_list)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting payslips: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/<int:run_id>/payslips', methods=['GET', 'OPTIONS'])
@token_required
def get_run_payslips(run_id):
    """Get payslips for a specific payroll run"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        
        run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        if not run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        lines = PayrollLine.query.filter_by(payroll_run_id=run.id).all()
        
        payslips_list = []
        for line in lines:
            employee = Employee.query.get(line.employee_id)
            if employee:
                payslips_list.append({
                    'id': line.id,
                    'employee_id': employee.id,
                    'employee_name': f"{employee.first_name or ''} {employee.last_name or ''}".strip(),
                    'employee_code': employee.employee_number,
                    'position': employee.position or '',
                    'department': employee.department or '',
                    'gross_pay': safe_float(line.gross_earnings),
                    'net_pay': safe_float(line.net_pay),
                    'basic_salary': safe_float(line.basic_salary),
                    'allowances': safe_float(line.allowances),
                    'deductions': {
                        'ssnit': safe_float(line.ssnit_employee),
                        'provident_fund': safe_float(line.provident_fund),
                        'paye_tax': safe_float(line.paye_tax),
                        'total': safe_float(line.total_deductions)
                    },
                    'payment_date': safe_date_iso(run.payment_date),
                    'period_start': safe_date_iso(run.period_start),
                    'period_end': safe_date_iso(run.period_end),
                    'generated_at': safe_date_iso(run.created_at)
                })
        
        return jsonify({
            'payslips': payslips_list,
            'run': {
                'id': run.id,
                'run_number': run.run_number,
                'period_start': safe_date_iso(run.period_start),
                'period_end': safe_date_iso(run.period_end),
                'payment_date': safe_date_iso(run.payment_date),
                'status': run.status.lower() if run.status else 'draft'
            },
            'total': len(payslips_list)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting run payslips: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/employees/<int:employee_id>/payslip', methods=['GET', 'OPTIONS'])
@token_required
def get_employee_payslip(employee_id):
    """Get payslip for a specific employee and run"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        run_id = request.args.get('run_id', type=int)
        
        if not run_id:
            return jsonify({'error': 'run_id is required'}), 400
        
        # Get employee
        employee = Employee.query.filter_by(id=employee_id, church_id=church_id).first()
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        
        # Get payroll run
        run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        if not run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        # Get payroll line
        line = PayrollLine.query.filter_by(
            payroll_run_id=run.id,
            employee_id=employee.id
        ).first()
        
        if not line:
            return jsonify({'error': 'No payslip found for this employee and period'}), 404
        
        return jsonify({
            'payslip': {
                'id': line.id,
                'employee_id': employee.id,
                'employee_name': f"{employee.first_name or ''} {employee.last_name or ''}".strip(),
                'employee_code': employee.employee_number,
                'position': employee.position or '',
                'department': employee.department or '',
                'run_number': run.run_number,
                'period_start': safe_date_iso(run.period_start),
                'period_end': safe_date_iso(run.period_end),
                'payment_date': safe_date_iso(run.payment_date),
                'gross_pay': safe_float(line.gross_earnings),
                'net_pay': safe_float(line.net_pay),
                'basic_salary': safe_float(line.basic_salary),
                'allowances': safe_float(line.allowances),
                'deductions': {
                    'ssnit': safe_float(line.ssnit_employee),
                    'provident_fund': safe_float(line.provident_fund),
                    'paye_tax': safe_float(line.paye_tax),
                    'total': safe_float(line.total_deductions)
                },
                'generated_at': safe_date_iso(run.created_at)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting employee payslip: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/employees/<int:employee_id>/payslip/download', methods=['GET', 'OPTIONS'])
@token_required
def download_payslip(employee_id):
    """Download payslip as PDF"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        run_id = request.args.get('run_id', type=int)
        
        if not run_id:
            return jsonify({'error': 'run_id is required'}), 400
        
        # Get employee and payslip data
        employee = Employee.query.filter_by(id=employee_id, church_id=church_id).first()
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        
        run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        if not run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        line = PayrollLine.query.filter_by(
            payroll_run_id=run.id,
            employee_id=employee.id
        ).first()
        
        if not line:
            return jsonify({'error': 'No payslip found'}), 404
        
        # Generate PDF (simplified - you'd use reportlab or similar)
        # For now, return JSON that can be used to generate PDF client-side
        return jsonify({
            'payslip': {
                'employee_name': f"{employee.first_name or ''} {employee.last_name or ''}".strip(),
                'employee_code': employee.employee_number,
                'position': employee.position or '',
                'department': employee.department or '',
                'period': f"{run.period_start.strftime('%B %Y')}",
                'run_number': run.run_number,
                'payment_date': run.payment_date.strftime('%B %d, %Y'),
                'gross_pay': safe_float(line.gross_earnings),
                'net_pay': safe_float(line.net_pay),
                'basic_salary': safe_float(line.basic_salary),
                'allowances': safe_float(line.allowances),
                'ssnit': safe_float(line.ssnit_employee),
                'provident_fund': safe_float(line.provident_fund),
                'paye_tax': safe_float(line.paye_tax),
                'total_deductions': safe_float(line.total_deductions)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error downloading payslip: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/<int:run_id>/email-payslips', methods=['POST', 'OPTIONS'])
@token_required
def email_payslips(run_id):
    """Email payslips for a payroll run"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        data = request.get_json() or {}
        employee_ids = data.get('employee_ids', [])
        
        run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        if not run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        lines = PayrollLine.query.filter_by(payroll_run_id=run.id).all()
        
        if employee_ids:
            lines = [l for l in lines if l.employee_id in employee_ids]
        
        emailed_count = 0
        for line in lines:
            employee = Employee.query.get(line.employee_id)
            if employee and employee.email:
                # Here you would implement actual email sending
                # For now, just count them
                emailed_count += 1
        
        return jsonify({
            'message': f'Successfully queued {emailed_count} payslips for email',
            'sent_count': emailed_count,
            'total': len(lines)
        }), 200
        
    except Exception as e:
        logger.error(f"Error emailing payslips: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
@payroll_bp.route('/runs/<int:run_id>/post-journal', methods=['POST'])
@token_required
def post_payroll_journal(run_id):
    """Post payroll run to general ledger"""
    try:
        church_id = ensure_user_church(g.current_user)
        current_user = get_current_user()
        
        # Get the payroll run
        payroll_run = PayrollRun.query.filter_by(
            id=run_id,
            church_id=church_id
        ).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        # Check if already posted
        if payroll_run.status in ['PROCESSED', 'POSTED']:
            return jsonify({'error': 'Payroll run already posted to ledger'}), 400
        
        # Check if approved
        if payroll_run.status != 'APPROVED':
            return jsonify({'error': f'Cannot post payroll run with status: {payroll_run.status}. Must be APPROVED first.'}), 400
        
        # Get salary expense account (Staff Cost)
        salary_account = Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'EXPENSE',
            Account.is_active == True,
            db.or_(
                Account.account_code == '5030',
                Account.name.ilike('%staff%'),
                Account.name.ilike('%salary%')
            )
        ).first()
        
        if not salary_account:
            # Create a default salary expense account
            salary_account = Account(
                church_id=church_id,
                account_code='5030',
                name='Staff Cost',
                display_name='5030 - Staff Cost',
                account_type='EXPENSE',
                category='Staff Cost',
                level=2,
                opening_balance=0,
                current_balance=0,
                normal_balance='debit',
                description='Staff salaries and wages',
                is_active=True
            )
            db.session.add(salary_account)
            db.session.flush()
            print("✅ Created default salary expense account")
        
        # Get cash/bank account for payment
        cash_account = Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'ASSET',
            Account.is_active == True,
            db.or_(
                Account.account_code == '1010',
                Account.name.ilike('%cash%'),
                Account.name.ilike('%bank%')
            )
        ).first()
        
        if not cash_account:
            # Create a default cash account
            cash_account = Account(
                church_id=church_id,
                account_code='1010',
                name='Cash',
                display_name='1010 - Cash',
                account_type='ASSET',
                category='Cash',
                level=2,
                opening_balance=0,
                current_balance=0,
                normal_balance='debit',
                description='Cash on hand',
                is_active=True
            )
            db.session.add(cash_account)
            db.session.flush()
            print("✅ Created default cash account")
        
        # Get SSNIT Payable account
        ssnit_payable = Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'LIABILITY',
            Account.is_active == True,
            db.or_(
                Account.account_code == '2050',
                Account.name.ilike('%ssnit%')
            )
        ).first()
        
        if not ssnit_payable:
            # Create default SSNIT Payable account
            ssnit_payable = Account(
                church_id=church_id,
                account_code='2050',
                name='SSNIT Payable',
                display_name='2050 - SSNIT Payable',
                account_type='LIABILITY',
                category='Statutory',
                level=2,
                opening_balance=0,
                current_balance=0,
                normal_balance='credit',
                description='SSNIT contributions payable to SSNIT',
                is_active=True
            )
            db.session.add(ssnit_payable)
            db.session.flush()
            print("✅ Created default SSNIT Payable account")
        
        # Get PAYE Payable account
        paye_payable = Account.query.filter(
            Account.church_id == church_id,
            Account.account_type == 'LIABILITY',
            Account.is_active == True,
            db.or_(
                Account.account_code == '2040',
                Account.name.ilike('%paye%')
            )
        ).first()
        
        if not paye_payable:
            # Create default PAYE Payable account
            paye_payable = Account(
                church_id=church_id,
                account_code='2040',
                name='PAYE Payable',
                display_name='2040 - PAYE Payable',
                account_type='LIABILITY',
                category='Taxes',
                level=2,
                opening_balance=0,
                current_balance=0,
                normal_balance='credit',
                description='PAYE tax payable to GRA',
                is_active=True
            )
            db.session.add(paye_payable)
            db.session.flush()
            print("✅ Created default PAYE Payable account")
        
        # Create journal entry
        entry_date = datetime.utcnow().date()
        
        # Generate entry number
        year = entry_date.year
        month = entry_date.month
        count = JournalEntry.query.filter(
            JournalEntry.entry_number.like(f'JE-{year}-{month:02d}%')
        ).count() + 1
        entry_number = f"JE-{year}-{month:02d}-{count:03d}"
        
        # Calculate totals
        lines = PayrollLine.query.filter_by(payroll_run_id=payroll_run.id).all()
        
        total_gross = sum(float(line.gross_earnings) for line in lines)
        total_ssnit = sum(float(line.ssnit_employee) for line in lines)
        total_paye = sum(float(line.paye_tax) for line in lines)
        total_net = sum(float(line.net_pay) for line in lines)
        
        print(f"Payroll totals - Gross: {total_gross}, SSNIT: {total_ssnit}, PAYE: {total_paye}, Net: {total_net}")
        
        # Create journal entry
        journal_entry = JournalEntry(
            church_id=church_id,
            entry_number=entry_number,
            entry_date=entry_date,
            description=f"Payroll for {payroll_run.period_start.strftime('%B %Y')} - Run: {payroll_run.run_number}",
            status='POSTED',
            created_by=current_user.id if current_user else None,
            posted_by=current_user.id if current_user else None,
            posted_at=datetime.utcnow()
        )
        
        db.session.add(journal_entry)
        db.session.flush()
        
        # Add journal lines
        # Line 1: Salary Expense (Debit)
        line1 = JournalLine(
            journal_entry_id=journal_entry.id,
            account_id=salary_account.id,
            debit=total_gross,
            credit=0,
            description=f"Gross salary for {payroll_run.period_start.strftime('%B %Y')}"
        )
        db.session.add(line1)
        
        # Line 2: Cash/Bank (Credit - Net Pay)
        line2 = JournalLine(
            journal_entry_id=journal_entry.id,
            account_id=cash_account.id,
            debit=0,
            credit=total_net,
            description=f"Net salary payment for {payroll_run.period_start.strftime('%B %Y')}"
        )
        db.session.add(line2)
        
        # Line 3: SSNIT Payable (Credit)
        if total_ssnit > 0:
            line3 = JournalLine(
                journal_entry_id=journal_entry.id,
                account_id=ssnit_payable.id,
                debit=0,
                credit=total_ssnit,
                description=f"SSNIT contribution for {payroll_run.period_start.strftime('%B %Y')}"
            )
            db.session.add(line3)
        
        # Line 4: PAYE Payable (Credit)
        if total_paye > 0:
            line4 = JournalLine(
                journal_entry_id=journal_entry.id,
                account_id=paye_payable.id,
                debit=0,
                credit=total_paye,
                description=f"PAYE tax for {payroll_run.period_start.strftime('%B %Y')}"
            )
            db.session.add(line4)
        
        # Update payroll run status
        payroll_run.status = 'PROCESSED'
        payroll_run.processed_by = current_user.id if current_user else None
        payroll_run.processed_at = datetime.utcnow()
        payroll_run.journal_entry_id = journal_entry.id
        
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll posted to ledger successfully',
            'journal_entry': {
                'id': journal_entry.id,
                'entry_number': journal_entry.entry_number,
                'description': journal_entry.description,
                'total_debit': total_gross,
                'total_credit': total_gross
            },
            'run': {
                'id': payroll_run.id,
                'run_number': payroll_run.run_number,
                'status': payroll_run.status
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error posting payroll journal: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500