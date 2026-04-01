from app.routes.accounting_routes import accounting_bp

print("\n=== Accounting Blueprint Info ===\n")
print(f"Blueprint name: {accounting_bp.name}")
print(f"Blueprint import name: {accounting_bp.import_name}")
print(f"Blueprint url_prefix: {accounting_bp.url_prefix}")

# Check deferred functions (these are the routes)
if hasattr(accounting_bp, 'deferred_functions'):
    print(f"\nDeferred functions count: {len(accounting_bp.deferred_functions)}")
    for i, func in enumerate(accounting_bp.deferred_functions):
        if hasattr(func, '__name__'):
            print(f"  {i+1}. {func.__name__}")
        else:
            print(f"  {i+1}. {func}")
else:
    print("\nNo deferred functions found - routes may not be properly decorated")
    
# Try to get routes from the blueprint's record collection
if hasattr(accounting_bp, 'record'):
    print(f"\nRecord: {accounting_bp.record}")
