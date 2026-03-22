# app/__init__.py - Fixed CORS configuration with rate limiting disabled
from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
import os
import logging
import traceback
from datetime import datetime, timedelta
from app.extensions import db, jwt, mail, logger, migrate
from app.config import config_by_name
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import event, inspect
from flask import g

# Import socketio from helper (handles production gracefully)
from app.socketio_helper import socketio, emit, join_room, leave_room

def create_app(config_name='development'):
    print(f"🔵 STEP 1: create_app started with config: {config_name}")
    
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])
    
    # JWT Configuration
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'super-secret-key-change-in-production')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
    app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=30)
    
    # Database pool config - optimized for serverless
    if config_name == 'production':
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_size': 1,
            'max_overflow': 0,
            'pool_pre_ping': True,
            'pool_recycle': 300,
            'pool_timeout': 30,
        }
    else:
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_size': 20,
            'max_overflow': 30,
            'pool_timeout': 30,
            'pool_recycle': 1800,
            'pool_pre_ping': True,
        }
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    
    print("🔵 STEP 5: SocketIO configured via helper")
    
    print("🔵 STEP 6: Configuring CORS...")
    
    # CORS CONFIGURATION - Let Flask-CORS handle all CORS including OPTIONS
    if config_name == 'production':
        allowed_origins = os.environ.get('CORS_ORIGINS', 'https://church-accounting-frontend.vercel.app').split(',')
        print(f"✅ Production CORS origins: {allowed_origins}")
    else:
        # Allow all local development origins
        allowed_origins = [
            "http://localhost:3000", 
            "http://127.0.0.1:3000",
            "http://localhost:5000",
            "http://127.0.0.1:5000",
            "http://localhost:5173",  # Vite default
            "http://127.0.0.1:5173"
        ]
        print(f"🔧 Development CORS origins: {allowed_origins}")

    # Configure CORS - This handles all CORS including OPTIONS preflight requests
    CORS(app, 
         origins=allowed_origins,
         supports_credentials=True,
         allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"],
         methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
         expose_headers=["Content-Type", "Authorization"],
         max_age=3600)
    
    # Add a before_request handler to handle OPTIONS requests early
    @app.before_request
    def handle_options():
        """Handle OPTIONS requests early to bypass JWT authentication"""
        if request.method == 'OPTIONS':
            print(f"🔧 Handling OPTIONS preflight for {request.path}")
            response = make_response()
            response.headers.add("Access-Control-Allow-Origin", request.headers.get('Origin', 'http://localhost:3000'))
            response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, Accept")
            response.headers.add("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, PATCH")
            response.headers.add("Access-Control-Allow-Credentials", "true")
            response.headers.add("Access-Control-Max-Age", "3600")
            return response, 200
    
    # Simple after_request for non-CORS headers only
    @app.after_request
    def add_security_headers(response):
        # Only add security headers, NOT CORS headers (they're already added by Flask-CORS)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        return response
    
    mail.init_app(app)
    
    print("🔵 STEP 7: Setting up rate limiter...")
    
    # ============================================================
    # COMPLETELY DISABLE RATE LIMITING FOR DEVELOPMENT
    # ============================================================
    
    # Create a dummy limiter that does absolutely nothing
    class DummyLimiter:
        def __init__(self):
            self.enabled = False
        
        def limit(self, *args, **kwargs):
            """Return a decorator that does nothing"""
            def decorator(f):
                return f
            return decorator
        
        def init_app(self, app):
            pass
        
        def __getattr__(self, name):
            """Return a no-op function for any other method calls"""
            return lambda *args, **kwargs: None
    
    # Create dummy limiter
    limiter = DummyLimiter()
    app.limiter = limiter
    
    # Explicitly disable rate limiting in Flask config
    app.config['RATELIMIT_ENABLED'] = False
    app.config['RATELIMIT_DEFAULT'] = []
    
    if config_name == 'production':
        # Even in production, use a placeholder for now
        print("⚠️ Rate limiting is disabled for all environments")
    else:
        print("⚠️ Rate limiting completely disabled for development")
    
    print("🔵 STEP 8: Entering app context...")
    
    with app.app_context():
        print("🔵 STEP 9: Inside app context, importing models...")
        
        try:
            from app.models import User, Church, Account, Transaction, Member, AuditLog, UserRole, Role, PermissionModel, Setting, Budget, BudgetCategory, BudgetComment, BudgetAttachment, JournalEntry, JournalLine, ApprovalWorkflow, ApprovalRequest, Approval, ApprovalComment
            print("🔵 STEP 10: Models imported successfully")
        except Exception as e:
            print(f"❌ ERROR importing models: {e}")
            return None
        
        print("🔵 STEP 11: Checking/Creating database tables...")
        
        try:
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            
            if not existing_tables:
                db.create_all()
                print("🔵 STEP 12: Database tables created")
            else:
                print(f"🔵 STEP 12: Database tables already exist ({len(existing_tables)} tables found)")
                
                try:
                    from flask_migrate import upgrade
                    upgrade()
                    print("✅ Migrations applied")
                except Exception as e:
                    print(f"⚠️ Migration skipped: {e}")
        except Exception as e:
            print(f"❌ ERROR with database: {e}")
            return None
        
        # Create default church if not exists
        try:
            church = Church.query.first()
            if not church:
                church = Church(
                    name='Default Church',
                    email='church@example.com',
                    phone='1234567890',
                    address='123 Church Street'
                )
                db.session.add(church)
                db.session.commit()
                print('✅ Default church created')
            else:
                print('👤 Church already exists')
        except Exception as e:
            print(f"❌ ERROR with church creation: {e}")
            return None
        
        # Create default roles if not exist
        try:
            roles = ['super_admin', 'admin', 'treasurer', 'accountant', 'auditor', 'pastor', 'finance_committee', 'user']
            for role_name in roles:
                if not Role.query.filter_by(name=role_name).first():
                    role = Role(name=role_name, description=f"{role_name.replace('_', ' ').title()} role")
                    db.session.add(role)
                    print(f'✅ Created role: {role_name}')
                else:
                    print(f'👤 Role {role_name} already exists')
            
            db.session.commit()
        except Exception as e:
            print(f"❌ ERROR with role creation: {e}")
            return None
        
        # Create admin user if not exists
        try:
            admin = User.query.filter_by(email='admin@church.org').first()
            if not admin:
                if config_name == 'production':
                    admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
                else:
                    admin_password = 'admin123'
                
                admin = User(
                    email='admin@church.org',
                    username='admin',
                    first_name='Admin',
                    last_name='User',
                    role='super_admin',
                    church_id=church.id,
                    is_active=True,
                    is_verified=True
                )
                admin.set_password(admin_password)
                db.session.add(admin)
                db.session.commit()
                print(f'✅ Default admin user created in {config_name} mode')
            else:
                print('👤 Admin user already exists')
        except Exception as e:
            print(f"❌ ERROR with admin creation: {e}")
            return None
        
        # Setup connection pool event listeners (only in development)
        if app.debug:
            try:
                @event.listens_for(db.engine, 'connect')
                def receive_connect(dbapi_connection, connection_record):
                    print("🔌 New database connection created")
                
                @event.listens_for(db.engine, 'close')
                def receive_close(dbapi_connection, connection_record):
                    print("🔌 Database connection closed")
                
                @event.listens_for(db.engine, 'checkout')
                def receive_checkout(dbapi_connection, connection_record, connection_proxy):
                    print("🔌 Connection checked out")
                
                @event.listens_for(db.engine, 'checkin')
                def receive_checkin(dbapi_connection, connection_record):
                    print("🔌 Connection returned to pool")
                    
                print("✅ Connection pool event listeners registered")
            except Exception as e:
                print(f"⚠️ Could not register connection pool listeners: {e}")

    print("🔵 STEP 13: Registering blueprints...")
    
    # Register blueprints
    try:
        from app.routes.auth_routes import auth_bp
        from app.routes.budget_routes import budget_bp
        from app.routes.accounting_routes import accounting_bp
        from app.routes.treasurer_routes import treasurer_bp
        from app.routes.pastor_routes import pastor_bp
        from app.routes.dashboard_routes import dashboard_bp
        from app.routes.income_routes import income_bp
        from app.routes.expense_routes import expense_bp
        from app.routes.member_routes import member_bp
        from app.routes.report_routes import report_bp
        from app.routes.admin_routes import admin_bp
        from app.routes.donation_routes import donation_bp
        from app.routes.church_routes import church_bp
        from app.routes.journal_routes import journal_bp
        from app.routes.approval_routes import approval_bp
        from app.routes.account_routes import account_bp
        from app.routes.payroll_routes import payroll_bp
        from app.routes.payslip_routes import payslip_bp
        from app.routes.leave_routes import leave_bp
        from app.routes.tax_routes import tax_bp
        
        app.register_blueprint(auth_bp, url_prefix='/api/auth')
        app.register_blueprint(budget_bp, url_prefix='/api/budgets')
        app.register_blueprint(accounting_bp, url_prefix='/api/accounting')
        app.register_blueprint(treasurer_bp, url_prefix='/api/treasurer')
        app.register_blueprint(pastor_bp, url_prefix='/api/pastor')
        app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')
        app.register_blueprint(income_bp, url_prefix='/api/income')
        app.register_blueprint(expense_bp, url_prefix='/api/expenses')
        app.register_blueprint(member_bp, url_prefix='/api/members')
        app.register_blueprint(report_bp, url_prefix='/api/reports')
        app.register_blueprint(admin_bp, url_prefix='/api/admin')
        app.register_blueprint(donation_bp, url_prefix='/api/donations')
        app.register_blueprint(church_bp, url_prefix='/api')
        app.register_blueprint(journal_bp, url_prefix='/api')
        app.register_blueprint(approval_bp, url_prefix='/api')
        app.register_blueprint(account_bp, url_prefix='/api')
        app.register_blueprint(payroll_bp, url_prefix='/api/payroll')
        app.register_blueprint(payslip_bp, url_prefix='/api/payslip')
        app.register_blueprint(leave_bp, url_prefix='/api/leave')
        app.register_blueprint(tax_bp, url_prefix='/api/tax')
        
        print("🔵 STEP 14: Blueprints registered successfully")
    except Exception as e:
        print(f"❌ ERROR registering blueprints: {e}")
        traceback.print_exc()
        return None
    
    print("🔵 STEP 15: Adding teardown and request handlers...")
    
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if exception:
            db.session.rollback()
        db.session.remove()
    
    @app.before_request
    def log_request_info():
        if config_name == 'development':
            # Log all requests for debugging
            print(f"📥 {request.method} {request.path} from {request.headers.get('Origin')}")
            if request.method == 'OPTIONS':
                print(f"   🔄 Preflight request received")
    
    @app.route('/health', methods=['GET'])
    def health_check():
        db_status = 'healthy'
        try:
            db.session.execute('SELECT 1').scalar()
        except Exception as e:
            db_status = f'unhealthy: {str(e)}'
        
        return jsonify({
            'status': 'healthy',
            'environment': config_name,
            'database': db_status,
            'cors_enabled': True,
            'cors_origins': allowed_origins,
            'rate_limiting_enabled': False,  # Always false now
            'socketio_enabled': False,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    
    @app.route('/api/test', methods=['GET'])
    def test_endpoint():
        """Simple test endpoint"""
        return jsonify({
            'message': 'Backend is working',
            'status': 'ok',
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    
    @app.route('/debug/cors', methods=['GET'])
    def debug_cors():
        """Debug endpoint to check CORS headers"""
        return jsonify({
            'message': 'CORS debug endpoint',
            'request_origin': request.headers.get('Origin'),
            'request_headers': dict(request.headers),
            'allowed_origins': allowed_origins
        }), 200
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        if config_name == 'production':
            return jsonify({'error': 'Resource not found'}), 404
        return jsonify({'error': 'Resource not found', 'details': str(error)}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        logger.error(f'💥 Internal server error: {str(error)}')
        logger.error(traceback.format_exc())
        
        if config_name == 'production':
            return jsonify({'error': 'Internal server error'}), 500
        return jsonify({'error': str(error), 'traceback': traceback.format_exc()}), 500
        
    @app.errorhandler(422)
    def handle_unprocessable_entity(err):
        return jsonify({
            'error': 'Validation Error',
            'message': 'Invalid data provided'
        }), 422
    
    # Remove the 429 error handler since rate limiting is disabled
    # @app.errorhandler(429)
    # def ratelimit_error(error):
    #     return jsonify({
    #         'error': 'Rate limit exceeded',
    #         'message': 'Too many requests. Please try again later.'
    #     }), 429
    
    print("🔵 STEP 16: Returning app...")
    print(f"🔵 FINAL: App is {app}")
    return app