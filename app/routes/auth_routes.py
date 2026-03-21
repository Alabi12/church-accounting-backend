from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token, verify_jwt_in_request, get_jwt
from datetime import datetime, timedelta
from functools import wraps
import logging
import traceback
import pyotp
import qrcode
import io
import base64
import re

from app.models import User, Church, AuditLog, UserRole, Permission
from app.extensions import db, limiter
from app.utils.validators import validate_email, validate_password_strength

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__)

# Custom decorators for role-based access control
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Handle OPTIONS requests for CORS
        if request.method == 'OPTIONS':
            return '', 200
            
        try:
            # Verify JWT token
            verify_jwt_in_request()
            
            # Get current user ID from token
            current_user_id = get_jwt_identity()
            
            # Get user from database
            current_user = User.query.get(current_user_id)
            
            if not current_user:
                return jsonify({'error': 'User not found'}), 401
                
            # Store user in Flask's g object
            g.current_user = current_user
            
            return f(*args, **kwargs)
            
        except Exception as e:
            print(f"Token verification error: {str(e)}")
            return jsonify({'error': 'Invalid or missing token'}), 401
            
    return decorated

def role_required(*roles):
    """Check if user has any of the required roles"""
    def decorator(f):
        @wraps(f)
        @token_required
        def decorated(*args, **kwargs):
            if not hasattr(g, 'current_user'):
                return jsonify({'error': 'Authentication required'}), 401
            
            if g.current_user.role not in roles and UserRole.SUPER_ADMIN not in roles:
                return jsonify({'error': 'Insufficient role permissions'}), 403
            
            return f(*args, **kwargs)
        return decorated
    return decorator

def permission_required(permission):
    """Check if user has specific permission"""
    def decorator(f):
        @wraps(f)
        @token_required
        def decorated(*args, **kwargs):
            if not hasattr(g, 'current_user'):
                return jsonify({'error': 'Authentication required'}), 401
            
            if not g.current_user.has_permission(permission):
                return jsonify({'error': f'Missing required permission: {permission}'}), 403
            
            return f(*args, **kwargs)
        return decorated
    return decorator

