# app/scripts/seed_accounts.py
"""
Script to seed the database with the default Chart of Accounts
Run with: flask seed-accounts
"""
from app import create_app
from app.extensions import db
from app.models import Account, Church, User
from app.models.chart_of_accounts import CHART_OF_ACCOUNTS
from app.utils.account_classifier import AccountClassifier
import click
import traceback
from flask.cli import with_appcontext
import logging

logger = logging.getLogger(__name__)

def seed_chart_of_accounts(church_id, created_by=None):
    """
    Seed the chart of accounts for a specific church
    """
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
                
                # Determine if contra account
                is_contra = account_data.get('is_contra', False) or \
                            AccountClassifier.is_contra_account(
                                account_data['name'], 
                                account_data['code']
                            )
                
                # Determine level based on code length
                code_str = str(account_data['code'])
                level = 1 if len(code_str) == 4 else 2
                
                # Create account
                account = Account(
                    church_id=church_id,
                    account_code=account_data['code'],
                    name=account_data['name'],
                    display_name=account_data.get('display_name', account_data['name']),
                    account_type=account_type,
                    category=account_data.get('category'),
                    sub_category=account_data.get('sub_category'),
                    normal_balance=account_data.get('normal_balance', 
                                                    AccountClassifier.get_normal_balance(
                                                        account_type, is_contra
                                                    )),
                    is_contra=is_contra,
                    level=level,
                    description=account_data.get('description', ''),
                    is_active=True,
                    opening_balance=0,
                    current_balance=0,
                    created_by=created_by
                )
                
                db.session.add(account)
                created.append(account_data['code'])
                logger.debug(f"Created account: {account_data['code']} - {account_data['name']}")
                
            except Exception as e:
                errors.append(f"{account_data['code']}: {str(e)}")
                logger.error(f"Error creating account {account_data['code']}: {str(e)}")
    
    try:
        db.session.commit()
        logger.info(f"Successfully created {len(created)} accounts")
        
        # Set up parent-child relationships
        _setup_account_hierarchy(church_id)
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error committing accounts: {str(e)}")
        raise
    
    return {
        'created': created,
        'skipped': skipped,
        'errors': errors,
        'total_created': len(created),
        'total_skipped': len(skipped),
        'total_errors': len(errors)
    }


def _setup_account_hierarchy(church_id):
    """
    Set up parent-child relationships based on account codes
    """
    accounts = Account.query.filter_by(church_id=church_id).all()
    account_dict = {acc.account_code: acc for acc in accounts}
    
    for account in accounts:
        # Find parent based on code prefix
        code = str(account.account_code)
        if len(code) > 4:
            # Parent is the first 4 digits
            parent_code = code[:4]
            if parent_code in account_dict:
                account.parent_account_id = account_dict[parent_code].id
    
    db.session.commit()
    logger.info("Account hierarchy established")


def get_or_create_default_church():
    """Get or create a default church for seeding"""
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
        logger.info(f"Created default church: {church.name} (ID: {church.id})")
    return church


def get_default_admin():
    """Get the default admin user"""
    admin = User.query.filter_by(email='admin@church.org').first()
    if not admin:
        # Try to find any admin user
        admin = User.query.filter_by(role='super_admin').first()
    return admin


