from app import create_app, db
from app.models import Employee
from sqlalchemy import inspect
import os

print("Creating app...")
app = create_app()

print("Testing Employee query...")
with app.app_context():
    try:
        # Get the actual database connection info
        db_url = str(db.engine.url)
        print(f"Database URL: {db_url}")
        
        # List all tables
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"\nTables in database: {tables}")
        
        if 'employees' not in tables:
            print("❌ employees table does not exist!")
        else:
            # Check columns in employees table
            columns = inspector.get_columns('employees')
            column_names = [c['name'] for c in columns]
            print(f"\nEmployees table columns: {column_names}")
            
            # Try different queries
            print("\n=== Testing different queries ===")
            
            # Query 1: Get all employees
            all_employees = Employee.query.all()
            print(f"1. All employees: {len(all_employees)}")
            
            # Query 2: Filter by status='active' using filter_by
            active_by_filter_by = Employee.query.filter_by(status='active').all()
            print(f"2. Filter by status='active' (filter_by): {len(active_by_filter_by)}")
            
            # Query 3: Filter using filter()
            active_by_filter = Employee.query.filter(Employee.status == 'active').all()
            print(f"3. Filter by status='active' (filter): {len(active_by_filter)}")
            
            # Query 4: Filter by church_id and status
            church_active = Employee.query.filter(Employee.church_id == 1, Employee.status == 'active').all()
            print(f"4. Filter by church_id=1 and status='active': {len(church_active)}")
            
            # Show all employees with their status
            print("\n=== All employees with details ===")
            for emp in all_employees:
                print(f"   - {emp.first_name} {emp.last_name}: status='{emp.status}', pay_rate={emp.pay_rate}")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
