from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import (
    Employee, PayrollRun, PayrollLine,
    User, JournalEntry, JournalLine,
    Account, AuditLog, Church
)
from app.extensions import db
from datetime import datetime, timedelta
from sqlalchemy import func, and_, extract, text
import traceback
import logging
from decimal import Decimal

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


def calculate_paye_tax(gross_salary):
    """Calculate PAYE tax based on Ghana tax brackets"""
    gross = float(gross_salary)
    
    if gross <= 402:
        tax = 0
    elif gross <= 490:
        tax = (gross - 402) * 0.05
    elif gross <= 644:
        tax = 4.40 + (gross - 490) * 0.10
    elif gross <= 971:
        tax = 19.80 + (gross - 644) * 0.175
    elif gross <= 1632:
        tax = 77.00 + (gross - 971) * 0.25
    elif gross <= 3227:
        tax = 242.25 + (gross - 1632) * 0.30
    else:
        tax = 720.75 + (gross - 3227) * 0.35
    
    return round(tax, 2)


def calculate_employee_payroll(employee, period_start, period_end):
    """Helper function to calculate payroll for a single employee"""
    try:
        basic_salary = float(employee.basic_salary) if employee.basic_salary else 0.0
        allowances = float(employee.allowances) if employee.allowances else 0.0
        gross_salary = basic_salary + allowances
        ssnit_employee = gross_salary * 0.055
        ssnit_employer = gross_salary * 0.13
        tax = calculate_paye_tax(gross_salary)
        total_deductions = ssnit_employee + tax
        net_salary = gross_salary - total_deductions
        
        return {
            'employee_id': employee.id,
            'employee_number': employee.employee_number,
            'employee_name': f"{employee.first_name} {employee.last_name}",
            'position': employee.position,
            'department': employee.department,
            'period_start': period_start.isoformat(),
            'period_end': period_end.isoformat(),
            'basic_salary': round(basic_salary, 2),
            'allowances': round(allowances, 2),
            'gross_salary': round(gross_salary, 2),
            'deductions': {
                'ssnit_employee': round(ssnit_employee, 2),
                'ssnit_employer': round(ssnit_employer, 2),
                'paye_tax': round(tax, 2),
                'total': round(total_deductions, 2)
            },
            'net_salary': round(net_salary, 2),
            'currency': 'GHS'
        }
    except Exception as e:
        logger.error(f"Error calculating payroll for employee {employee.id}: {str(e)}")
        raise