@click.command('seed-accounts')
@click.option('--church-id', type=int, help='Church ID to seed accounts for')
@click.option('--force', is_flag=True, help='Force seeding even if accounts exist')
@with_appcontext
def seed_accounts_command(church_id, force):
    """
    Seed the chart of accounts for a church
    """
    if church_id:
        church = Church.query.get(church_id)
        if not church:
            click.echo(f"Error: Church with ID {church_id} not found")
            return
    else:
        church = get_or_create_default_church()
        click.echo(f"Using default church: {church.name} (ID: {church.id})")
    
    # Check if accounts already exist
    existing_count = Account.query.filter_by(church_id=church.id).count()
    if existing_count > 0 and not force:
        click.echo(f"Warning: {existing_count} accounts already exist for this church.")
        click.echo("Use --force to seed anyway (will skip existing accounts)")
        if not click.confirm("Continue?"):
            return
    
    admin = get_default_admin()
    created_by = admin.id if admin else None
    
    click.echo(f"Seeding chart of accounts for {church.name}...")
    
    try:
        result = seed_chart_of_accounts(church.id, created_by)
        
        click.echo("\n" + "="*50)
        click.echo("SEEDING COMPLETE")
        click.echo("="*50)
        click.echo(f"Created: {result['total_created']} accounts")
        click.echo(f"Skipped: {result['total_skipped']} accounts (already exist)")
        
        if result['total_errors'] > 0:
            click.echo(f"Errors: {result['total_errors']}")
            for error in result['errors']:
                click.echo(f"  - {error}")
        
        if result['created']:
            click.echo("\nCreated accounts:")
            # Show first 10 created accounts
            for code in result['created'][:10]:
                click.echo(f"  - {code}")
            if len(result['created']) > 10:
                click.echo(f"  ... and {len(result['created']) - 10} more")
        
        click.echo("\n✅ Chart of accounts seeded successfully!")
        
    except Exception as e:
        click.echo(f"❌ Error seeding accounts: {str(e)}")
        logger.error(traceback.format_exc())


@click.command('list-accounts')
@click.option('--church-id', type=int, help='Church ID to list accounts for')
@click.option('--type', 'account_type', help='Filter by account type')
@with_appcontext
def list_accounts_command(church_id, account_type):
    """
    List all accounts for a church
    """
    if church_id:
        church = Church.query.get(church_id)
        if not church:
            click.echo(f"Error: Church with ID {church_id} not found")
            return
    else:
        church = get_or_create_default_church()
    
    query = Account.query.filter_by(church_id=church.id)
    
    if account_type:
        query = query.filter_by(account_type=account_type.upper())
    
    accounts = query.order_by(Account.account_code).all()
    
    if not accounts:
        click.echo(f"No accounts found for {church.name}")
        return
    
    click.echo(f"\nChart of Accounts for {church.name}")
    click.echo("="*70)
    click.echo(f"{'Code':<8} {'Type':<10} {'Name':<40} {'Balance':>12}")
    click.echo("-"*70)
    
    for acc in accounts:
        click.echo(f"{acc.account_code:<8} {acc.account_type:<10} {acc.name[:40]:<40} {acc.current_balance:>12,.2f}")
    
    click.echo("="*70)
    click.echo(f"Total accounts: {len(accounts)}")


@click.command('delete-accounts')
@click.option('--church-id', type=int, required=True, help='Church ID to delete accounts for')
@click.option('--force', is_flag=True, help='Force deletion without confirmation')
@with_appcontext
def delete_accounts_command(church_id, force):
    """
    Delete all accounts for a church (USE WITH CAUTION)
    """
    church = Church.query.get(church_id)
    if not church:
        click.echo(f"Error: Church with ID {church_id} not found")
        return
    
    count = Account.query.filter_by(church_id=church_id).count()
    
    if count == 0:
        click.echo(f"No accounts found for {church.name}")
        return
    
    if not force:
        click.echo(f"WARNING: You are about to delete {count} accounts for {church.name}")
        click.echo("This action cannot be undone!")
        if not click.confirm("Are you sure you want to continue?"):
            return
    
    try:
        Account.query.filter_by(church_id=church_id).delete()
        db.session.commit()
        click.echo(f"✅ Deleted {count} accounts for {church.name}")
    except Exception as e:
        db.session.rollback()
        click.echo(f"❌ Error deleting accounts: {str(e)}")


def register_commands(app):
    """
    Register CLI commands with the Flask app
    """
    app.cli.add_command(seed_accounts_command)
    app.cli.add_command(list_accounts_command)
    app.cli.add_command(delete_accounts_command)


# For running as standalone script
if __name__ == '__main__':
    app = create_app('development')
    with app.app_context():
        church = get_or_create_default_church()
        result = seed_chart_of_accounts(church.id)
        print(f"Created: {len(result['created'])} accounts")
        print(f"Skipped: {len(result['skipped'])} accounts")
        if result['errors']:
            print(f"Errors: {len(result['errors'])}")
            for error in result['errors']:
                print(f"  - {error}")