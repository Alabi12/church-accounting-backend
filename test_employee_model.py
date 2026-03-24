from app import create_app, db
from app.models import Employee

app = create_app()
with app.app_context():
    print("Employee table columns:")
    for col in Employee.__table__.columns:
        print(f"  - {col.name}")
    
    print("\nAttempting to query employees...")
    try:
        employees = Employee.query.all()
        print(f"✅ Found {len(employees)} employees")
        for emp in employees:
            print(f"  - {emp.first_name} {emp.last_name}: code={emp.employee_code}, rate={emp.pay_rate}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
