import os
from dotenv import load_dotenv
import pathlib

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'jwt-secret-key-change-in-production'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', 'http://localhost:3000,http://localhost:5000').split(',')
    
    # Get the base directory of the application
    BASE_DIR = pathlib.Path(__file__).parent.parent.absolute()

class DevelopmentConfig(Config):
    DEBUG = True
    
    # Use a regular attribute, not a property
    # Ensure the instance directory exists
    _db_path = Config.BASE_DIR / 'instance' / 'dev.db'
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{_db_path}'
    
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 5,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
    }

class ProductionConfig(Config):
    DEBUG = False
    
    # Check for environment variable first
    _db_url = os.environ.get('DATABASE_URL')
    if _db_url:
        SQLALCHEMY_DATABASE_URI = _db_url
    else:
        _db_path = Config.BASE_DIR / 'instance' / 'prod_church_accounting.db'
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{_db_path}'

class TestingConfig(Config):
    TESTING = True
    
    _db_path = Config.BASE_DIR / 'instance' / 'test_church_accounting.db'
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{_db_path}'

# Dictionary to map configuration names to config classes
config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}