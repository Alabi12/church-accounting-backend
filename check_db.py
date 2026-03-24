from app import create_app, db
from sqlalchemy import inspect, text

print("Creating app...")
app = create_app()

with app.app_context():
    # Get the database URL
    db_url = str(db.engine.url)
    print(f"\n=== Database in use ===")
    print(f"URL: {db_url}")
    
    # Get the database file path
    if 'sqlite:///' in db_url:
        db_path = db_url.replace('sqlite:///', '')
        print(f"File path: {db_path}")
    
    # List all tables
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print(f"\n=== Tables in database ===")
    print(f"Total tables: {len(tables)}")
    
    # Check if employees table exists
    if 'employees' in tables:
        columns = inspector.get_columns('employees')
        print(f"\n=== Employees table columns ===")
        for col in columns[:10]:  # Show first 10 columns
            print(f"  - {col['name']}")
        
        # Check for employee_code column
        has_employee_code = any(c['name'] == 'employee_code' for c in columns)
        print(f"\nHas employee_code column: {has_employee_code}")
        
        # Count employees
        result = db.session.execute(text("SELECT COUNT(*) FROM employees")).scalar()
        print(f"Number of employees: {result}")
    else:
        print("\n❌ employees table not found!")
        print(f"Available tables: {tables[:20]}")
