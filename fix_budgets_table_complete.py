# fix_budgets_table_complete.py
import sqlite3
import os
import shutil

def add_missing_columns():
    db_path = 'instance/app.db'
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        print("Available databases:")
        os.system("find . -name '*.db' -type f")
        return
    
    print(f"Found database at: {db_path}")
    
    # Backup the database first
    backup_path = f"{db_path}.backup"
    print(f"Creating backup at: {backup_path}")
    shutil.copy2(db_path, backup_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get existing columns
    cursor.execute("PRAGMA table_info(budgets)")
    existing_columns = [column[1] for column in cursor.fetchall()]
    
    print(f"\nExisting columns in budgets table: {existing_columns}")
    print(f"Total columns found: {len(existing_columns)}")
    
    # All columns that should exist based on your Budget model
    all_required_columns = {
        'period': 'VARCHAR(20) DEFAULT "annual"',
        'account_id': 'INTEGER',
        'account_code': 'VARCHAR(20)',
        'actual_amount': 'NUMERIC(15,2) DEFAULT 0',
        'variance': 'NUMERIC(15,2) DEFAULT 0',
        'variance_percentage': 'NUMERIC(5,2) DEFAULT 0',
        'budget_type': 'VARCHAR(20) DEFAULT "EXPENSE"',
        'january': 'NUMERIC(15,2) DEFAULT 0',
        'february': 'NUMERIC(15,2) DEFAULT 0',
        'march': 'NUMERIC(15,2) DEFAULT 0',
        'april': 'NUMERIC(15,2) DEFAULT 0',
        'may': 'NUMERIC(15,2) DEFAULT 0',
        'june': 'NUMERIC(15,2) DEFAULT 0',
        'july': 'NUMERIC(15,2) DEFAULT 0',
        'august': 'NUMERIC(15,2) DEFAULT 0',
        'september': 'NUMERIC(15,2) DEFAULT 0',
        'october': 'NUMERIC(15,2) DEFAULT 0',
        'november': 'NUMERIC(15,2) DEFAULT 0',
        'december': 'NUMERIC(15,2) DEFAULT 0',
        'created_by': 'INTEGER',
        'submitted_by': 'INTEGER',
        'approved_by': 'INTEGER',
        'rejected_by': 'INTEGER',
        'submitted_at': 'DATETIME',
        'approved_at': 'DATETIME',
        'rejected_at': 'DATETIME',
        'rejection_reason': 'TEXT'
    }
    
    # Add missing columns
    columns_added = []
    for column, data_type in all_required_columns.items():
        if column not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE budgets ADD COLUMN {column} {data_type}")
                print(f"✅ Added column: {column} ({data_type})")
                columns_added.append(column)
            except Exception as e:
                print(f"❌ Error adding {column}: {e}")
    
    conn.commit()
    
    # Verify the columns after update
    cursor.execute("PRAGMA table_info(budgets)")
    updated_columns = [column[1] for column in cursor.fetchall()]
    print(f"\nUpdated columns count: {len(updated_columns)}")
    if columns_added:
        print(f"Columns added: {columns_added}")
    
    # Check if any columns are still missing
    missing = set(all_required_columns.keys()) - set(updated_columns)
    if missing:
        print(f"\n⚠️ Still missing columns: {missing}")
    else:
        print("\n✅ All required columns are present!")
    
    conn.close()
    print(f"\n✅ Database update completed! Backup saved at: {backup_path}")

if __name__ == "__main__":
    add_missing_columns()