# app/seeders/leave_types.py
from app.models import db, LeaveType
from datetime import datetime

def seed_leave_types():
    """Seed default leave types"""
    
    leave_types = [
        {
            'name': 'Annual Leave',
            'code': 'ANNUAL',
            'description': 'Standard annual leave entitlement',
            'default_days': 22,
            'is_paid': True,
            'requires_approval': True
        },
        {
            'name': 'Sick Leave',
            'code': 'SICK',
            'description': 'Medical leave with doctor\'s note',
            'default_days': 12,
            'is_paid': True,
            'requires_approval': True
        },
        {
            'name': 'Maternity Leave',
            'code': 'MATERNITY',
            'description': 'Maternity leave for female employees',
            'default_days': 90,
            'is_paid': True,
            'requires_approval': True
        },
        {
            'name': 'Paternity Leave',
            'code': 'PATERNITY',
            'description': 'Paternity leave for new fathers',
            'default_days': 10,
            'is_paid': True,
            'requires_approval': True
        },
        {
            'name': 'Compassionate Leave',
            'code': 'COMPASSIONATE',
            'description': 'Leave for family emergencies',
            'default_days': 5,
            'is_paid': True,
            'requires_approval': True
        },
        {
            'name': 'Unpaid Leave',
            'code': 'UNPAID',
            'description': 'Leave without pay',
            'default_days': 0,
            'is_paid': False,
            'requires_approval': True
        },
        {
            'name': 'Study Leave',
            'code': 'STUDY',
            'description': 'Leave for educational purposes',
            'default_days': 10,
            'is_paid': True,
            'requires_approval': True
        }
    ]
    
    for lt in leave_types:
        existing = LeaveType.query.filter_by(code=lt['code']).first()
        if not existing:
            leave_type = LeaveType(**lt)
            db.session.add(leave_type)
    
    db.session.commit()
    print(f"✅ Seeded {len(leave_types)} leave types")