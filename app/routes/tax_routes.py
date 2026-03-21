# app/routes/tax_routes.py
from flask import Blueprint, request, jsonify, g, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import TaxTable, Church, User, AuditLog
from app.extensions import db
from datetime import datetime
import logging
import traceback

logger = logging.getLogger(__name__)
tax_bp = Blueprint('tax', __name__)


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
    except Exception as e:
        logger.warning(f"Error getting user from JWT: {e}")
    
    return None


def ensure_user_church(user=None):
    """
    Ensure we have a valid church_id.
    Returns church_id or raises appropriate error.
    """
    try:
        # Case 1: User object provided
        if user and hasattr(user, 'church_id') and user.church_id:
            return user.church_id
        
        # Case 2: Try to get current user from context
        current_user = get_current_user()
        if current_user and current_user.church_id:
            return current_user.church_id
        
        # Case 3: Try to get default church
        default_church = Church.query.first()
        if default_church:
            # If we have a user but no church_id, assign default
            if current_user and not current_user.church_id:
                current_user.church_id = default_church.id
                db.session.add(current_user)
                db.session.commit()
                logger.info(f"Assigned default church {default_church.id} to user {current_user.id}")
            return default_church.id
        
        # Case 4: For development, return a fallback
        if current_app.debug:
            logger.warning("Using fallback church_id=1 for development")
            return 1
            
        raise ValueError("No church found in database")
        
    except Exception as e:
        logger.error(f"Error in ensure_user_church: {str(e)}")
        if current_app.debug:
            return 1  # Fallback for development
        raise


def create_default_tax_tables(church_id, year):
    """Create default Ghana tax tables for a given year"""
    # 2025 Ghana tax brackets (monthly)
    brackets = [
        {'from': 0, 'to': 490, 'rate': 0},
        {'from': 490, 'to': 600, 'rate': 5},
        {'from': 600, 'to': 730, 'rate': 10},
        {'from': 730, 'to': 3896.67, 'rate': 17.5},
        {'from': 3896.67, 'to': 19896.67, 'rate': 25},
        {'from': 19896.67, 'to': 50416.67, 'rate': 30},
        {'from': 50416.67, 'to': None, 'rate': 35}
    ]
    
    tax_tables = []
    for bracket in brackets:
        tax_table = TaxTable(
            church_id=church_id,
            tax_year=year,
            bracket_from=bracket['from'],
            bracket_to=bracket['to'],
            rate=bracket['rate'],
            ss_employee_rate=5.5,
            ss_employer_rate=13.0,
            hi_employee_rate=2.5,
            hi_employer_rate=2.5
        )
        db.session.add(tax_table)
        tax_tables.append(tax_table)
    
    db.session.commit()
    return tax_tables


# ==================== TAX ROUTES ====================

