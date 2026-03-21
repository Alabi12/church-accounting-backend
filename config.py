# app/config.py
import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'neondb_owner:npg_cUTJLED2q6XC@ep-snowy-shape-amae5iiu-pooler.c-5.us-east-1.aws.neon.tech/neondb?channel_binding=require&sslmode=require')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-dev-key-change-in-production')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///dev_church_accounting.db'

class ProductionConfig(Config):
    DEBUG = False
    # Use PostgreSQL from environment variable
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', '').replace('postgres://', 'postgresql://')
    
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("DATABASE_URL environment variable is required in production")
    
    # Serverless-friendly pool settings
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 1,
        'max_overflow': 0,
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    # Security settings
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True

config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig
}