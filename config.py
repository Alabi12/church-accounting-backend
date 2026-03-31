# app/config.py
import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'neondb_owner:npg_cUTJLED2q6XC@ep-snowy-shape-amae5iiu-pooler.c-5.us-east-1.aws.neon.tech/neondb?channel_binding=require&sslmode=require')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-dev-key-change-in-production')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)


     # Email settings
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@church.com')

class DevelopmentConfig(Config):
    DEBUG = True
    # Use absolute path for the database
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DB_PATH = os.environ.get('DATABASE_URL', f'sqlite:///{os.path.join(BASE_DIR, "instance", "dev_church_accounting.db")}')
    
    # If DATABASE_URL is just a filename, convert to full path
    if DB_PATH.startswith('sqlite:///') and not DB_PATH.startswith('sqlite:////'):
        # It's a relative path, make it absolute
        db_file = DB_PATH.replace('sqlite:///', '')
        if not os.path.isabs(db_file):
            # If it's just a filename, put it in instance folder
            if os.path.sep not in db_file:
                db_file = os.path.join(BASE_DIR, 'instance', db_file)
            SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_file}'
        else:
            SQLALCHEMY_DATABASE_URI = DB_PATH
    else:
        SQLALCHEMY_DATABASE_URI = DB_PATH
    
    print(f"📁 Database URI: {SQLALCHEMY_DATABASE_URI}")

class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', '').replace('postgres://', 'postgresql://')
    
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("DATABASE_URL environment variable is required in production")
    
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 1,
        'max_overflow': 0,
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True

config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig
}