@tax_bp.route('/tables', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_tax_tables():
    """Get tax tables for a specific year"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church()
        year = request.args.get('year', datetime.now().year, type=int)
        
        # Get tax tables for the specified year
        tax_tables = TaxTable.query.filter_by(
            church_id=church_id,
            tax_year=year
        ).order_by(TaxTable.bracket_from).all()
        
        # If no tables for this year, create default ones
        if not tax_tables:
            logger.info(f"No tax tables found for year {year}, creating defaults")
            tax_tables = create_default_tax_tables(church_id, year)
        
        return jsonify({
            'tax_tables': [t.to_dict() for t in tax_tables],
            'year': year
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting tax tables: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@tax_bp.route('/tables', methods=['POST', 'OPTIONS'])
@jwt_required()
def create_tax_table():
    """Create a new tax table entry"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church()
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
            
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['tax_year', 'bracket_from', 'rate']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Check if bracket already exists
        existing = TaxTable.query.filter_by(
            church_id=church_id,
            tax_year=data['tax_year'],
            bracket_from=data['bracket_from']
        ).first()
        
        if existing:
            return jsonify({'error': 'Tax bracket already exists for this year'}), 400
        
        tax_table = TaxTable(
            church_id=church_id,
            tax_year=data['tax_year'],
            bracket_from=data['bracket_from'],
            bracket_to=data.get('bracket_to'),
            rate=data['rate'],
            ss_employee_rate=data.get('ss_employee_rate', 5.5),
            ss_employer_rate=data.get('ss_employer_rate', 13.0),
            hi_employee_rate=data.get('hi_employee_rate', 2.5),
            hi_employer_rate=data.get('hi_employer_rate', 2.5)
        )
        
        db.session.add(tax_table)
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=current_user.id,
            action='CREATE_TAX_TABLE',
            resource='tax_table',
            resource_id=tax_table.id,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'Tax table created successfully',
            'tax_table': tax_table.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating tax table: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@tax_bp.route('/tables/<int:table_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@jwt_required()
def manage_tax_table(table_id):
    """Get, update, or delete a specific tax table"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church()
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
            
        tax_table = TaxTable.query.filter_by(id=table_id, church_id=church_id).first()
        
        if not tax_table:
            return jsonify({'error': 'Tax table not found'}), 404
        
        if request.method == 'GET':
            return jsonify(tax_table.to_dict()), 200
            
        elif request.method == 'PUT':
            data = request.get_json()
            
            if 'bracket_from' in data:
                tax_table.bracket_from = data['bracket_from']
            if 'bracket_to' in data:
                tax_table.bracket_to = data['bracket_to']
            if 'rate' in data:
                tax_table.rate = data['rate']
            if 'ss_employee_rate' in data:
                tax_table.ss_employee_rate = data['ss_employee_rate']
            if 'ss_employer_rate' in data:
                tax_table.ss_employer_rate = data['ss_employer_rate']
            if 'hi_employee_rate' in data:
                tax_table.hi_employee_rate = data['hi_employee_rate']
            if 'hi_employer_rate' in data:
                tax_table.hi_employer_rate = data['hi_employer_rate']
            
            db.session.commit()
            
            return jsonify({
                'message': 'Tax table updated successfully',
                'tax_table': tax_table.to_dict()
            }), 200
            
        elif request.method == 'DELETE':
            db.session.delete(tax_table)
            db.session.commit()
            
            return jsonify({'message': 'Tax table deleted successfully'}), 200
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error managing tax table: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@tax_bp.route('/calculate', methods=['POST', 'OPTIONS'])
@jwt_required()
def calculate_tax():
    """Calculate tax for a given income"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        
        if 'income' not in data:
            return jsonify({'error': 'Income is required'}), 400
        
        income = float(data['income'])
        frequency = data.get('frequency', 'monthly')  # monthly, annual
        
        # Convert to monthly if annual
        if frequency == 'annual':
            monthly_income = income / 12
        else:
            monthly_income = income
        
        # Get tax tables for current year
        church_id = ensure_user_church()
        year = datetime.now().year
        
        tax_tables = TaxTable.query.filter_by(
            church_id=church_id,
            tax_year=year
        ).order_by(TaxTable.bracket_from).all()
        
        if not tax_tables:
            tax_tables = create_default_tax_tables(church_id, year)
        
        # Calculate PAYE
        remaining_income = monthly_income
        total_tax = 0
        brackets = []
        
        for i, table in enumerate(tax_tables):
            if remaining_income <= 0:
                break
            
            bracket_from = float(table.bracket_from)
            bracket_to = float(table.bracket_to) if table.bracket_to else float('inf')
            rate = float(table.rate)
            
            if i == len(tax_tables) - 1:  # Last bracket
                taxable = remaining_income
            else:
                taxable = min(remaining_income, bracket_to - bracket_from)
            
            tax = taxable * (rate / 100)
            
            brackets.append({
                'range': f"{bracket_from:,.2f} - {bracket_to if table.bracket_to else 'Above':,.2f}",
                'taxable': round(taxable, 2),
                'rate': rate,
                'tax': round(tax, 2)
            })
            
            total_tax += tax
            remaining_income -= taxable
        
        # Calculate SSNIT
        ss_employee_rate = float(tax_tables[0].ss_employee_rate) / 100 if tax_tables else 0.055
        ss_employer_rate = float(tax_tables[0].ss_employer_rate) / 100 if tax_tables else 0.13
        
        ss_employee = monthly_income * ss_employee_rate
        ss_employer = monthly_income * ss_employer_rate
        
        # Calculate Net
        net_monthly = monthly_income - total_tax - ss_employee
        net_annual = net_monthly * 12 if frequency == 'monthly' else (income - total_tax * 12 - ss_employee * 12)
        
        return jsonify({
            'input': {
                'income': income,
                'frequency': frequency
            },
            'monthly': {
                'gross': round(monthly_income, 2),
                'paye': round(total_tax, 2),
                'ssnit_employee': round(ss_employee, 2),
                'ssnit_employer': round(ss_employer, 2),
                'total_deductions': round(total_tax + ss_employee, 2),
                'net': round(net_monthly, 2)
            },
            'annual': {
                'gross': round(income if frequency == 'annual' else monthly_income * 12, 2),
                'paye': round(total_tax * 12, 2),
                'ssnit_employee': round(ss_employee * 12, 2),
                'ssnit_employer': round(ss_employer * 12, 2),
                'total_deductions': round((total_tax + ss_employee) * 12, 2),
                'net': round(net_annual, 2)
            },
            'brackets': brackets,
            'effective_tax_rate': round((total_tax / monthly_income) * 100, 2) if monthly_income > 0 else 0
        }), 200
        
    except Exception as e:
        logger.error(f"Error calculating tax: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500