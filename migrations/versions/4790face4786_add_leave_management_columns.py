"""Add leave management columns

Revision ID: 4790face4786
Revises:
Create Date: 2026-03-31 22:13:58.179884

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = '4790face4786'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to leave_requests table
    with op.batch_alter_table('leave_requests', schema=None) as batch_op:
        # Add new columns
        batch_op.add_column(sa.Column('admin_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('admin_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('admin_comments', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('pastor_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('pastor_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('pastor_comments', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('accountant_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('accountant_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('accountant_comments', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('treasurer_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('treasurer_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('treasurer_comments', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('posted_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('posted_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('posted_to_ledger', sa.Boolean(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('journal_entry_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('allowance_processed', sa.Boolean(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('allowance_processed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('allowance_amount', sa.Numeric(15, 2), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('allowance_approved', sa.Boolean(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('allowance_approved_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('allowance_approved_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('payroll_run_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('rejected_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('rejected_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('rejection_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('rejection_stage', sa.String(length=50), nullable=True))
        
        # Modify status column length
        batch_op.alter_column('status',
               existing_type=sa.VARCHAR(length=20),
               type_=sa.String(length=50),
               existing_nullable=True)
        
        # Try to drop foreign keys - skip if they don't exist
        # Using try/except because SQLite handles constraints differently
        try:
            batch_op.drop_constraint('fk_leave_requests_recommended_by', type_='foreignkey')
        except:
            pass
        
        try:
            batch_op.drop_constraint('fk_leave_requests_approved_by', type_='foreignkey')
        except:
            pass
        
        try:
            batch_op.drop_constraint('fk_leave_requests_returned_by', type_='foreignkey')
        except:
            pass
        
        try:
            batch_op.drop_constraint('fk_leave_requests_reviewed_by', type_='foreignkey')
        except:
            pass
        
        # Create new foreign keys
        batch_op.create_foreign_key('fk_leave_requests_allowance_approved_by', 'users', ['allowance_approved_by'], ['id'])
        batch_op.create_foreign_key('fk_leave_requests_treasurer_id', 'users', ['treasurer_id'], ['id'])
        batch_op.create_foreign_key('fk_leave_requests_journal_entry_id', 'journal_entries', ['journal_entry_id'], ['id'])
        batch_op.create_foreign_key('fk_leave_requests_admin_id', 'users', ['admin_id'], ['id'])
        batch_op.create_foreign_key('fk_leave_requests_accountant_id', 'users', ['accountant_id'], ['id'])
        batch_op.create_foreign_key('fk_leave_requests_pastor_id', 'users', ['pastor_id'], ['id'])
        batch_op.create_foreign_key('fk_leave_requests_posted_by', 'users', ['posted_by'], ['id'])
        batch_op.create_foreign_key('fk_leave_requests_rejected_by', 'users', ['rejected_by'], ['id'])
        batch_op.create_foreign_key('fk_leave_requests_payroll_run_id', 'payroll_runs', ['payroll_run_id'], ['id'])
        
        # Drop old columns
        columns_to_drop = [
            'approved_by', 'review_comments', 'approval_comments', 'reviewed_by',
            'recommendation_comments', 'return_reason', 'approved_at', 'recommended_by',
            'returned_by', 'recommendation', 'returned_at', 'recommended_at', 'reviewed_at'
        ]
        
        for col in columns_to_drop:
            try:
                batch_op.drop_column(col)
            except:
                pass

    # Add columns to leave_types table
    with op.batch_alter_table('leave_types', schema=None) as batch_op:
        batch_op.add_column(sa.Column('allowance_rate', sa.Numeric(precision=5, scale=2), nullable=True))
        batch_op.add_column(sa.Column('allowance_type', sa.String(length=20), server_default='percentage', nullable=True))


def downgrade():
    # This is a complex downgrade - raising NotImplementedError is safer
    raise NotImplementedError("Downgrade is not implemented for this migration")