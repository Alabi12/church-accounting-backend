# app/scripts/seed_accounts.py
"""
Seed script for chart of accounts
"""
from app import create_app
from app.models import Account, Church
from app.extensions import db
from app.models.chart_of_accounts import CHART_OF_ACCOUNTS
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def seed_chart_of_accounts(church_id):
    """Seed the chart of accounts"""
    created = []
    skipped = []
    errors = []
    
    for account_type, accounts in CHART_OF_ACCOUNTS.items():
        logger.info(f"Processing {account_type} accounts...")
        
        for account_data in accounts:
            try:
                # Check if account already exists
                existing = Account.query.filter_by(
                    church_id=church_id,
                    account_code=account_data['code']
                ).first()
                
                if existing:
                    skipped.append(account_data['code'])
                    continue
                
                # Create account (without display_name if your model doesn't have it)
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
                    opening_balance=0,
                    current_balance=0,
                    description=account_data.get('description', '')
                )
                
                db.session.add(account)
                created.append(account_data['code'])
                
            except Exception as e:
                errors.append(f"{account_data['code']}: {str(e)}")
                logger.error(f"Error creating {account_data['code']}: {str(e)}")
    
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
        logger.info(f"Created default church: {church.name}")
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
            print("\n✅ Chart of accounts seeded successfully!")
