# wsgi.py
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app

# Get config from environment variable or default to development for local use
# You can set FLASK_CONFIG=production in production environment
config_name = os.environ.get('FLASK_CONFIG', 'development')
app = create_app(config_name)
application = app

if __name__ == '__main__':
    # Run with development settings when executed directly
    app.run(debug=True, host='0.0.0.0', port=5000)