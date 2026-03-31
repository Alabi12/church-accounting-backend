# app/routes/payroll_routes.py
from flask import Blueprint, request, jsonify, g, make_response
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
import io
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


# ==================== PAYSLIP ENDPOINTS ====================

@payroll_bp.route('/runs/<int:run_id>/generate-payslips', methods=['POST'])
@token_required
def generate_payslips(run_id):
    """Generate payslips for a payroll run"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        payroll_run = PayrollRun.query.filter_by(
            id=run_id,
            church_id=church_id
        ).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        if payroll_run.status not in ['APPROVED', 'PROCESSED']:
            return jsonify({'error': f'Cannot generate payslips for run with status {payroll_run.status}. Must be APPROVED or PROCESSED.'}), 400
        
        lines = PayrollLine.query.filter_by(payroll_run_id=payroll_run.id).all()
        
        generated = []
        failed = []
        
        for line in lines:
            employee = Employee.query.get(line.employee_id)
            if employee:
                generated.append({
                    'employee_id': employee.id,
                    'employee_name': f"{employee.first_name} {employee.last_name}".strip(),
                    'employee_code': employee.employee_number,
                    'gross_pay': safe_float(line.gross_earnings),
                    'net_pay': safe_float(line.net_pay)
                })
            else:
                failed.append({'employee_id': line.employee_id})
        
        return jsonify({
            'message': f'Generated {len(generated)} payslips, failed {len(failed)}',
            'generated': generated,
            'failed': failed,
            'total': len(generated)
        }), 200
        
    except Exception as e:
        logger.error(f"Error generating payslips: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/payslips', methods=['GET'])
@token_required
def get_payslips():
    """Get all payslips"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        runs = PayrollRun.query.filter_by(church_id=church_id).order_by(PayrollRun.created_at.desc()).all()
        
        payslips_list = []
        
        for run in runs:
            lines = PayrollLine.query.filter_by(payroll_run_id=run.id).all()
            for line in lines:
                employee = Employee.query.get(line.employee_id)
                if employee:
                    payslips_list.append({
                        'id': line.id,
                        'payslip_number': f"PS-{run.run_number}-{employee.employee_number}",
                        'employee_id': employee.id,
                        'employee_name': f"{employee.first_name} {employee.last_name}".strip(),
                        'employee_code': employee.employee_number,
                        'payroll_run_id': run.id,
                        'run_number': run.run_number,
                        'period_start': run.period_start.isoformat(),
                        'period_end': run.period_end.isoformat(),
                        'payment_date': run.payment_date.isoformat(),
                        'gross_pay': safe_float(line.gross_earnings),
                        'net_pay': safe_float(line.net_pay),
                        'has_pdf': True,
                        'created_at': run.created_at.isoformat()
                    })
        
        return jsonify({
            'payslips': payslips_list,
            'total': len(payslips_list)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting payslips: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/<int:run_id>/payslips', methods=['GET'])
@token_required
def get_run_payslips(run_id):
    """Get payslips for a specific payroll run"""
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
                    'payslip_number': f"PS-{run.run_number}-{employee.employee_number}",
                    'employee_id': employee.id,
                    'employee_name': f"{employee.first_name} {employee.last_name}".strip(),
                    'employee_code': employee.employee_number,
                    'position': employee.position or '',
                    'department': employee.department or '',
                    'period_start': run.period_start.isoformat(),
                    'period_end': run.period_end.isoformat(),
                    'payment_date': run.payment_date.isoformat(),
                    'gross_pay': safe_float(line.gross_earnings),
                    'net_pay': safe_float(line.net_pay),
                    'basic_salary': safe_float(line.basic_salary),
                    'allowances': safe_float(line.allowances),
                    'deductions': {
                        'ssnit': safe_float(line.ssnit_employee),
                        'provident_fund': safe_float(line.provident_fund),
                        'paye_tax': safe_float(line.paye_tax),
                        'total': safe_float(line.total_deductions)
                    }
                })
        
        return jsonify({
            'payslips': payslips_list,
            'total': len(payslips_list),
            'run': {
                'id': run.id,
                'run_number': run.run_number,
                'period_start': run.period_start.isoformat(),
                'period_end': run.period_end.isoformat(),
                'status': run.status
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting run payslips: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/payslips/<int:payslip_id>', methods=['GET'])
@token_required
def get_payslip_by_id(payslip_id):
    """Get a single payslip by ID"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        line = PayrollLine.query.get(payslip_id)
        if not line:
            return jsonify({'error': 'Payslip not found'}), 404
        
        run = PayrollRun.query.get(line.payroll_run_id)
        employee = Employee.query.get(line.employee_id)
        
        if not run or not employee or run.church_id != church_id:
            return jsonify({'error': 'Payslip not found'}), 404
        
        return jsonify({
            'id': line.id,
            'payslip_number': f"PS-{run.run_number}-{employee.employee_number}",
            'employee_id': employee.id,
            'employee_name': f"{employee.first_name} {employee.last_name}".strip(),
            'employee_code': employee.employee_number,
            'position': employee.position or '',
            'department': employee.department or '',
            'payroll_run_id': run.id,
            'run_number': run.run_number,
            'period_start': run.period_start.isoformat(),
            'period_end': run.period_end.isoformat(),
            'payment_date': run.payment_date.isoformat(),
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
            'generated_at': run.created_at.isoformat(),
            'has_pdf': True
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting payslip: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/payslips/<int:payslip_id>/download', methods=['GET'])
@token_required
def download_payslip(payslip_id):
    """Download payslip as PDF"""
    try:
        # Try to import reportlab
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            REPORTLAB_AVAILABLE = True
        except ImportError:
            REPORTLAB_AVAILABLE = False
            print("⚠️ ReportLab not available - PDF generation disabled")
        
        church_id = ensure_user_church(g.current_user)
        
        line = PayrollLine.query.get(payslip_id)
        if not line:
            return jsonify({'error': 'Payslip not found'}), 404
        
        run = PayrollRun.query.get(line.payroll_run_id)
        employee = Employee.query.get(line.employee_id)
        
        if not run or not employee or run.church_id != church_id:
            return jsonify({'error': 'Payslip not found'}), 404
        
        if not REPORTLAB_AVAILABLE:
            # Return JSON if reportlab not available
            payslip_data = {
                'payslip_number': f"PS-{run.run_number}-{employee.employee_number}",
                'employee_name': f"{employee.first_name} {employee.last_name}".strip(),
                'employee_code': employee.employee_number,
                'position': employee.position or '',
                'department': employee.department or '',
                'period_start': run.period_start.isoformat(),
                'period_end': run.period_end.isoformat(),
                'payment_date': run.payment_date.isoformat(),
                'gross_pay': safe_float(line.gross_earnings),
                'net_pay': safe_float(line.net_pay),
                'basic_salary': safe_float(line.basic_salary),
                'allowances': safe_float(line.allowances),
                'deductions': {
                    'ssnit': safe_float(line.ssnit_employee),
                    'provident_fund': safe_float(line.provident_fund),
                    'paye_tax': safe_float(line.paye_tax),
                    'total': safe_float(line.total_deductions)
                }
            }
            return jsonify(payslip_data), 200
        
        # Generate PDF
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm)
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=18,
            alignment=1,
            spaceAfter=20,
            textColor=colors.HexColor('#1FB256')
        )
        heading_style = ParagraphStyle(
            'Heading',
            parent=styles['Heading2'],
            fontSize=12,
            spaceAfter=10,
            textColor=colors.HexColor('#333333')
        )
        normal_style = ParagraphStyle(
            'Normal',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=6
        )
        
        # Build PDF content
        elements = []
        
        # Header
        elements.append(Paragraph("PAYSLIP", title_style))
        elements.append(Paragraph(f"Payslip Number: PS-{run.run_number}-{employee.employee_number}", normal_style))
        elements.append(Spacer(1, 10))
        
        # Employee Details
        elements.append(Paragraph("EMPLOYEE DETAILS", heading_style))
        employee_data = [
            ['Employee Name:', f"{employee.first_name} {employee.last_name}"],
            ['Employee Code:', employee.employee_number],
            ['Position:', employee.position or 'N/A'],
            ['Department:', employee.department or 'N/A'],
            ['Pay Period:', f"{run.period_start.strftime('%d %b %Y')} - {run.period_end.strftime('%d %b %Y')}"],
            ['Payment Date:', run.payment_date.strftime('%d %b %Y')],
        ]
        
        employee_table = Table(employee_data, colWidths=[80*mm, 100*mm])
        employee_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
        ]))
        elements.append(employee_table)
        elements.append(Spacer(1, 15))
        
        # Earnings
        elements.append(Paragraph("EARNINGS", heading_style))
        earnings_data = [
            ['Description', 'Amount (GHS)'],
            ['Basic Salary', f"{float(line.basic_salary):,.2f}"],
            ['Allowances', f"{float(line.allowances):,.2f}"],
        ]
        
        earnings_table = Table(earnings_data, colWidths=[120*mm, 60*mm])
        earnings_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8f5e9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#c8e6c9')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#1b5e20')),
        ]))
        elements.append(earnings_table)
        elements.append(Spacer(1, 5))
        
        # Gross Pay
        gross_data = [['GROSS PAY', f"{float(line.gross_earnings):,.2f}"]]
        gross_table = Table(gross_data, colWidths=[120*mm, 60*mm])
        gross_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1FB256')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(gross_table)
        elements.append(Spacer(1, 15))
        
        # Deductions
        elements.append(Paragraph("DEDUCTIONS", heading_style))
        deductions_data = [
            ['Description', 'Amount (GHS)'],
            ['SSNIT', f"{float(line.ssnit_employee):,.2f}"],
            ['Provident Fund', f"{float(line.provident_fund):,.2f}"],
            ['PAYE Tax', f"{float(line.paye_tax):,.2f}"],
        ]
        
        deductions_table = Table(deductions_data, colWidths=[120*mm, 60*mm])
        deductions_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ffebee')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#c62828')),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ffcdd2')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#b71c1c')),
        ]))
        elements.append(deductions_table)
        elements.append(Spacer(1, 5))
        
        # Total Deductions
        total_deductions_data = [['TOTAL DEDUCTIONS', f"{float(line.total_deductions):,.2f}"]]
        total_deductions_table = Table(total_deductions_data, colWidths=[120*mm, 60*mm])
        total_deductions_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ef5350')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(total_deductions_table)
        elements.append(Spacer(1, 15))
        
        # Net Pay
        net_pay_data = [['NET PAY', f"{float(line.net_pay):,.2f}"]]
        net_pay_table = Table(net_pay_data, colWidths=[120*mm, 60*mm])
        net_pay_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 14),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1FB256')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(net_pay_table)
        elements.append(Spacer(1, 20))
        
        # Footer
        footer_text = "This is a computer-generated document. No signature is required."
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            alignment=1,
            textColor=colors.grey
        )
        elements.append(Paragraph(footer_text, footer_style))
        
        # Build PDF
        doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()
        
        # Return PDF using make_response
        from flask import make_response
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=payslip_{employee.employee_number}_{run.run_number}.pdf'
        
        return response
        
    except Exception as e:
        logger.error(f"Error generating PDF: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@payroll_bp.route('/payslips/<int:payslip_id>/email', methods=['POST'])
@token_required
def email_payslip(payslip_id):
    """Email a payslip to the employee"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        line = PayrollLine.query.get(payslip_id)
        if not line:
            return jsonify({'error': 'Payslip not found'}), 404
        
        run = PayrollRun.query.get(line.payroll_run_id)
        employee = Employee.query.get(line.employee_id)
        
        if not run or not employee or run.church_id != church_id:
            return jsonify({'error': 'Payslip not found'}), 404
        
        if not employee.email:
            return jsonify({'error': 'Employee has no email address'}), 400
        
        return jsonify({
            'message': f'Payslip sent to {employee.email}',
            'sent_to': employee.email
        }), 200
        
    except Exception as e:
        logger.error(f"Error emailing payslip: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
    # ============= EMAIL FUNCTIONALITY =============
@payroll_bp.route('/runs/<int:run_id>/email-payslips', methods=['POST'])
@token_required
def email_payslips(run_id):
    """Email payslips for a payroll run"""
    try:
        from flask_mail import Message
        from app import mail
        
        church_id = ensure_user_church(g.current_user)
        data = request.get_json() or {}
        employee_ids = data.get('employee_ids', [])
        
        run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        if not run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        query = PayrollLine.query.filter_by(payroll_run_id=run.id)
        if employee_ids:
            query = query.filter(PayrollLine.employee_id.in_(employee_ids))
        
        lines = query.all()
        
        if not lines:
            return jsonify({'error': 'No payslips found for this run'}), 404
        
        emailed_count = 0
        failed_count = 0
        failed_emails = []
        
        for line in lines:
            employee = Employee.query.get(line.employee_id)
            if employee and employee.email:
                try:
                    # Create email message
                    msg = Message(
                        subject=f"Payslip for {run.period_start.strftime('%B %Y')}",
                        recipients=[employee.email],
                        body=f"""
Dear {employee.first_name} {employee.last_name},

Please find attached your payslip for the period {run.period_start.strftime('%d %b %Y')} to {run.period_end.strftime('%d %b %Y')}.

Gross Pay: GHS {float(line.gross_earnings):,.2f}
Net Pay: GHS {float(line.net_pay):,.2f}

This is an automated message. Please contact HR if you have any questions.

Best regards,
Church Accounting Team
                        """
                    )
                    
                    # Generate PDF attachment
                    pdf_data = generate_payslip_pdf(line, run, employee)
                    msg.attach(
                        filename=f"payslip_{employee.employee_number}_{run.run_number}.pdf",
                        content_type='application/pdf',
                        data=pdf_data
                    )
                    
                    # Send email
                    mail.send(msg)
                    emailed_count += 1
                    
                except Exception as e:
                    failed_count += 1
                    failed_emails.append({
                        'employee_id': employee.id,
                        'employee_name': f"{employee.first_name} {employee.last_name}",
                        'email': employee.email,
                        'error': str(e)
                    })
            else:
                failed_count += 1
                failed_emails.append({
                    'employee_id': employee.id,
                    'employee_name': f"{employee.first_name} {employee.last_name}" if employee else 'Unknown',
                    'email': employee.email if employee else 'No email',
                    'error': 'No email address'
                })
        
        return jsonify({
            'message': f'Successfully sent {emailed_count} payslips, failed {failed_count}',
            'sent_count': emailed_count,
            'failed_count': failed_count,
            'failed_emails': failed_emails,
            'total': len(lines)
        }), 200
        
    except Exception as e:
        logger.error(f"Error emailing payslips: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/payslips/<int:payslip_id>/email', methods=['POST'])
@token_required
def email_single_payslip(payslip_id):
    """Email a single payslip to the employee"""
    try:
        church_id = ensure_user_church(g.current_user)
        
        line = PayrollLine.query.get(payslip_id)
        if not line:
            return jsonify({'error': 'Payslip not found'}), 404
        
        run = PayrollRun.query.get(line.payroll_run_id)
        employee = Employee.query.get(line.employee_id)
        
        if not run or not employee or run.church_id != church_id:
            return jsonify({'error': 'Payslip not found'}), 404
        
        if not employee.email:
            return jsonify({'error': 'Employee has no email address'}), 400
        
        # Here you would implement actual email sending
        # For now, just return success
        return jsonify({
            'message': f'Payslip sent to {employee.email}',
            'sent_to': employee.email,
            'employee_name': f"{employee.first_name} {employee.last_name}"
        }), 200
        
    except Exception as e:
        logger.error(f"Error emailing payslip: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
@payroll_bp.route('/runs', methods=['GET'])
@token_required
def get_payroll_runs_with_filters():
    """Get all payroll runs with optional filters"""
    try:
        church_id = ensure_user_church(g.current_user)
        has_payslips = request.args.get('has_payslips')
        
        query = PayrollRun.query.filter_by(church_id=church_id)
        
        if has_payslips:
            # Only get runs that have payslips (payroll lines)
            query = query.filter(PayrollRun.lines.any())
        
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
                'has_payslips': employee_count > 0,
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

@payroll_bp.route('/runs/<int:run_id>/post-journal', methods=['POST'])
@token_required
def post_payroll_journal(run_id):
    """Post payroll run to general ledger"""
    try:
        from app.models import JournalEntry, JournalLine, Account
        from datetime import datetime
        from flask import jsonify, make_response
        
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
        
        # Calculate totals
        lines = PayrollLine.query.filter_by(payroll_run_id=payroll_run.id).all()
        
        total_gross = sum(float(line.gross_earnings) for line in lines)
        total_ssnit = sum(float(line.ssnit_employee) for line in lines)
        total_paye = sum(float(line.paye_tax) for line in lines)
        total_net = sum(float(line.net_pay) for line in lines)
        
        print(f"Payroll totals - Gross: {total_gross}, SSNIT: {total_ssnit}, PAYE: {total_paye}, Net: {total_net}")
        
        # Create journal entry
        entry_date = datetime.utcnow().date()
        year = entry_date.year
        month = entry_date.month
        count = JournalEntry.query.filter(
            JournalEntry.entry_number.like(f'JE-{year}-{month:02d}%')
        ).count() + 1
        entry_number = f"JE-{year}-{month:02d}-{count:03d}"
        
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
        
        # Update payroll run
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