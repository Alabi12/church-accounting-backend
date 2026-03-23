import sys
print("Python version:", sys.version)

try:
    print("1. Importing create_app...")
    from app import create_app
    print("   ✅ create_app imported")
    
    print("2. Creating app...")
    app = create_app()
    print("   ✅ App created")
    
    print("3. Pushing app context...")
    with app.app_context():
        print("   ✅ App context pushed")
        
        print("4. Importing db...")
        from app import db
        print("   ✅ db imported")
        
        print("5. Creating tables...")
        db.create_all()
        print("   ✅ Tables created")
        
        print("6. Listing tables...")
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"   Tables: {tables}")
        
        # Check specific tables
        required = ['employees', 'payroll_runs', 'payroll_lines', 'leave_types']
        for table in required:
            if table in tables:
                print(f"   ✅ {table} exists")
            else:
                print(f"   ❌ {table} missing")
                
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
