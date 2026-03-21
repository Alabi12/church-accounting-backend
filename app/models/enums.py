# app/models/enums.py
from enum import Enum

class UserRole(str, Enum):
    SUPER_ADMIN = 'super_admin'
    ADMIN = 'admin'
    TREASURER = 'treasurer'
    ACCOUNTANT = 'accountant'
    AUDITOR = 'auditor'
    PASTOR = 'pastor'
    FINANCE_COMMITTEE = 'finance_committee'
    USER = 'user'

class Permission:
    # Income permissions
    VIEW_INCOME = 'view_income'
    CREATE_INCOME = 'create_income'
    EDIT_INCOME = 'edit_income'
    DELETE_INCOME = 'delete_income'
    
    # Expense permissions
    VIEW_EXPENSES = 'view_expenses'
    CREATE_EXPENSE = 'create_expense'
    EDIT_EXPENSE = 'edit_expense'
    DELETE_EXPENSE = 'delete_expense'
    APPROVE_EXPENSE = 'approve_expense'
    
    # Member permissions
    VIEW_MEMBERS = 'view_members'
    CREATE_MEMBER = 'create_member'
    EDIT_MEMBER = 'edit_member'
    DELETE_MEMBER = 'delete_member'
    
    # Budget permissions
    VIEW_BUDGET = 'view_budget'
    CREATE_BUDGET = 'create_budget'
    EDIT_BUDGET = 'edit_budget'
    DELETE_BUDGET = 'delete_budget'
    APPROVE_BUDGET = 'approve_budget'
    
    # Report permissions
    VIEW_REPORTS = 'view_reports'
    
    # Audit permissions
    VIEW_AUDIT_LOGS = 'view_audit_logs'
    
    # User permissions
    VIEW_USERS = 'view_users'
    MANAGE_USERS = 'manage_users'