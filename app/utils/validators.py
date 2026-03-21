import re
from email_validator import validate_email as validate_email_lib, EmailNotValidError

def validate_email(email):
    """Validate email format"""
    try:
        valid = validate_email_lib(email)
        return True
    except EmailNotValidError:
        return False

def validate_password_strength(password):
    """
    Validate password strength
    Returns: (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number"
    
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character"
    
    return True, "Password is strong"

def validate_phone(phone):
    """Validate phone number format"""
    pattern = r'^\+?[\d\s-]{10,}$'
    return bool(re.match(pattern, phone))

def validate_amount(amount):
    """Validate monetary amount"""
    try:
        amount = float(amount)
        return amount > 0
    except (ValueError, TypeError):
        return False

def validate_date_range(start_date, end_date):
    """Validate date range"""
    from datetime import datetime
    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        return start <= end
    except (ValueError, TypeError):
        return False