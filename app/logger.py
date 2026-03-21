import logging
import sys
from pythonjsonlogger import jsonlogger

def setup_logger(name):
    """Setup logger with consistent formatting"""
    logger = logging.getLogger(name)
    
    # Only add handler if it doesn't have one
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = jsonlogger.JsonFormatter(
            '%(asctime)s %(levelname)s %(name)s %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    
    return logger

# Create a default logger for the app
app_logger = setup_logger('app')