def log_audit(action, resource=None, resource_id=None, data=None):
    """Create audit log entry"""
    try:
        audit_log = AuditLog(
            user_id=g.current_user.id if hasattr(g, 'current_user') else None,
            action=action,
            resource=resource,
            resource_id=resource_id,
            data=data,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
    except Exception as e:
        logger.error(f"Failed to create audit log: {str(e)}")



# ==================== AUTHENTICATION ENDPOINTS ====================

@auth_bp.route('/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return '', 200
    
    try:    
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        email = data.get('email', '').lower().strip()
        password = data.get('password', '')
        
        logger.info(f"📝 Login attempt for email: {email}")
        
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400
        
        user = User.query.filter_by(email=email).first()
        
        # Check if account is locked
        if user and user.locked_until and user.locked_until > datetime.utcnow():
            return jsonify({
                'error': 'Account is temporarily locked',
                'locked_until': user.locked_until.isoformat()
            }), 423
        
        if not user or not user.check_password(password):
            if user:
                user.increment_login_attempts()
                db.session.commit()
                logger.warning(f"❌ Failed login attempt {user.login_attempts}/5 for: {email}")
            return jsonify({'error': 'Invalid credentials'}), 401
        
        if not user.is_active:
            return jsonify({'error': 'Account is deactivated'}), 401
        
        # Reset login attempts on successful login
        user.reset_login_attempts()
        user.last_login = datetime.utcnow()
        user.last_login_ip = request.remote_addr
        db.session.commit()
        
        # Generate tokens
        from flask_jwt_extended import create_access_token, create_refresh_token
        
        access_token = create_access_token(
            identity=str(user.id),
            additional_claims={
                'role': user.role,
                'email': user.email,
                'church_id': user.church_id,
                'permissions': user.get_permissions()
            }
        )
        
        refresh_token = create_refresh_token(identity=str(user.id))
        
        return jsonify({
            'message': 'Login successful',
            'user': user.to_dict(),
            'tokens': {
                'access_token': access_token,
                'refresh_token': refresh_token
            }
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Login error: {str(e)}")
        return jsonify({'error': 'Login failed'}), 500
    
@auth_bp.route('/register', methods=['POST', 'OPTIONS'])
# @limiter.limit("3 per hour")
def register():
    """User registration endpoint"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        logger.info(f"📝 Registration attempt for email: {data.get('email')}")
        
        required_fields = ['email', 'username', 'password', 'first_name', 'last_name']
        missing_fields = [field for field in required_fields if not data.get(field)]
        
        if missing_fields:
            return jsonify({'error': f'Missing required fields: {missing_fields}'}), 400
        
        email = data['email'].lower().strip()
        username = data['username'].strip()
        password = data['password']
        
        if not validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400
        
        if not re.match("^[a-zA-Z0-9_]{3,20}$", username):
            return jsonify({'error': 'Username must be 3-20 characters and contain only letters, numbers, and underscores'}), 400
        
        password_valid, password_error = validate_password_strength(password)
        if not password_valid:
            return jsonify({'error': password_error}), 400
        
        if User.query.filter_by(email=email).first():
            return jsonify({'error': 'Email already registered'}), 400
        
        if User.query.filter_by(username=username).first():
            return jsonify({'error': 'Username already taken'}), 400
        
        user_count = User.query.count()
        role = UserRole.SUPER_ADMIN if user_count == 0 else UserRole.USER
        
        user = User(
            email=email,
            username=username,
            first_name=data['first_name'].strip(),
            last_name=data['last_name'].strip(),
            role=role,
            is_verified=True
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        logger.info(f"✅ Registration successful for: {user.email} with role: {role.value}")
        log_audit('user_registered', 'user', user.id, {'email': user.email, 'role': role.value})
        
        return jsonify({
            'message': 'Registration successful',
            'user': user.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"❌ Registration error: {str(e)}")
        return jsonify({'error': 'Registration failed'}), 500

@auth_bp.route('/refresh', methods=['POST', 'OPTIONS'])
def refresh_token():
    """Refresh access token"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        refresh_token = data.get('refresh_token')
        
        if not refresh_token:
            return jsonify({'error': 'Refresh token required'}), 401
        
        from flask_jwt_extended import decode_token
        try:
            decoded = decode_token(refresh_token)
            user_id_str = decoded['sub']
            
            try:
                user_id_int = int(user_id_str)
            except ValueError:
                return jsonify({'error': 'Invalid user ID'}), 401
            
            user = User.query.get(user_id_int)
            
            if not user or not user.is_active:
                return jsonify({'error': 'Invalid user'}), 401
            
            new_access_token = create_access_token(
                identity=str(user.id),
                additional_claims={
                    'role': user.role.value,
                    'email': user.email,
                    'church_id': user.church_id,
                    'permissions': user.get_permissions()
                }
            )
            
            return jsonify({
                'access_token': new_access_token,
                'token_type': 'bearer',
                'expires_in': 3600
            }), 200
            
        except Exception as e:
            logger.error(f"❌ Refresh token validation failed: {str(e)}")
            return jsonify({'error': 'Invalid refresh token'}), 401
            
    except Exception as e:
        logger.error(f"❌ Refresh error: {str(e)}")
        return jsonify({'error': 'Token refresh failed'}), 500

@auth_bp.route('/logout', methods=['POST', 'OPTIONS'])
@token_required
def logout():
    """Logout user"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        log_audit('user_logout', 'user', g.current_user.id)
        return jsonify({'message': 'Logged out successfully'}), 200
    except Exception as e:
        logger.error(f"❌ Logout error: {str(e)}")
        return jsonify({'error': 'Logout failed'}), 500

# ==================== PROFILE ENDPOINTS ====================

@auth_bp.route('/profile', methods=['GET', 'OPTIONS'])
@token_required
def get_profile():
    """Get current user profile"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        return jsonify(g.current_user.to_dict()), 200
    except Exception as e:
        logger.error(f"❌ Profile error: {str(e)}")
        return jsonify({'error': 'Failed to get profile'}), 500

@auth_bp.route('/profile', methods=['PUT', 'OPTIONS'])
@token_required
def update_profile():
    """Update user profile"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        user = g.current_user
        
        allowed_fields = ['first_name', 'last_name']
        updates = {}
        
        for field in allowed_fields:
            if field in data and data[field]:
                setattr(user, field, data[field].strip())
                updates[field] = data[field]
        
        db.session.commit()
        log_audit('profile_updated', 'user', user.id, updates)
        
        return jsonify({
            'message': 'Profile updated successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Profile update error: {str(e)}")
        return jsonify({'error': 'Failed to update profile'}), 500

@auth_bp.route('/change-password', methods=['POST', 'OPTIONS'])
@token_required
def change_password():
    """Change user password"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        user = g.current_user
        
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        
        if not current_password or not new_password:
            return jsonify({'error': 'Current and new password required'}), 400
        
        if not user.check_password(current_password):
            return jsonify({'error': 'Current password is incorrect'}), 401
        
        password_valid, password_error = validate_password_strength(new_password)
        if not password_valid:
            return jsonify({'error': password_error}), 400
        
        if user.check_password(new_password):
            return jsonify({'error': 'New password must be different from current password'}), 400
        
        user.set_password(new_password)
        db.session.commit()
        log_audit('password_changed', 'user', user.id)
        
        return jsonify({'message': 'Password changed successfully'}), 200
        
    except Exception as e:
        logger.error(f"❌ Change password error: {str(e)}")
        return jsonify({'error': 'Failed to change password'}), 500

# ==================== 2FA ENDPOINTS ====================

@auth_bp.route('/setup-2fa', methods=['POST', 'OPTIONS'])
@token_required
def setup_2fa():
    """Setup 2FA for user"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        user = g.current_user
        
        if user.two_factor_enabled:
            return jsonify({'error': '2FA already enabled'}), 400
        
        secret = pyotp.random_base32()
        user.two_factor_secret = secret
        db.session.commit()
        
        totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=user.email,
            issuer_name="Church Accounting System"
        )
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        log_audit('2fa_setup_initiated', 'user', user.id)
        
        return jsonify({
            'secret': secret,
            'qr_code': f"data:image/png;base64,{img_str}"
        }), 200
        
    except Exception as e:
        logger.error(f"❌ 2FA setup error: {str(e)}")
        return jsonify({'error': 'Failed to setup 2FA'}), 500

@auth_bp.route('/enable-2fa', methods=['POST', 'OPTIONS'])
@token_required
def enable_2fa():
    """Enable 2FA after verification"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        user = g.current_user
        code = data.get('code')
        
        if not code:
            return jsonify({'error': 'Verification code required'}), 400
        
        if not user.two_factor_secret:
            return jsonify({'error': '2FA not setup'}), 400
        
        totp = pyotp.TOTP(user.two_factor_secret)
        
        if not totp.verify(code):
            return jsonify({'error': 'Invalid verification code'}), 401
        
        user.two_factor_enabled = True
        db.session.commit()
        log_audit('2fa_enabled', 'user', user.id)
        
        return jsonify({'message': '2FA enabled successfully'}), 200
        
    except Exception as e:
        logger.error(f"❌ Enable 2FA error: {str(e)}")
        return jsonify({'error': 'Failed to enable 2FA'}), 500

@auth_bp.route('/disable-2fa', methods=['POST', 'OPTIONS'])
@token_required
def disable_2fa():
    """Disable 2FA"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        user = g.current_user
        code = data.get('code')
        password = data.get('password')
        
        if not code or not password:
            return jsonify({'error': 'Verification code and password required'}), 400
        
        if not user.check_password(password):
            return jsonify({'error': 'Invalid password'}), 401
        
        if not user.two_factor_enabled:
            return jsonify({'error': '2FA not enabled'}), 400
        
        totp = pyotp.TOTP(user.two_factor_secret)
        
        if not totp.verify(code):
            return jsonify({'error': 'Invalid verification code'}), 401
        
        user.two_factor_enabled = False
        user.two_factor_secret = None
        db.session.commit()
        log_audit('2fa_disabled', 'user', user.id)
        
        return jsonify({'message': '2FA disabled successfully'}), 200
        
    except Exception as e:
        logger.error(f"❌ Disable 2FA error: {str(e)}")
        return jsonify({'error': 'Failed to disable 2FA'}), 500

# ==================== USER MANAGEMENT ENDPOINTS ====================

@auth_bp.route('/users', methods=['GET', 'OPTIONS'])
def list_users():
    """Get all users"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Verify JWT token and get current user
        verify_jwt_in_request()
        user_id = get_jwt_identity()
        
        try:
            user_id_int = int(user_id)
        except ValueError:
            return jsonify({'error': 'Invalid user ID format'}), 401
        
        current_user = User.query.get(user_id_int)
        
        if not current_user:
            return jsonify({'error': 'User not found'}), 401
        
        if not current_user.is_active:
            return jsonify({'error': 'User account is inactive'}), 401
        
        # Check if user has permission to view users
        if current_user.role not in [UserRole.SUPER_ADMIN, UserRole.TREASURER]:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        # Get query parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        role = request.args.get('role')
        church_id = request.args.get('church_id')
        
        # Build query
        query = User.query
        
        if role:
            query = query.filter_by(role=role)
        
        if church_id:
            query = query.filter_by(church_id=church_id)
        
        # Filter by church if not super admin
        if current_user.role != UserRole.SUPER_ADMIN and current_user.church_id:
            query = query.filter_by(church_id=current_user.church_id)
        
        # Execute query with pagination
        users = query.order_by(User.created_at.desc()).paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )
        
        return jsonify({
            'users': [user.to_dict() for user in users.items],
            'total': users.total,
            'pages': users.pages,
            'current_page': users.page
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Get users error: {str(e)}")
        return jsonify({'error': 'Failed to get users'}), 500

@auth_bp.route('/users/<int:user_id>', methods=['GET', 'OPTIONS'])
def get_single_user(user_id):  # Unique name
    """Get user by ID"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        verify_jwt_in_request()
        current_user_id = get_jwt_identity()
        current_user = User.query.get(int(current_user_id))
        
        if not current_user:
            return jsonify({'error': 'Authentication required'}), 401
        
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if (current_user.role != UserRole.SUPER_ADMIN and 
            user.church_id != current_user.church_id):
            return jsonify({'error': 'Access denied'}), 403
        
        return jsonify(user.to_dict()), 200
        
    except Exception as e:
        logger.error(f"❌ Get user error: {str(e)}")
        return jsonify({'error': 'Failed to get user'}), 500

@auth_bp.route('/users/<int:user_id>', methods=['PUT', 'OPTIONS'])
def update_single_user(user_id):  # Unique name
    """Update user details"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        verify_jwt_in_request()
        current_user_id = get_jwt_identity()
        current_user = User.query.get(int(current_user_id))
        
        if not current_user:
            return jsonify({'error': 'Authentication required'}), 401
        
        if current_user.role != UserRole.SUPER_ADMIN:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        data = request.get_json()
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        allowed_fields = ['first_name', 'last_name', 'email', 'username']
        updates = {}
        
        for field in allowed_fields:
            if field in data and data[field]:
                setattr(user, field, data[field].strip())
                updates[field] = data[field]
        
        db.session.commit()
        
        return jsonify({
            'message': 'User updated successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Update user error: {str(e)}")
        return jsonify({'error': 'Failed to update user'}), 500

@auth_bp.route('/users/<int:user_id>/role', methods=['PUT', 'OPTIONS'])
def change_user_role(user_id):  # Changed from update_user_role to change_user_role
    """Update user role"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        verify_jwt_in_request()
        current_user_id = get_jwt_identity()
        current_user = User.query.get(int(current_user_id))
        
        if not current_user or current_user.role != UserRole.SUPER_ADMIN:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        data = request.get_json()
        new_role = data.get('role')
        
        if not new_role:
            return jsonify({'error': 'Role required'}), 400
        
        try:
            role_enum = UserRole[new_role]
        except KeyError:
            return jsonify({'error': f'Invalid role. Must be one of: {[r.name for r in UserRole]}'}), 400
        
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        old_role = user.role
        user.role = role_enum
        db.session.commit()
        
        return jsonify({
            'message': 'User role updated successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Update user role error: {str(e)}")
        return jsonify({'error': 'Failed to update user role'}), 500

@auth_bp.route('/users/<int:user_id>', methods=['DELETE', 'OPTIONS'])
def delete_single_user(user_id):  # Unique name
    """Delete user"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        verify_jwt_in_request()
        current_user_id = get_jwt_identity()
        current_user = User.query.get(int(current_user_id))
        
        if not current_user or current_user.role != UserRole.SUPER_ADMIN:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if user.id == current_user.id:
            return jsonify({'error': 'Cannot delete your own account'}), 400
        
        db.session.delete(user)
        db.session.commit()
        
        return jsonify({'message': 'User deleted successfully'}), 200
        
    except Exception as e:
        logger.error(f"❌ Delete user error: {str(e)}")
        return jsonify({'error': 'Failed to delete user'}), 500

@auth_bp.route('/users/<int:user_id>/activate', methods=['POST', 'OPTIONS'])
def activate_user(user_id):  # Changed from activate_user_account
    """Activate user account"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        verify_jwt_in_request()
        current_user_id = get_jwt_identity()
        current_user = User.query.get(int(current_user_id))
        
        if not current_user or current_user.role not in [UserRole.SUPER_ADMIN, UserRole.TREASURER]:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if (current_user.role != UserRole.SUPER_ADMIN and 
            user.church_id != current_user.church_id):
            return jsonify({'error': 'Access denied'}), 403
        
        user.is_active = True
        user.locked_until = None
        user.login_attempts = 0
        db.session.commit()
        
        return jsonify({'message': 'User activated successfully'}), 200
        
    except Exception as e:
        logger.error(f"❌ Activate user error: {str(e)}")
        return jsonify({'error': 'Failed to activate user'}), 500

@auth_bp.route('/users/<int:user_id>/deactivate', methods=['POST', 'OPTIONS'])
def deactivate_user(user_id):  # Changed from deactivate_user_account
    """Deactivate user account"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        verify_jwt_in_request()
        current_user_id = get_jwt_identity()
        current_user = User.query.get(int(current_user_id))
        
        if not current_user or current_user.role not in [UserRole.SUPER_ADMIN, UserRole.TREASURER]:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if (current_user.role != UserRole.SUPER_ADMIN and 
            user.church_id != current_user.church_id):
            return jsonify({'error': 'Access denied'}), 403
        
        if user.id == current_user.id:
            return jsonify({'error': 'Cannot deactivate your own account'}), 400
        
        user.is_active = False
        db.session.commit()
        
        return jsonify({'message': 'User deactivated successfully'}), 200
        
    except Exception as e:
        logger.error(f"❌ Deactivate user error: {str(e)}")
        return jsonify({'error': 'Failed to deactivate user'}), 500
    
# ==================== AUDIT LOGS ENDPOINTS ====================

@auth_bp.route('/audit-logs', methods=['GET', 'OPTIONS'])
@permission_required(Permission.VIEW_AUDIT_LOGS)
def get_audit_logs():
    """Get audit logs"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        user_id = request.args.get('user_id')
        action = request.args.get('action')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        query = AuditLog.query
        
        if user_id:
            query = query.filter_by(user_id=user_id)
        
        if action:
            query = query.filter(AuditLog.action.like(f'%{action}%'))
        
        if start_date:
            query = query.filter(AuditLog.timestamp >= datetime.fromisoformat(start_date))
        
        if end_date:
            query = query.filter(AuditLog.timestamp <= datetime.fromisoformat(end_date))
        
        logs = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=per_page)
        
        return jsonify({
            'logs': [log.to_dict() for log in logs.items],
            'total': logs.total,
            'pages': logs.pages,
            'current_page': logs.page
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Get audit logs error: {str(e)}")
        return jsonify({'error': 'Failed to get audit logs'}), 500

# ==================== PERMISSIONS ENDPOINTS ====================

@auth_bp.route('/permissions', methods=['GET', 'OPTIONS'])
@token_required
def get_permissions():
    """Get all available permissions"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        permissions = [perm.value for perm in Permission]
        
        return jsonify({
            'all_permissions': permissions,
            'user_permissions': g.current_user.get_permissions(),
            'role': g.current_user.role.value
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Get permissions error: {str(e)}")
        return jsonify({'error': 'Failed to get permissions'}), 500