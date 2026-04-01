from app import create_app

app = create_app()

print("\n=== ACCOUNTING ROUTES ===\n")
with app.app_context():
    accounting_routes = []
    for rule in app.url_map.iter_rules():
        if 'accounting' in rule.rule:
            accounting_routes.append(f"{rule.endpoint}: {rule.rule}")
    
    if accounting_routes:
        for route in sorted(accounting_routes):
            print(route)
        print(f"\nTotal accounting routes: {len(accounting_routes)}")
    else:
        print("No accounting routes found!")
    
    print("\n=== ALL ROUTES (first 20) ===\n")
    all_routes = []
    for rule in app.url_map.iter_rules():
        all_routes.append(f"{rule.endpoint}: {rule.rule}")
    
    for route in sorted(all_routes)[:20]:
        print(route)
