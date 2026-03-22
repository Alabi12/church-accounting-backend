from flask import Blueprint, request, jsonify, g, make_response
from datetime import datetime, timedelta
import logging
from sqlalchemy import func, desc
import csv
import io

from app.models import User, AuditLog, Church, Role, Permission, Setting
from app.extensions import db
from app.routes.auth_routes import token_required, role_required
from app.utils.validators import validate_email, validate_password_strength

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__)

# ==================== USER MANAGEMENT ====================

@admin_bp.route('/users', methods=['GET', 'OPTIONS'])
@token_required
@role_required('super_admin', 'admin')
def get_users():
    """Get all users with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        # Build query
        query = User.query.filter_by(church_id=church_id)
        
        # Apply filters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('perPage', 10, type=int)
        role = request.args.get('role')
        status = request.args.get('status')
        search = request.args.get('search')
        
        if role:
            query = query.filter_by(role=role)
        
        if status == 'active':
            query = query.filter_by(is_active=True)
        elif status == 'inactive':
            query = query.filter_by(is_active=False)
        
        if search:
            query = query.filter(
                db.or_(
                    User.email.ilike(f'%{search}%'),
                    User.username.ilike(f'%{search}%'),
                    User.first_name.ilike(f'%{search}%'),
                    User.last_name.ilike(f'%{search}%')
                )
            )
        
        # Get paginated results
        paginated = query.order_by(User.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Format response
        user_list = []
        for user in paginated.items:
            user_list.append({
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'firstName': user.first_name,
                'lastName': user.last_name,
                'fullName': user.full_name if hasattr(user, 'full_name') else f"{user.first_name or ''} {user.last_name or ''}".strip(),
                'role': user.role,
                'churchId': user.church_id,
                'isActive': user.is_active,
                'isVerified': user.is_verified,
                'lastLogin': user.last_login.isoformat() if user.last_login else None,
                'createdAt': user.created_at.isoformat() if user.created_at else None
            })
        
        return jsonify({
            'users': user_list,
            'total': paginated.total,
            'pages': paginated.pages,
            'currentPage': paginated.page
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting users: {str(e)}")
        return jsonify({'error': 'Failed to get users'}), 500


@admin_bp.route('/users', methods=['POST', 'OPTIONS'])
@token_required
@role_required('super_admin', 'admin')
def create_user():
    """Create a new user"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        church_id = g.current_user.church_id
        
        # Validate required fields
        required_fields = ['email', 'username', 'firstName', 'lastName', 'password', 'role']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        # Validate email
        if not validate_email(data['email']):
            return jsonify({'error': 'Invalid email format'}), 400
        
        # Check if user already exists
        existing = User.query.filter_by(email=data['email']).first()
        if existing:
            return jsonify({'error': 'User with this email already exists'}), 400
        
        # Validate password strength
        password_valid, password_error = validate_password_strength(data['password'])
        if not password_valid:
            return jsonify({'error': password_error}), 400
        
        # Create user
        user = User(
            email=data['email'].lower().strip(),
            username=data['username'].strip(),
            first_name=data['firstName'].strip(),
            last_name=data['lastName'].strip(),
            role=data['role'],
            church_id=church_id,
            is_active=data.get('isActive', True),
            is_verified=data.get('isVerified', False)
        )
        user.set_password(data['password'])
        
        db.session.add(user)
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='CREATE_USER',
            resource='user',
            resource_id=user.id,
            data={'email': user.email, 'role': user.role},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({
            'message': 'User created successfully',
            'id': user.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating user: {str(e)}")
        return jsonify({'error': 'Failed to create user'}), 500


@admin_bp.route('/users/<int:user_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
@role_required('super_admin', 'admin')
def manage_user(user_id):
    """Get, update, or delete a specific user"""
    if request.method == 'OPTIONS':
        return '', 200
    
    church_id = g.current_user.church_id
    user = User.query.filter_by(id=user_id, church_id=church_id).first()
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # GET - Retrieve user
    if request.method == 'GET':
        return jsonify({
            'id': user.id,
            'email': user.email,
            'username': user.username,
            'firstName': user.first_name,
            'lastName': user.last_name,
            'fullName': user.full_name if hasattr(user, 'full_name') else f"{user.first_name or ''} {user.last_name or ''}".strip(),
            'role': user.role,
            'churchId': user.church_id,
            'isActive': user.is_active,
            'isVerified': user.is_verified,
            'lastLogin': user.last_login.isoformat() if user.last_login else None,
            'createdAt': user.created_at.isoformat() if user.created_at else None
        }), 200
    
    # PUT - Update user
    elif request.method == 'PUT':
        try:
            data = request.get_json()
            
            # Update fields
            if 'firstName' in data:
                user.first_name = data['firstName'].strip()
            if 'lastName' in data:
                user.last_name = data['lastName'].strip()
            if 'email' in data:
                if not validate_email(data['email']):
                    return jsonify({'error': 'Invalid email format'}), 400
                user.email = data['email'].lower().strip()
            if 'username' in data:
                user.username = data['username'].strip()
            if 'role' in data:
                user.role = data['role']
            if 'isActive' in data:
                user.is_active = data['isActive']
            if 'isVerified' in data:
                user.is_verified = data['isVerified']
            
            db.session.commit()
            
            # Log audit
            audit_log = AuditLog(
                user_id=g.current_user.id,
                action='UPDATE_USER',
                resource='user',
                resource_id=user.id,
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string
            )
            db.session.add(audit_log)
            db.session.commit()
            
            return jsonify({'message': 'User updated successfully'}), 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating user: {str(e)}")
            return jsonify({'error': 'Failed to update user'}), 500
    
    # DELETE - Delete user
    elif request.method == 'DELETE':
        try:
            # Don't allow deleting yourself
            if user.id == g.current_user.id:
                return jsonify({'error': 'Cannot delete your own account'}), 400
            
            db.session.delete(user)
            db.session.commit()
            
            # Log audit
            audit_log = AuditLog(
                user_id=g.current_user.id,
                action='DELETE_USER',
                resource='user',
                resource_id=user_id,
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string
            )
            db.session.add(audit_log)
            db.session.commit()
            
            return jsonify({'message': 'User deleted successfully'}), 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting user: {str(e)}")
            return jsonify({'error': 'Failed to delete user'}), 500


@admin_bp.route('/users/<int:user_id>/status', methods=['PATCH', 'OPTIONS'])
@token_required
@role_required('super_admin', 'admin')
def toggle_user_status(user_id):
    """Toggle user active status"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        user = User.query.filter_by(id=user_id, church_id=church_id).first()
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json()
        user.is_active = data.get('isActive', not user.is_active)
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='TOGGLE_USER_STATUS',
            resource='user',
            resource_id=user_id,
            data={'is_active': user.is_active},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'User status updated successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error toggling user status: {str(e)}")
        return jsonify({'error': 'Failed to update user status'}), 500

# Add this after the toggle_user_status endpoint, before the export_users endpoint

@admin_bp.route('/users/check-username/<username>', methods=['GET', 'OPTIONS'])
@token_required
@role_required('super_admin', 'admin')
def check_username(username):
    """Check if username is available"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        # Check if username exists in this church
        existing_user = User.query.filter_by(
            username=username.strip(),
            church_id=church_id
        ).first()
        
        # Also check if username exists in default church if user is super_admin
        if not existing_user and g.current_user.role == 'super_admin':
            # Super admins can see users from all churches for username check
            existing_user = User.query.filter_by(username=username.strip()).first()
        
        return jsonify({
            'available': existing_user is None,
            'message': 'Username available' if not existing_user else 'Username already taken'
        }), 200
        
    except Exception as e:
        logger.error(f"Error checking username: {str(e)}")
        return jsonify({
            'available': True,
            'message': 'Username check failed, will validate on submit',
            'error': str(e)
        }), 200
    
@admin_bp.route('/users/export', methods=['GET', 'OPTIONS'])
@token_required
@role_required('super_admin', 'admin')
def export_users():
    """Export users as CSV"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        users = User.query.filter_by(church_id=church_id).order_by(User.created_at).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        writer.writerow(['ID', 'Email', 'Username', 'First Name', 'Last Name', 'Role', 'Active', 'Verified', 'Last Login', 'Created At'])
        
        # Write data
        for user in users:
            writer.writerow([
                user.id,
                user.email,
                user.username,
                user.first_name or '',
                user.last_name or '',
                user.role,
                'Yes' if user.is_active else 'No',
                'Yes' if user.is_verified else 'No',
                user.last_login.strftime('%Y-%m-%d %H:%M:%S') if user.last_login else '',
                user.created_at.strftime('%Y-%m-%d %H:%M:%S') if user.created_at else ''
            ])
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=users_{datetime.utcnow().strftime("%Y%m%d")}.csv'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting users: {str(e)}")
        return jsonify({'error': 'Failed to export users'}), 500


# ==================== AUDIT LOGS ====================

@admin_bp.route('/audit-logs', methods=['GET', 'OPTIONS'])
@token_required
@role_required('super_admin', 'admin', 'auditor')
def get_audit_logs():
    """Get audit logs with filters"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        # Build query
        query = AuditLog.query.join(User).filter(User.church_id == church_id)
        
        # Apply filters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('perPage', 20, type=int)
        user_id = request.args.get('userId', type=int)
        action = request.args.get('action')
        resource = request.args.get('resource')
        start_date = request.args.get('startDate')
        end_date = request.args.get('endDate')
        search = request.args.get('search')
        
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        
        if action:
            query = query.filter(AuditLog.action.ilike(f'%{action}%'))
        
        if resource:
            query = query.filter(AuditLog.resource == resource)
        
        if start_date:
            query = query.filter(AuditLog.timestamp >= datetime.fromisoformat(start_date))
        
        if end_date:
            end = datetime.fromisoformat(end_date)
            end = end.replace(hour=23, minute=59, second=59)
            query = query.filter(AuditLog.timestamp <= end)
        
        if search:
            query = query.filter(
                db.or_(
                    AuditLog.action.ilike(f'%{search}%'),
                    AuditLog.resource.ilike(f'%{search}%'),
                    AuditLog.data.cast(db.String).ilike(f'%{search}%')
                )
            )
        
        # Get paginated results
        paginated = query.order_by(
            AuditLog.timestamp.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        # Format response
        log_list = []
        for log in paginated.items:
            user = User.query.get(log.user_id)
            log_list.append({
                'id': log.id,
                'userId': log.user_id,
                'userName': user.full_name if user else 'Unknown',
                'action': log.action,
                'resource': log.resource,
                'resourceId': log.resource_id,
                'data': log.data,
                'ipAddress': log.ip_address,
                'userAgent': log.user_agent,
                'timestamp': log.timestamp.isoformat() if log.timestamp else None
            })
        
        return jsonify({
            'logs': log_list,
            'total': paginated.total,
            'pages': paginated.pages,
            'currentPage': paginated.page
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting audit logs: {str(e)}")
        return jsonify({'error': 'Failed to get audit logs'}), 500


@admin_bp.route('/audit-logs/export', methods=['GET', 'OPTIONS'])
@token_required
@role_required('super_admin', 'admin', 'auditor')
def export_audit_logs():
    """Export audit logs as CSV"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        logs = AuditLog.query.join(User).filter(User.church_id == church_id).order_by(
            AuditLog.timestamp.desc()
        ).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        writer.writerow(['ID', 'Timestamp', 'User ID', 'User Name', 'Action', 'Resource', 'Resource ID', 'IP Address', 'Data'])
        
        # Write data
        for log in logs:
            user = User.query.get(log.user_id)
            writer.writerow([
                log.id,
                log.timestamp.strftime('%Y-%m-%d %H:%M:%S') if log.timestamp else '',
                log.user_id,
                user.full_name if user else 'Unknown',
                log.action,
                log.resource or '',
                log.resource_id or '',
                log.ip_address or '',
                str(log.data) if log.data else ''
            ])
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=audit_logs_{datetime.utcnow().strftime("%Y%m%d")}.csv'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting audit logs: {str(e)}")
        return jsonify({'error': 'Failed to export audit logs'}), 500


# ==================== SYSTEM SETTINGS ====================

@admin_bp.route('/settings', methods=['GET', 'OPTIONS'])
@token_required
@role_required('super_admin')
def get_system_settings():
    """Get system settings"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        
        # Get all settings for this church
        settings = Setting.query.filter_by(church_id=church_id).all()
        
        # Convert to dictionary
        settings_dict = {}
        for setting in settings:
            settings_dict[setting.key] = setting.value
        
        # Default settings if not found
        default_settings = {
            'siteName': 'Church Accounting System',
            'siteUrl': 'http://localhost:3000',
            'adminEmail': g.current_user.email,
            'timezone': 'UTC',
            'dateFormat': 'YYYY-MM-DD',
            'currency': 'GHS',
            'sessionTimeout': 30,
            'maxLoginAttempts': 5,
            'passwordMinLength': 8,
            'requireTwoFactor': False,
            'requireEmailVerification': True,
            'enableEmailNotifications': True,
            'enablePushNotifications': False,
            'notificationEmail': g.current_user.email,
            'enableAutoBackup': False,
            'backupFrequency': 'weekly',
            'backupRetentionDays': 30
        }
        
        # Merge with defaults
        for key, value in default_settings.items():
            if key not in settings_dict:
                settings_dict[key] = value
        
        return jsonify(settings_dict), 200
        
    except Exception as e:
        logger.error(f"Error getting system settings: {str(e)}")
        return jsonify({'error': 'Failed to get system settings'}), 500


@admin_bp.route('/settings', methods=['PUT', 'OPTIONS'])
@token_required
@role_required('super_admin')
def update_system_settings():
    """Update system settings"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        church_id = g.current_user.church_id
        
        # Update each setting
        for key, value in data.items():
            setting = Setting.query.filter_by(church_id=church_id, key=key).first()
            
            if setting:
                setting.value = value
                setting.updated_at = datetime.utcnow()
            else:
                setting = Setting(
                    church_id=church_id,
                    key=key,
                    value=value
                )
                db.session.add(setting)
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='UPDATE_SYSTEM_SETTINGS',
            resource='settings',
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Settings updated successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating system settings: {str(e)}")
        return jsonify({'error': 'Failed to update settings'}), 500


# ==================== ROLE MANAGEMENT ====================

@admin_bp.route('/roles', methods=['GET', 'OPTIONS'])
@token_required
@role_required('super_admin')
def get_roles():
    """Get all roles"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        roles = Role.query.all()
        
        role_list = []
        for role in roles:
            # Count users with this role
            user_count = User.query.filter_by(role=role.name).count()
            
            role_list.append({
                'id': role.id,
                'name': role.name,
                'description': role.description,
                'userCount': user_count,
                'createdAt': role.created_at.isoformat() if role.created_at else None
            })
        
        return jsonify(role_list), 200
        
    except Exception as e:
        logger.error(f"Error getting roles: {str(e)}")
        return jsonify({'error': 'Failed to get roles'}), 500


@admin_bp.route('/roles', methods=['POST', 'OPTIONS'])
@token_required
@role_required('super_admin')
def create_role():
    """Create a new role"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        
        if not data.get('name'):
            return jsonify({'error': 'Role name is required'}), 400
        
        # Check if role already exists
        existing = Role.query.filter_by(name=data['name']).first()
        if existing:
            return jsonify({'error': 'Role already exists'}), 400
        
        role = Role(
            name=data['name'],
            description=data.get('description')
        )
        
        db.session.add(role)
        db.session.commit()
        
        return jsonify({
            'message': 'Role created successfully',
            'id': role.id,
            'name': role.name,
            'description': role.description
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating role: {str(e)}")
        return jsonify({'error': 'Failed to create role'}), 500


@admin_bp.route('/roles/<int:role_id>', methods=['PUT', 'DELETE', 'OPTIONS'])
@token_required
@role_required('super_admin')
def manage_role(role_id):
    """Update or delete a role"""
    if request.method == 'OPTIONS':
        return '', 200
    
    role = Role.query.get(role_id)
    
    if not role:
        return jsonify({'error': 'Role not found'}), 404
    
    # PUT - Update role
    if request.method == 'PUT':
        try:
            data = request.get_json()
            
            if 'name' in data:
                role.name = data['name']
            if 'description' in data:
                role.description = data['description']
            
            db.session.commit()
            
            return jsonify({'message': 'Role updated successfully'}), 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating role: {str(e)}")
            return jsonify({'error': 'Failed to update role'}), 500
    
    # DELETE - Delete role
    elif request.method == 'DELETE':
        try:
            # Don't allow deleting built-in roles
            built_in_roles = ['super_admin', 'admin', 'treasurer', 'accountant', 'auditor', 'pastor', 'finance_committee', 'user']
            if role.name in built_in_roles:
                return jsonify({'error': 'Cannot delete built-in role'}), 400
            
            db.session.delete(role)
            db.session.commit()
            
            return jsonify({'message': 'Role deleted successfully'}), 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting role: {str(e)}")
            return jsonify({'error': 'Failed to delete role'}), 500


# ==================== PERMISSIONS ====================

@admin_bp.route('/permissions', methods=['GET', 'OPTIONS'])
@token_required
@role_required('super_admin')
def get_permissions():
    """Get all permissions"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        permissions = Permission.query.all()
        
        perm_list = []
        for perm in permissions:
            perm_list.append({
                'id': perm.id,
                'name': perm.name,
                'category': perm.category,
                'description': perm.description
            })
        
        return jsonify(perm_list), 200
        
    except Exception as e:
        logger.error(f"Error getting permissions: {str(e)}")
        return jsonify({'error': 'Failed to get permissions'}), 500


@admin_bp.route('/role-permissions', methods=['GET', 'OPTIONS'])
@token_required
@role_required('super_admin')
def get_role_permissions():
    """Get permissions for all roles"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        roles = Role.query.all()
        permissions = Permission.query.all()
        
        result = {}
        for role in roles:
            role_perms = {}
            for perm in permissions:
                # Check if role has this permission (simplified - you'd have a role_permissions table)
                # For now, we'll return a structure
                role_perms[perm.id] = True if role.name == 'super_admin' else False
            
            result[role.id] = role_perms
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error getting role permissions: {str(e)}")
        return jsonify({'error': 'Failed to get role permissions'}), 500


@admin_bp.route('/role-permissions', methods=['PUT', 'OPTIONS'])
@token_required
@role_required('super_admin')
def update_role_permissions():
    """Update role permissions"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        
        # This would update the role_permissions table
        # Implementation depends on your database schema
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='UPDATE_ROLE_PERMISSIONS',
            resource='permissions',
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Permissions updated successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating permissions: {str(e)}")
        return jsonify({'error': 'Failed to update permissions'}), 500


# ==================== CHURCH SETTINGS ====================

@admin_bp.route('/church', methods=['GET', 'OPTIONS'])
@token_required
@role_required('super_admin', 'admin')
def get_church_settings():
    """Get church settings"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = g.current_user.church_id
        church = Church.query.get(church_id)
        
        if not church:
            return jsonify({'error': 'Church not found'}), 404
        
        return jsonify({
            'id': church.id,
            'name': church.name,
            'legalName': church.legal_name,
            'address': church.address,
            'city': church.city,
            'state': church.state,
            'postalCode': church.postal_code,
            'country': church.country,
            'phone': church.phone,
            'email': church.email,
            'website': church.website,
            'taxId': church.tax_id,
            'foundedDate': church.founded_date.isoformat() if church.founded_date else None,
            'pastorName': church.pastor_name,
            'associatePastor': church.associate_pastor,
            'denomination': church.denomination,
            'serviceTimes': church.service_times,
            'description': church.description,
            'logo': church.logo,
            'createdAt': church.created_at.isoformat() if church.created_at else None
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting church settings: {str(e)}")
        return jsonify({'error': 'Failed to get church settings'}), 500


@admin_bp.route('/church', methods=['PUT', 'OPTIONS'])
@token_required
@role_required('super_admin', 'admin')
def update_church_settings():
    """Update church settings"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        church_id = g.current_user.church_id
        church = Church.query.get(church_id)
        
        if not church:
            return jsonify({'error': 'Church not found'}), 404
        
        # Update fields
        if 'name' in data:
            church.name = data['name']
        if 'legalName' in data:
            church.legal_name = data['legalName']
        if 'address' in data:
            church.address = data['address']
        if 'city' in data:
            church.city = data['city']
        if 'state' in data:
            church.state = data['state']
        if 'postalCode' in data:
            church.postal_code = data['postalCode']
        if 'country' in data:
            church.country = data['country']
        if 'phone' in data:
            church.phone = data['phone']
        if 'email' in data:
            church.email = data['email']
        if 'website' in data:
            church.website = data['website']
        if 'taxId' in data:
            church.tax_id = data['taxId']
        if 'foundedDate' in data:
            church.founded_date = datetime.fromisoformat(data['foundedDate']) if data['foundedDate'] else None
        if 'pastorName' in data:
            church.pastor_name = data['pastorName']
        if 'associatePastor' in data:
            church.associate_pastor = data['associatePastor']
        if 'denomination' in data:
            church.denomination = data['denomination']
        if 'serviceTimes' in data:
            church.service_times = data['serviceTimes']
        if 'description' in data:
            church.description = data['description']
        
        db.session.commit()
        
        # Log audit
        audit_log = AuditLog(
            user_id=g.current_user.id,
            action='UPDATE_CHURCH_SETTINGS',
            resource='church',
            resource_id=church.id,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'message': 'Church settings updated successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating church settings: {str(e)}")
        return jsonify({'error': 'Failed to update church settings'}), 500


# ==================== BACKUP ====================

@admin_bp.route('/backup', methods=['POST', 'OPTIONS'])
@token_required
@role_required('super_admin')
def create_backup():
    """Create a database backup"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # This would create a database backup
        # Implementation depends on your database
        
        return jsonify({
            'message': 'Backup created successfully',
            'backupId': f"backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        }), 200
        
    except Exception as e:
        logger.error(f"Error creating backup: {str(e)}")
        return jsonify({'error': 'Failed to create backup'}), 500


@admin_bp.route('/backups', methods=['GET', 'OPTIONS'])
@token_required
@role_required('super_admin')
def get_backups():
    """Get list of backups"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # This would list available backups
        # For now, return mock data
        backups = [
            {
                'id': 'backup_20250309_120000',
                'filename': 'backup_20250309_120000.sql',
                'size': 1024 * 1024 * 10,  # 10 MB
                'createdAt': datetime.utcnow().isoformat()
            }
        ]
        
        return jsonify(backups), 200
        
    except Exception as e:
        logger.error(f"Error getting backups: {str(e)}")
        return jsonify({'error': 'Failed to get backups'}), 500


@admin_bp.route('/backup/<backup_id>/restore', methods=['POST', 'OPTIONS'])
@token_required
@role_required('super_admin')
def restore_backup(backup_id):
    """Restore a backup"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # This would restore a backup
        
        return jsonify({'message': 'Backup restored successfully'}), 200
        
    except Exception as e:
        logger.error(f"Error restoring backup: {str(e)}")
        return jsonify({'error': 'Failed to restore backup'}), 500


@admin_bp.route('/backup/<backup_id>/download', methods=['GET', 'OPTIONS'])
@token_required
@role_required('super_admin')
def download_backup(backup_id):
    """Download a backup file"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # This would serve the backup file
        # For now, return a simple text file
        output = io.StringIO()
        output.write("This is a mock backup file")
        output.seek(0)
        
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'application/octet-stream'
        response.headers['Content-Disposition'] = f'attachment; filename={backup_id}.sql'
        
        return response
        
    except Exception as e:
        logger.error(f"Error downloading backup: {str(e)}")
        return jsonify({'error': 'Failed to download backup'}), 500