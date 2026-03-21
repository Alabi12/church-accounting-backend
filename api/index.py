# api/index.py
import sys
import os

# Add the parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

# Create Flask app - Vercel looks for 'app' by default
app = create_app('production')

# Optional: Add a test endpoint
@app.route('/api/test')
def test():
    return {"message": "Flask is working on Vercel!"}