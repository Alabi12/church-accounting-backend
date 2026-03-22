# app/socketio_helper.py
import os

# Dummy SocketIO for production
class DummySocketIO:
    def __init__(self, *args, **kwargs):
        pass
    
    def on(self, *args, **kwargs):
        def decorator(f):
            return f
        return decorator
    
    def emit(self, *args, **kwargs):
        pass
    
    def init_app(self, *args, **kwargs):
        pass
    
    def run(self, *args, **kwargs):
        pass

# Dummy functions for production
def dummy_emit(*args, **kwargs):
    pass

# Create socketio instance based on environment
if os.environ.get('FLASK_ENV') == 'production':
    socketio = DummySocketIO()
    emit = dummy_emit
    join_room = dummy_emit
    leave_room = dummy_emit
    print("SocketIO disabled (production mode)")
else:
    try:
        from flask_socketio import SocketIO, emit, join_room, leave_room
        socketio = SocketIO(async_mode='threading')
        print("SocketIO enabled for development")  # Removed emoji
    except ImportError as e:
        print(f"SocketIO import failed: {e}")  # Removed emoji
        socketio = DummySocketIO()
        emit = dummy_emit
        join_room = dummy_emit
        leave_room = dummy_emit