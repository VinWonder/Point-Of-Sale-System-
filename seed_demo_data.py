"""
Run this once after migrating to populate demo data for testing:
    python manage.py shell < seed_demo_data.py
"""
from accounts.models import User
from branches.models import Branch
from inventory.models import Product, Stock, Category
from customers.models import Customer

if not Branch.objects.exists():
    branch = Branch.objects.create(name="Main Branch", location="Nairobi CBD")
    branch2 = Branch.objects.create(name="Westlands Branch", location="Westlands")

    if not User.objects.filter(username="owner").exists():
        User.objects.create_superuser(
            username="owner", password="ChangeMe123!", role=User.Role.OWNER, branch=branch
        )
    if not User.objects.filter(username="cashier1").exists():
        User.objects.create_user(
            username="cashier1", password="ChangeMe123!", role=User.Role.CASHIER, branch=branch
        )

    cat = Category.objects.create(name="Fasteners")
    p1 = Product.objects.create(sku="NAIL-001", name="3 inch Nails (1kg)", category=cat, unit="kg", cost_price=100, sell_price=150, reorder_level=5)
    p2 = Product.objects.create(sku="CEM-050", name="Cement 50kg Bag", category=cat, unit="bag", cost_price=650, sell_price=780, reorder_level=10)
    Stock.objects.create(product=p1, branch=branch, quantity=50)
    Stock.objects.create(product=p2, branch=branch, quantity=30)

    Customer.objects.create(name="John Mwangi", phone_number="254700000001", credit_limit=5000)
    Customer.objects.create(name="Jane Wanjiru (test defaulter)", phone_number="254700000002", credit_limit=1000, balance_owed=2000)

    print("Demo data created. Login: owner / ChangeMe123! (or cashier1 / ChangeMe123!)")
else:
    print("Data already exists — skipping seed.")
