# seed_chart.py
import os
import sys

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models import Church, Account
from app.models.chart_of_accounts import CHART_OF_ACCOUNTS
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def seed_chart_of_accounts(church_id, created_by=None):
    """Simplified seeding function"""
    created = []
    skipped = []
    errors = []
    
    for account_type, accounts in CHART_OF_ACCOUNTS.items():
        logger.info(f"Processing {account_type} accounts...")
        
        for account_data in accounts:
            try:
                existing = Account.query.filter_by(
                    church_id=church_id,
                    account_code=account_data['code']
                ).first()
                
                if existing:
                    skipped.append(account_data['code'])
                    continue
                
                account = Account(
                    church_id=church_id,
                    account_code=account_data['code'],
                    name=account_data['name'],
                    account_type=account_type,
                    category=account_data.get('category'),
                    sub_category=account_data.get('sub_category'),
                    normal_balance=account_data.get('normal_balance', 'debit'),
                    is_contra=account_data.get('is_contra', False),
                    level=1 if len(str(account_data['code'])) == 4 else 2,
                    created_by=created_by,
                    opening_balance=0,
                    current_balance=0
                )
                
                from app.extensions import db
                db.session.add(account)
                created.append(account_data['code'])
                
            except Exception as e:
                errors.append(f"{account_data['code']}: {str(e)}")
    
    from app.extensions import db
    db.session.commit()
    
    return {
        'created': created,
        'skipped': skipped,
        'errors': errors,
        'total_created': len(created),
        'total_skipped': len(skipped),
        'total_errors': len(errors)
    }

def get_or_create_default_church():
    """Get or create default church"""
    from app.extensions import db
    
    church = Church.query.first()
    if not church:
        church = Church(
            name='Default Church',
            address='123 Church Street',
            phone='+1234567890',
            email='church@example.com'
        )
        db.session.add(church)
        db.session.commit()
        print(f"Created default church: {church.name}")
    return church

if __name__ == '__main__':
    app = create_app('development')
    with app.app_context():
        church = get_or_create_default_church()
        result = seed_chart_of_accounts(church.id)
        
        print("\n" + "="*50)
        print("SEEDING COMPLETE")
        print("="*50)
        print(f"Created: {result['total_created']} accounts")
        print(f"Skipped: {result['total_skipped']} accounts (already exist)")
        
        if result['total_errors'] > 0:
            print(f"Errors: {result['total_errors']}")
            for error in result['errors']:
                print(f"  - {error}")
        
        if result['created']:
            print("\nCreated accounts:")
            for code in result['created'][:10]:
                account = Account.query.filter_by(account_code=code).first()
                if account:
                    print(f"  - {code}: {account.name}")
            if len(result['created']) > 10:
                print(f"  ... and {len(result['created']) - 10} more")
        
        print("\n✅ Chart of accounts seeded successfully!")