# wsgi.py
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app

# Create app with production config
app = create_app('production')
application = app

if __name__ == '__main__':
    app.run()