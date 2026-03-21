from app import create_app
import os

config_name = os.environ.get('FLASK_ENV', 'development')
app = create_app(config_name)

if __name__ == '__main__':
    print(f"🚀 Starting server in {config_name} mode...")
    app.run(debug=(config_name == 'development'), host='0.0.0.0', port=5000)