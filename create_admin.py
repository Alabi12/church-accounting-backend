# create_admin.py
import os
import sys
from app import create_app
from app.extensions import db
from app.models import User, Church, Role
from app.models.role_permission import RolePermission
from app.models.role import PermissionModel  # adjust if your Permission class lives elsewhere

# These are the permissions your app actually enforces.
# Keep this list in sync with the frontend's PermissionMatrix constants.
PREDEFINED_PERMISSIONS = [
    # (name, category, description)
    ('view_dashboard',           'Dashboard',  'View main dashboard'),
    ('view_income',              'Income',     'View income records'),
    ('create_income',            'Income',     'Create income entries'),
    ('edit_income',              'Income',     'Edit income records'),
    ('delete_income',            'Income',     'Delete income records'),
    ('view_expenses',            'Expenses',   'View expense records'),
    ('create_expenses',          'Expenses',   'Create expense entries'),
    ('edit_expenses',            'Expenses',   'Edit expense records'),
    ('delete_expenses',          'Expenses',   'Delete expense records'),
    ('approve_expenses',         'Expenses',   'Approve expense requests'),
    ('view_members',             'Members',    'View member records'),
    ('manage_members',           'Members',    'Add/edit/delete members'),
    ('view_reports',             'Reports',    'View financial reports'),
    ('manage_budgets',           'Budgets',    'Create/edit budgets'),
    ('approve_budgets',          'Budgets',    'Approve budget requests'),
    ('view_audit_logs',          'Admin',      'View audit logs'),
    ('manage_users',             'Admin',      'Manage system users'),
    ('manage_roles',             'Admin',      'Manage roles & permissions'),
    ('manage_settings',          'Admin',      'Manage system settings'),
    ('manage_church',            'Admin',      'Manage church settings'),
    ('backup_restore',           'Admin',      'Create/restore backups'),
    ('view_payroll',             'Payroll',    'View payroll records'),
    ('manage_payroll',           'Payroll',    'Run payroll & manage payslips'),
    ('approve_leave',            'Leave',      'Approve leave requests'),
    ('view_reconciliation',      'Accounting', 'View reconciliation data'),
    ('manage_reconciliation',    'Reconciliation', 'Perform reconciliation'),
]

# Which permissions each built-in role gets by default.
# super_admin gets everything (handled below), so leave it out here.
DEFAULT_ROLE_GRANTS = {
    'admin': [
        'view_dashboard', 'view_income', 'create_income', 'edit_income',
        'view_expenses', 'create_expenses', 'edit_expenses', 'approve_expenses',
        'view_members', 'manage_members', 'view_reports',
        'manage_budgets', 'approve_budgets',
        'view_audit_logs', 'manage_users', 'manage_roles', 'manage_settings',
        'manage_church', 'backup_restore',
        'view_payroll', 'manage_payroll',
        'approve_leave',
        'view_reconciliation', 'manage_reconciliation',
    ],
    'accountant': [
        'view_dashboard', 'view_income', 'create_income', 'edit_income',
        'view_expenses', 'create_expenses', 'edit_expenses',
        'view_members', 'view_reports',
        'view_payroll', 'manage_payroll',
        'view_reconciliation', 'manage_reconciliation',
    ],
    'treasurer': [
        'view_dashboard', 'view_income', 'view_expenses', 'approve_expenses',
        'view_reports', 'approve_budgets',
        'view_payroll', 'approve_leave',
        'view_reconciliation',
    ],
    'auditor': [
        'view_dashboard', 'view_income', 'view_expenses', 'view_reports',
        'view_audit_logs', 'view_reconciliation',
    ],
    'pastor': [
        'view_dashboard', 'view_income', 'view_expenses', 'view_members',
        'view_reports', 'approve_budgets', 'approve_expenses', 'approve_leave',
    ],
    'finance_committee': [
        'view_dashboard', 'view_income', 'view_expenses', 'view_reports',
        'approve_budgets', 'view_reconciliation',
    ],
    'user': [
        'view_dashboard',
    ],
}


def seed_roles():
    """Ensure all built-in roles exist."""
    roles = [
        'super_admin', 'admin', 'treasurer', 'accountant', 'auditor',
        'pastor', 'finance_committee', 'user',
    ]
    created = 0
    for role_name in roles:
        if not Role.query.filter_by(name=role_name).first():
            db.session.add(Role(
                name=role_name,
                description=f"{role_name.replace('_', ' ').title()} role",
            ))
            created += 1
    db.session.commit()
    if created:
        print(f"✅ Roles seeded ({created} new)")
    else:
        print("ℹ️  Roles already exist")


def seed_permissions():
    """Ensure all predefined permissions exist."""
    created = 0
    for name, category, description in PREDEFINED_PERMISSIONS:
        existing = PermissionModel.query.filter_by(name=name).first()
        if not existing:
            db.session.add(PermissionModel(
                name=name,
                category=category,
                description=description,
            ))
            created += 1
    db.session.commit()
    if created:
        print(f"✅ Permissions seeded ({created} new)")
    else:
        print("ℹ️  Permissions already exist")


def seed_role_grants():
    """Grant default permissions to each built-in role."""
    all_perms = {p.name: p for p in PermissionModel.query.all()}
    total_granted = 0

    # super_admin gets EVERYTHING
    super_admin = Role.query.filter_by(name='super_admin').first()
    if super_admin:
        for perm in all_perms.values():
            if not RolePermission.query.filter_by(
                role_id=super_admin.id, permission_id=perm.id
            ).first():
                db.session.add(RolePermission(
                    role_id=super_admin.id,
                    permission_id=perm.id,
                    granted=True,
                ))
                total_granted += 1

    # Other roles get their defaults
    for role_name, perm_names in DEFAULT_ROLE_GRANTS.items():
        role = Role.query.filter_by(name=role_name).first()
        if not role:
            continue
        for perm_name in perm_names:
            perm = all_perms.get(perm_name)
            if not perm:
                continue
            if not RolePermission.query.filter_by(
                role_id=role.id, permission_id=perm.id
            ).first():
                db.session.add(RolePermission(
                    role_id=role.id,
                    permission_id=perm.id,
                    granted=True,
                ))
                total_granted += 1

    db.session.commit()
    if total_granted:
        print(f"✅ Role grants seeded ({total_granted} new)")
    else:
        print("ℹ️  Role grants already exist")


def create_admin():
    """Create admin user in production database."""
    app = create_app('production')

    with app.app_context():
        print("🔧 Setting up admin user...")

        # ---- Church ----
        church = Church.query.first()
        if not church:
            church = Church(
                name='Default Church',
                email='church@example.com',
                phone='1234567890',
                address='123 Church Street',
            )
            db.session.add(church)
            db.session.commit()
            print("✅ Church created")
        else:
            print("ℹ️  Church already exists")

        # ---- Roles ----
        seed_roles()

        # ---- Permissions ----
        seed_permissions()

        # ---- Role → Permission grants ----
        seed_role_grants()

        # ---- Admin user ----
        admin = User.query.filter_by(email='admin@church.org').first()
        if not admin:
            admin = User(
                email='admin@church.org',
                username='admin',
                first_name='Admin',
                last_name='User',
                role='super_admin',
                church_id=church.id,
                is_active=True,
                is_verified=True,
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✅ Admin user created")
            print("   Email: admin@church.org")
            print("   Password: admin123")
        else:
            print("ℹ️  Admin user already exists")

        print("🎉 Setup complete!")


if __name__ == '__main__':
    create_admin()