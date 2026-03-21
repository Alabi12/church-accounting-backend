# app/routes/church_routes.py
from flask import Blueprint, request, jsonify, g
from app.models import Church, User, Account
from app.extensions import db
from datetime import datetime
from app.routes.auth_routes import token_required
import traceback
import logging

logger = logging.getLogger(__name__)

# Create the blueprint
church_bp = Blueprint('church', __name__)

# ==================== CHURCH MANAGEMENT ====================

@church_bp.route('/churches', methods=['GET', 'OPTIONS'])
@token_required
def get_churches():
    """Get all churches (admin only)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Only super_admin and admin can see all churches
        if g.current_user.role not in ['super_admin', 'admin']:
            # Regular users only see their church
            church = Church.query.get(g.current_user.church_id)
            return jsonify({
                'churches': [{
                    'id': church.id,
                    'name': church.name,
                    'legal_name': church.legal_name,
                    'address': church.address,
                    'city': church.city,
                    'state': church.state,
                    'country': church.country,
                    'phone': church.phone,
                    'email': church.email,
                    'website': church.website,
                    'tax_id': church.tax_id,
                    'founded_date': church.founded_date.isoformat() if church.founded_date else None,
                    'pastor_name': church.pastor_name,
                    'denomination': church.denomination,
                    'is_active': church.is_active if hasattr(church, 'is_active') else True,
                    'created_at': church.created_at.isoformat() if church.created_at else None
                }]
            }), 200
        
        # Admin view - get all churches
        churches = Church.query.all()
        church_list = []
        for church in churches:
            church_list.append({
                'id': church.id,
                'name': church.name,
                'legal_name': church.legal_name,
                'address': church.address,
                'city': church.city,
                'state': church.state,
                'country': church.country,
                'phone': church.phone,
                'email': church.email,
                'website': church.website,
                'tax_id': church.tax_id,
                'founded_date': church.founded_date.isoformat() if church.founded_date else None,
                'pastor_name': church.pastor_name,
                'denomination': church.denomination,
                'is_active': church.is_active if hasattr(church, 'is_active') else True,
                'created_at': church.created_at.isoformat() if church.created_at else None
            })
        
        return jsonify({'churches': church_list}), 200
        
    except Exception as e:
        logger.error(f"Error fetching churches: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@church_bp.route('/churches/my', methods=['GET', 'OPTIONS'])
@token_required
def get_my_church():
    """Get current user's church"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church = Church.query.get(g.current_user.church_id)
        if not church:
            return jsonify({'error': 'Church not found'}), 404
        
        return jsonify({
            'id': church.id,
            'name': church.name,
            'legal_name': church.legal_name,
            'address': church.address,
            'city': church.city,
            'state': church.state,
            'country': church.country,
            'phone': church.phone,
            'email': church.email,
            'website': church.website,
            'tax_id': church.tax_id,
            'founded_date': church.founded_date.isoformat() if church.founded_date else None,
            'pastor_name': church.pastor_name,
            'denomination': church.denomination,
            'created_at': church.created_at.isoformat() if church.created_at else None
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching my church: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@church_bp.route('/churches', methods=['POST', 'OPTIONS'])
@token_required
def create_church():
    """Create a new church (admin only)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # Check permission
    if g.current_user.role not in ['super_admin', 'admin']:
        return jsonify({'error': 'Permission denied'}), 403
    
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        church = Church(
            name=data['name'],
            legal_name=data.get('legal_name'),
            address=data.get('address'),
            city=data.get('city'),
            state=data.get('state'),
            country=data.get('country', 'Ghana'),
            phone=data.get('phone'),
            email=data.get('email'),
            website=data.get('website'),
            tax_id=data.get('tax_id'),
            founded_date=datetime.fromisoformat(data['founded_date']) if data.get('founded_date') else None,
            pastor_name=data.get('pastor_name'),
            denomination=data.get('denomination'),
            created_at=datetime.utcnow()
        )
        
        # Add is_active if the field exists
        if hasattr(church, 'is_active'):
            church.is_active = data.get('is_active', True)
        
        db.session.add(church)
        db.session.commit()
        
        return jsonify({
            'message': 'Church created successfully',
            'church': {
                'id': church.id,
                'name': church.name
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating church: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@church_bp.route('/churches/<int:church_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_church(church_id):
    """Update a church (admin only)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # Check permission
    if g.current_user.role not in ['super_admin', 'admin']:
        return jsonify({'error': 'Permission denied'}), 403
    
    try:
        church = Church.query.get(church_id)
        if not church:
            return jsonify({'error': 'Church not found'}), 404
        
        data = request.get_json()
        
        # Update fields
        if 'name' in data:
            church.name = data['name']
        if 'legal_name' in data:
            church.legal_name = data['legal_name']
        if 'address' in data:
            church.address = data['address']
        if 'city' in data:
            church.city = data['city']
        if 'state' in data:
            church.state = data['state']
        if 'country' in data:
            church.country = data['country']
        if 'phone' in data:
            church.phone = data['phone']
        if 'email' in data:
            church.email = data['email']
        if 'website' in data:
            church.website = data['website']
        if 'tax_id' in data:
            church.tax_id = data['tax_id']
        if 'founded_date' in data:
            church.founded_date = datetime.fromisoformat(data['founded_date']) if data['founded_date'] else None
        if 'pastor_name' in data:
            church.pastor_name = data['pastor_name']
        if 'denomination' in data:
            church.denomination = data['denomination']
        if 'is_active' in data and hasattr(church, 'is_active'):
            church.is_active = data['is_active']
        
        church.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'message': 'Church updated successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating church: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@church_bp.route('/churches/<int:church_id>/users', methods=['GET', 'OPTIONS'])
@token_required
def get_church_users(church_id):
    """Get all users in a church"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Check access
        if church_id != g.current_user.church_id and g.current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Access denied'}), 403
        
        users = User.query.filter_by(church_id=church_id).all()
        user_list = []
        
        for user in users:
            user_list.append({
                'id': user.id,
                'email': user.email,
                'full_name': user.full_name,
                'role': user.role,
                'is_active': user.is_active,
                'last_login': user.last_login.isoformat() if user.last_login else None
            })
        
        return jsonify({'users': user_list}), 200
        
    except Exception as e:
        logger.error(f"Error fetching church users: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@church_bp.route('/churches/<int:church_id>/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_church_stats(church_id):
    """Get church statistics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Check access
        if church_id != g.current_user.church_id and g.current_user.role not in ['super_admin', 'admin']:
            return jsonify({'error': 'Access denied'}), 403
        
        # Get counts
        user_count = User.query.filter_by(church_id=church_id).count()
        account_count = Account.query.filter_by(church_id=church_id).count()
        
        # Get financial stats
        total_balance = db.session.query(db.func.sum(Account.current_balance)).filter(
            Account.church_id == church_id,
            Account.is_active == True
        ).scalar() or 0
        
        return jsonify({
            'church_id': church_id,
            'user_count': user_count,
            'account_count': account_count,
            'total_balance': float(total_balance)
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching church stats: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
@church_bp.route('/churches/<int:church_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_church(church_id):
    """Delete a church (admin only)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # Check permission
    if g.current_user.role not in ['super_admin']:
        return jsonify({'error': 'Permission denied'}), 403
    
    try:
        church = Church.query.get(church_id)
        if not church:
            return jsonify({'error': 'Church not found'}), 404
        
        # Check if church has users
        user_count = User.query.filter_by(church_id=church_id).count()
        if user_count > 0:
            return jsonify({'error': 'Cannot delete church with existing users'}), 400
        
        # Check if church has accounts
        account_count = Account.query.filter_by(church_id=church_id).count()
        if account_count > 0:
            return jsonify({'error': 'Cannot delete church with existing accounts'}), 400
        
        db.session.delete(church)
        db.session.commit()
        
        return jsonify({'message': 'Church deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting church: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500