@payroll_bp.route('/calculate', methods=['POST', 'OPTIONS'])
@token_required
def calculate_payroll():
    """Calculate payroll for employees"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin', 'accountant']:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        church_id = ensure_user_church(g.current_user)
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        employee_id = data.get('employee_id')
        period_start = data.get('period_start')
        period_end = data.get('period_end')
        
        if not period_start or not period_end:
            return jsonify({'error': 'period_start and period_end are required'}), 400
        
        try:
            start_date = datetime.fromisoformat(period_start.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(period_end.replace('Z', '+00:00')).date()
        except Exception as e:
            return jsonify({'error': f'Invalid date format: {str(e)}'}), 400
        
        if employee_id:
            employee = Employee.query.filter_by(
                id=employee_id, church_id=church_id, is_active=True
            ).first()
            if not employee:
                return jsonify({'error': 'Employee not found'}), 404
            result = calculate_employee_payroll(employee, start_date, end_date)
            return jsonify({'success': True, 'message': 'Payroll calculated successfully', 'data': result}), 200
        else:
            employees = Employee.query.filter_by(church_id=church_id, is_active=True).all()
            results = [calculate_employee_payroll(emp, start_date, end_date) for emp in employees]
            return jsonify({
                'success': True,
                'message': f'Payroll calculated for {len(results)} employees',
                'data': results,
                'total_employees': len(results)
            }), 200
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error calculating payroll: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/runs/initiate', methods=['POST', 'OPTIONS'])
@token_required
def initiate_payroll_run():
    """Admin initiates a new payroll run"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Only admin can initiate payroll'}), 403
        
        church_id = ensure_user_church(g.current_user)
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        period_start = data.get('period_start')
        period_end = data.get('period_end')
        payment_date = data.get('payment_date')
        
        if not period_start or not period_end or not payment_date:
            return jsonify({'error': 'period_start, period_end, and payment_date are required'}), 400
        
        year = datetime.now().year
        month = datetime.now().month
        count = PayrollRun.query.filter(
            PayrollRun.run_number.like(f'PR-{year}-{month:02d}%')
        ).count() + 1
        run_number = f"PR-{year}-{month:02d}-{count:03d}"
        
        payroll_run = PayrollRun(
            church_id=church_id,
            run_number=run_number,
            period_start=datetime.fromisoformat(period_start.replace('Z', '+00:00')).date(),
            period_end=datetime.fromisoformat(period_end.replace('Z', '+00:00')).date(),
            payment_date=datetime.fromisoformat(payment_date.replace('Z', '+00:00')).date(),
            status='INITIATED',
            initiated_by=current_user.id,
            initiated_at=datetime.utcnow()
        )
        
        db.session.add(payroll_run)
        db.session.flush()
        
        employees = Employee.query.filter_by(church_id=church_id, is_active=True).all()
        
        total_gross = 0.0
        total_deductions = 0.0
        total_tax = 0.0
        total_net = 0.0
        
        for emp in employees:
            basic_salary = float(emp.basic_salary) if emp.basic_salary else 0
            allowances = float(emp.allowances) if emp.allowances else 0
            gross = basic_salary + allowances
            ssnit = gross * 0.055
            tax = calculate_paye_tax(gross)
            deductions = ssnit + tax
            net = gross - deductions
            
            line = PayrollLine(
                payroll_run_id=payroll_run.id,
                employee_id=emp.id,
                basic_salary=basic_salary,
                allowances=allowances,
                paye_tax=tax,
                ssnit_employee=ssnit,
                gross_earnings=gross,
                total_deductions=deductions,
                net_pay=net
            )
            db.session.add(line)
            
            total_gross += gross
            total_deductions += deductions
            total_tax += tax
            total_net += net
        
        payroll_run.total_gross = total_gross
        payroll_run.total_deductions = total_deductions
        payroll_run.total_tax = total_tax
        payroll_run.total_net = total_net
        
        db.session.commit()
        
        # Build response with items
        items = []
        for line in payroll_run.lines:
            emp = line.employee
            items.append({
                'id': line.id,
                'employee_id': line.employee_id,
                'employee_name': f"{emp.first_name} {emp.last_name}" if emp else f"Employee {line.employee_id}",
                'department': emp.department if emp else 'N/A',
                'basic_salary': float(line.basic_salary or 0),
                'allowances': float(line.allowances or 0),
                'gross_pay': float(line.gross_earnings or 0),
                'tax_amount': float(line.paye_tax or 0),
                'pension_amount': float(line.ssnit_employee or 0),
                'other_deductions': float(line.other_deductions or 0),
                'net_pay': float(line.net_pay or 0),
                'employee': {'department': emp.department if emp else 'N/A'}
            })
        
        run_dict = payroll_run.to_dict()
        run_dict['items'] = items
        run_dict['employee_count'] = len(items)
        
        return jsonify({
            'message': 'Payroll run initiated successfully',
            'run': run_dict
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error initiating payroll run: {str(e)}")
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
        runs = PayrollRun.query.filter_by(church_id=church_id).order_by(PayrollRun.created_at.desc()).all()
        return jsonify({'runs': [run.to_dict() for run in runs], 'total': len(runs)}), 200
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
        payroll_run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        # Build items from lines
        items = []
        for line in payroll_run.lines:
            emp = line.employee
            items.append({
                'id': line.id,
                'employee_id': line.employee_id,
                'employee_name': f"{emp.first_name} {emp.last_name}" if emp else f"Employee {line.employee_id}",
                'department': emp.department if emp else 'N/A',
                'basic_salary': float(line.basic_salary or 0),
                'allowances': float(line.allowances or 0),
                'gross_pay': float(line.gross_earnings or 0),
                'tax_amount': float(line.paye_tax or 0),
                'pension_amount': float(line.ssnit_employee or 0),
                'other_deductions': float(line.other_deductions or 0),
                'net_pay': float(line.net_pay or 0),
                'employee': {'department': emp.department if emp else 'N/A'}
            })
        
        run_dict = payroll_run.to_dict()
        run_dict['items'] = items
        run_dict['employee_count'] = len(items)
        
        return jsonify(run_dict), 200
    except Exception as e:
        logger.error(f"Error getting payroll run: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/<int:run_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_payroll_run_by_id(run_id):
    """Get a specific payroll run (alternative endpoint)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
        payroll_run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        items = []
        for line in payroll_run.lines:
            emp = line.employee
            items.append({
                'id': line.id,
                'employee_id': line.employee_id,
                'employee_name': f"{emp.first_name} {emp.last_name}" if emp else f"Employee {line.employee_id}",
                'department': emp.department if emp else 'N/A',
                'basic_salary': float(line.basic_salary or 0),
                'allowances': float(line.allowances or 0),
                'gross_pay': float(line.gross_earnings or 0),
                'tax_amount': float(line.paye_tax or 0),
                'pension_amount': float(line.ssnit_employee or 0),
                'other_deductions': float(line.other_deductions or 0),
                'net_pay': float(line.net_pay or 0)
            })
        
        run_dict = payroll_run.to_dict()
        run_dict['items'] = items
        run_dict['employee_count'] = len(items)
        
        return jsonify(run_dict), 200
    except Exception as e:
        logger.error(f"Error getting payroll run: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/<int:run_id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_payroll_run(run_id):
    """Approve a payroll run"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Only admin can approve payroll'}), 403
        
        church_id = ensure_user_church(g.current_user)
        payroll_run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        payroll_run.status = 'APPROVED'
        payroll_run.approved_by = current_user.id
        payroll_run.approved_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll run approved successfully',
            'run': payroll_run.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving payroll run: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/<int:run_id>/reject', methods=['POST', 'OPTIONS'])
@token_required
def reject_payroll_run(run_id):
    """Reject a payroll run"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        current_user = get_current_user()
        if current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Only admin can reject payroll'}), 403
        
        church_id = ensure_user_church(g.current_user)
        payroll_run = PayrollRun.query.filter_by(id=run_id, church_id=church_id).first()
        
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        data = request.get_json() or {}
        reason = data.get('reason', 'No reason provided')
        
        payroll_run.status = 'REJECTED'
        payroll_run.review_comments = reason
        db.session.commit()
        
        return jsonify({
            'message': 'Payroll run rejected',
            'run': payroll_run.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting payroll run: {str(e)}")
        return jsonify({'error': str(e)}), 500


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
        
        total_employees = Employee.query.filter_by(church_id=church_id, is_active=True).count()
        latest_run = PayrollRun.query.filter_by(church_id=church_id).order_by(PayrollRun.created_at.desc()).first()
        recent_runs = PayrollRun.query.filter_by(church_id=church_id).order_by(PayrollRun.created_at.desc()).limit(5).all()
        
        current_month = datetime.now().month
        current_year = datetime.now().year
        
        result = db.session.execute(
            text("""
                SELECT COALESCE(SUM(pl.basic_salary + pl.allowances), 0) as total
                FROM payroll_lines pl
                JOIN payroll_runs pr ON pl.payroll_run_id = pr.id
                WHERE pr.church_id = :church_id
                AND strftime('%Y', pr.period_start) = :year
                AND strftime('%m', pr.period_start) = :month
            """),
            {'church_id': church_id, 'year': str(current_year), 'month': f"{current_month:02d}"}
        ).fetchone()
        
        total_payroll_current_month = float(result[0]) if result and result[0] is not None else 0.0
        
        recent_runs_data = []
        for run in recent_runs:
            run_dict = run.to_dict()
            lines = PayrollLine.query.filter_by(payroll_run_id=run.id).all()
            run_total = sum((line.basic_salary or 0) + (line.allowances or 0) for line in lines)
            run_dict['total_gross'] = float(run_total)
            recent_runs_data.append(run_dict)
        
        return jsonify({
            'total_employees': total_employees,
            'total_payroll_current_month': round(total_payroll_current_month, 2),
            'latest_payroll_run': latest_run.to_dict() if latest_run else None,
            'recent_runs': recent_runs_data
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting payroll dashboard: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/employees', methods=['GET', 'OPTIONS'])
@token_required
def get_employees():
    """Get all employees"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church(g.current_user)
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
        
        return jsonify({
            'employees': [emp.to_dict() for emp in employees],
            'total': len(employees)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting employees: {str(e)}")
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/debug-schema', methods=['GET'])
@token_required
def debug_schema():
    """Debug database schema"""
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        columns = inspector.get_columns('payroll_runs')
        tables = inspector.get_table_names()
        
        return jsonify({
            'database_url': str(db.engine.url),
            'tables': tables,
            'payroll_runs_columns': [c['name'] for c in columns]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500