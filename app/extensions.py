# app/extensions.py

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_mail import Mail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import logging

# Database
db = SQLAlchemy()

# Migration
migrate = Migrate()

# JWT
jwt = JWTManager()

# Mail
mail = Mail()

# Rate Limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Logger
logger = logging.getLogger(__name__)