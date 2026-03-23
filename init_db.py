from app import create_app, db
from sqlalchemy import inspect

print("íº€ Initializing database...")

app = create_app()
with app.app_context():
    # Create all tables
    db.create_all()
    print('âœ… Database created successfully')
    
    # List all tables
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print(f'í³Š Tables created: {len(tables)}')
    for table in tables[:10]:  # Show first 10 tables
        print(f'   - {table}')
    if len(tables) > 10:
        print(f'   ... and {len(tables) - 10} more')
    
    # Check if employees table exists
    if 'employees' in tables:
        print('âœ… Employees table created')
    else:
        print('âŒ Employees table missing')
    
    # Check if payroll tables exist
    payroll_tables = ['payroll_runs', 'payroll_lines']
    for pt in payroll_tables:
        if pt in tables:
            print(f'âœ… {pt} table created')
        else:
            print(f'âŒ {pt} table missing')
    
    # Check if leave tables exist
    leave_tables = ['leave_types', 'leave_requests', 'leave_balances']
    for lt in leave_tables:
        if lt in tables:
            print(f'âœ… {lt} table created')
        else:
            print(f'âŒ {lt} table missing')

print("\ní¾‰ Database initialization complete!")
