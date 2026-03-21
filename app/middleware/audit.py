from flask import request, g
import json
import logging
from datetime import datetime
from app.extensions import db
import time

logger = logging.getLogger(__name__)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100), nullable=False)
    resource = db.Column(db.String(100))
    resource_id = db.Column(db.Integer)
    data = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', back_populates='audit_logs')

class AuditMiddleware:
    def __init__(self, app):
        self.app = app
        app.before_request(self.before_request)
        app.after_request(self.after_request)
    
    def before_request(self):
        g.start_time = time.time()
        g.request_data = {
            'method': request.method,
            'path': request.path,
            'ip': request.remote_addr,
            'user_agent': request.user_agent.string
        }
    
    def after_request(self, response):
        # Calculate request duration
        duration = time.time() - g.start_time
        
        # Determine if this is a financial transaction that needs audit
        if self.should_audit(request.path, request.method):
            try:
                self.create_audit_log(response)
            except Exception as e:
                logger.error(f"Failed to create audit log: {str(e)}")
        
        # Log to file as well
        self.log_request(response, duration)
        
        return response
    
    def should_audit(self, path, method):
        """Determine if request should be audited"""
        # Audit all POST, PUT, DELETE on financial endpoints
        audit_paths = [
            '/api/income', '/api/expenses', '/api/payroll', 
            '/api/budget', '/api/transactions'
        ]
        
        if method in ['POST', 'PUT', 'DELETE']:
            for audit_path in audit_paths:
                if path.startswith(audit_path):
                    return True
        
        # Also audit sensitive GET requests
        if path.startswith('/api/reports') and 'export' in path:
            return True
        
        return False
    
    def create_audit_log(self, response):
        """Create audit log entry"""
        if response.status_code >= 400:
            return  # Don't audit errors
        
        # Get request data
        user_id = g.current_user.id if hasattr(g, 'current_user') else None
        
        # Try to parse JSON data
        data = None
        try:
            if request.is_json:
                data = request.get_json()
            elif request.form:
                data = request.form.to_dict()
        except:
            data = None
        
        # Create audit log
        audit_log = AuditLog(
            user_id=user_id,
            action=f"{request.method} {request.path}",
            resource=self.get_resource_name(request.path),
            data=json.dumps(data) if data else None,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        
        # Extract resource ID from path if possible
        path_parts = request.path.split('/')
        if len(path_parts) > 3 and path_parts[3].isdigit():
            audit_log.resource_id = int(path_parts[3])
        
        db.session.add(audit_log)
        db.session.commit()
    
    def get_resource_name(self, path):
        """Extract resource name from path"""
        parts = path.split('/')
        if len(parts) > 2:
            return parts[2]  # e.g., 'income', 'expenses'
        return path
    
    def log_request(self, response, duration):
        """Log request details"""
        log_data = {
            'method': request.method,
            'path': request.path,
            'status': response.status_code,
            'duration_ms': round(duration * 1000, 2),
            'ip': request.remote_addr,
            'user': g.current_user.username if hasattr(g, 'current_user') else 'anonymous'
        }
        
        if response.status_code >= 500:
            logger.error(json.dumps(log_data))
        elif response.status_code >= 400:
            logger.warning(json.dumps(log_data))
        else:
            logger.info(json.dumps(log_data))