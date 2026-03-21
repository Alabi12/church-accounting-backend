from functools import wraps
from flask import request, jsonify, g
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity, get_jwt
from app.models.user import User
from app.extensions import db
import logging

logger = logging.getLogger(__name__)

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            verify_jwt_in_request()
            user_id = get_jwt_identity()
            current_user = User.query.get(user_id)
            
            if not current_user or not current_user.is_active:
                return jsonify({'error': 'Invalid or inactive user'}), 401
            
            g.current_user = current_user
            g.user_claims = get_jwt()
            
        except Exception as e:
            logger.error(f"Token validation error: {str(e)}")
            return jsonify({'error': 'Invalid token'}), 401
        
        return f(*args, **kwargs)
    
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not hasattr(g, 'current_user'):
                return jsonify({'error': 'Authentication required'}), 401
            
            if g.current_user.role not in roles and 'SUPER_ADMIN' not in roles:
                return jsonify({'error': 'Insufficient permissions'}), 403
            
            return f(*args, **kwargs)
        return decorated
    return decorator

def permission_required(permission):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not hasattr(g, 'current_user'):
                return jsonify({'error': 'Authentication required'}), 401
            
            if not g.current_user.has_permission(permission):
                return jsonify({'error': 'Insufficient permissions'}), 403
            
            return f(*args, **kwargs)
        return decorated
    return decorator

def church_access_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(g, 'current_user'):
            return jsonify({'error': 'Authentication required'}), 401
        
        church_id = kwargs.get('church_id') or request.json.get('church_id') or request.args.get('church_id')
        
        if church_id and int(church_id) != g.current_user.church_id and g.current_user.role != 'SUPER_ADMIN':
            return jsonify({'error': 'Access denied to this church\'s data'}), 403
        
        return f(*args, **kwargs)
    return decorated

def rate_limit_for_role(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if hasattr(g, 'current_user'):
            # Higher rate limits for certain roles
            if g.current_user.role in ['SUPER_ADMIN', 'TREASURER']:
                # These roles get higher limits
                pass
        return f(*args, **kwargs)
    return decorated