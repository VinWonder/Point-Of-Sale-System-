"""
Load a realistic demo hardware shop: branches, staff, a catalogue with
stock, suppliers, customers and a month of sales history created through
the real checkout service (so stock, ledgers and balances all agree).

    python manage.py seed_demo            # only if the database is empty
    python manage.py seed_demo --force    # add demo data even if some exists
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from branches.models import Branch
from core.models import ShopSettings
from customers.models import Customer
from customers.services import record_debt_payment
from inventory.models import Category, Product, StockMovement, Supplier, SupplierPurchase
from inventory.services import adjust_stock
from registers.models import Expense
from sales.models import Sale
from sales.services import SaleError, checkout

DEMO_PASSWORD = 'ChangeMe123!'

# (category, sku, name, brand, unit, cost, retail, wholesale, wholesale_from, reorder, opening stock)
CATALOGUE = [
    ('Cement & Building', 'CEM-BAM-50', 'Bamburi Tembo Cement 50kg', 'Bamburi', 'bag', 680, 780, 750, 20, 40, 300),
    ('Cement & Building', 'CEM-SIM-50', 'Simba Cement 50kg', 'Simba', 'bag', 650, 750, 720, 20, 40, 250),
    ('Cement & Building', 'SND-RVR-T', 'River Sand (per tonne)', '', 'tonne', 1800, 2500, None, 0, 5, 30),
    ('Cement & Building', 'BAL-30', 'Ballast 3/4" (per tonne)', '', 'tonne', 2000, 2800, None, 0, 5, 25),
    ('Cement & Building', 'LIM-25', 'Hydrated Lime 25kg', 'Athi River', 'bag', 420, 550, None, 0, 10, 60),
    ('Steel & Iron', 'Y12-12M', 'Steel Bar Y12 x 12m', 'Devki', 'pcs', 980, 1150, 1100, 50, 50, 400),
    ('Steel & Iron', 'Y10-12M', 'Steel Bar Y10 x 12m', 'Devki', 'pcs', 690, 820, 790, 50, 50, 400),
    ('Steel & Iron', 'BRC-A142', 'BRC Mesh A142 (2.4x4.8m)', 'Insteel', 'sheet', 3900, 4600, None, 0, 10, 40),
    ('Steel & Iron', 'BND-WIRE', 'Binding Wire 25kg', '', 'roll', 3200, 3800, None, 0, 5, 20),
    ('Roofing', 'IRS-G30-3M', 'Iron Sheet G30 Box Profile 3m', 'Mabati Rolling Mills', 'sheet', 1050, 1250, 1180, 30, 30, 200),
    ('Roofing', 'IRS-G28-3M', 'Iron Sheet G28 Corrugated 3m', 'Mabati Rolling Mills', 'sheet', 1200, 1450, 1380, 30, 30, 150),
    ('Roofing', 'RDG-3M', 'Ridge Cap 3m', 'Mabati Rolling Mills', 'pcs', 650, 850, None, 0, 10, 60),
    ('Roofing', 'RFN-UMB', 'Roofing Nails Umbrella 1kg', '', 'kg', 230, 320, None, 0, 10, 80),
    ('Fasteners', 'NAIL-3IN', 'Wire Nails 3" (1kg)', '', 'kg', 140, 200, 180, 25, 20, 200),
    ('Fasteners', 'NAIL-4IN', 'Wire Nails 4" (1kg)', '', 'kg', 140, 200, 180, 25, 20, 180),
    ('Fasteners', 'NAIL-2IN', 'Wire Nails 2" (1kg)', '', 'kg', 150, 210, 190, 25, 20, 150),
    ('Fasteners', 'SCR-WD-100', 'Wood Screws 1.5" (box of 100)', 'Fischer', 'box', 180, 280, None, 0, 10, 60),
    ('Fasteners', 'BLT-M12', 'Hex Bolt & Nut M12 x 100mm', '', 'pcs', 35, 60, 50, 100, 50, 500),
    ('Paint', 'PNT-CRN-W4', 'Crown Silk Vinyl White 4L', 'Crown', 'tin', 1550, 1950, None, 0, 10, 50),
    ('Paint', 'PNT-CRN-W20', 'Crown Silk Vinyl White 20L', 'Crown', 'bucket', 6900, 8200, None, 0, 4, 15),
    ('Paint', 'PNT-BAS-GL4', 'Basco Gloss Enamel 4L', 'Basco', 'tin', 1700, 2150, None, 0, 6, 30),
    ('Paint', 'PNT-THN-1', 'Paint Thinner 1L', 'Sadolin', 'bottle', 280, 400, None, 0, 10, 40),
    ('Paint', 'BRS-4IN', 'Paint Brush 4"', 'Harris', 'pcs', 180, 300, None, 0, 10, 50),
    ('Plumbing', 'PVC-4IN-6M', 'PVC Pipe 4" Class B x 6m', 'Kentpipes', 'pcs', 1650, 2100, 1980, 10, 10, 80),
    ('Plumbing', 'PPR-25-4M', 'PPR Pipe 25mm x 4m', 'Pipelife', 'pcs', 380, 520, None, 0, 20, 120),
    ('Plumbing', 'ELB-PPR25', 'PPR Elbow 25mm', 'Pipelife', 'pcs', 25, 50, 40, 50, 50, 400),
    ('Plumbing', 'TAP-BIB-HALF', 'Bib Tap 1/2" Brass', 'Pegler', 'pcs', 650, 950, None, 0, 10, 40),
    ('Plumbing', 'TNK-1000', 'Water Tank 1000L', 'Roto', 'pcs', 9800, 11800, None, 0, 2, 8),
    ('Plumbing', 'SOL-PVC-250', 'PVC Solvent Cement 250ml', 'Tangit', 'tin', 380, 550, None, 0, 10, 40),
    ('Electrical', 'CBL-2.5-100', 'Twin & Earth Cable 2.5mm (100m)', 'East African Cables', 'roll', 8200, 9800, None, 0, 3, 15),
    ('Electrical', 'CBL-1.5-100', 'Twin & Earth Cable 1.5mm (100m)', 'East African Cables', 'roll', 5600, 6800, None, 0, 3, 15),
    ('Electrical', 'SKT-13A', 'Twin Socket 13A', 'Tronic', 'pcs', 280, 420, 380, 20, 20, 120),
    ('Electrical', 'SWT-1G', 'Light Switch 1-Gang', 'Tronic', 'pcs', 110, 180, 160, 20, 20, 150),
    ('Electrical', 'BLB-LED-9W', 'LED Bulb 9W B22', 'Philips', 'pcs', 140, 250, 220, 24, 30, 200),
    ('Tools', 'HMR-CLW-16', 'Claw Hammer 16oz', 'Stanley', 'pcs', 650, 950, None, 0, 5, 25),
    ('Tools', 'TPE-5M', 'Measuring Tape 5m', 'Stanley', 'pcs', 380, 600, None, 0, 10, 40),
    ('Tools', 'SPD-RND', 'Round-Point Spade', 'Crocodile', 'pcs', 520, 750, None, 0, 10, 40),
    ('Tools', 'WHB-SGL', 'Wheelbarrow Heavy Duty', 'Crocodile', 'pcs', 4200, 5500, None, 0, 3, 12),
    ('Tools', 'TRW-BRK', 'Brick Trowel 10"', 'Bellota', 'pcs', 350, 550, None, 0, 10, 30),
    ('Timber', 'TMB-2X4-12', 'Cypress Timber 2x4 x 12ft', '', 'pcs', 420, 560, 520, 50, 50, 300),
    ('Timber', 'TMB-2X2-12', 'Cypress Timber 2x2 x 12ft', '', 'pcs', 210, 290, 270, 50, 50, 300),
    ('Timber', 'PLY-18MM', 'Plywood 18mm 8x4', '', 'sheet', 3100, 3800, None, 0, 5, 30),
]

SUPPLIERS = [
    ('Bamburi Cement PLC', 'Grace Achieng', '0711000101'),
    ('Devki Steel Mills', 'Raj Patel', '0722000202'),
    ('Mabati Rolling Mills', 'Peter Kamau', '0733000303'),
    ('Crown Paints Kenya', 'Mercy Wanjiku', '0744000404'),
    ('Kentpipes Ltd', 'Hassan Ali', '0755000505'),
    ('Nairobi Timber Yard', 'Joseph Mutua', '0766000606'),
]

CUSTOMERS = [
    ('John Mwangi', 'CONTRACTOR', '254700000001', 50000, 0),
    ('Jane Wanjiru (test defaulter)', 'RETAIL', '254700000002', 1000, 2000),
    ('Otieno Construction Ltd', 'COMPANY', '254700000003', 300000, 0),
    ('Fundi Kip (Plumber)', 'CONTRACTOR', '254700000004', 20000, 0),
    ('Mama Njeri', 'RETAIL', '254700000005', 0, 0),
    ('St. Mary\'s School', 'COMPANY', '254700000006', 150000, 0),
    ('Wekesa Electricals', 'CONTRACTOR', '254700000007', 40000, 0),
]


class Command(BaseCommand):
    help = 'Load a realistic demo hardware shop with a month of sales history.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Seed even if data already exists')
        parser.add_argument('--days', type=int, default=30, help='Days of sales history to generate')

    def handle(self, *args, **options):
        if Product.objects.exists() and not options['force']:
            self.stdout.write(self.style.WARNING(
                'Products already exist — skipping. Use --force to add demo data anyway.'))
            return
        random.seed(42)
        with transaction.atomic():
            self.seed(options['days'])
        self.stdout.write(self.style.SUCCESS(
            f'Demo shop ready. Logins (password {DEMO_PASSWORD}): owner, manager, cashier1, cashier2. '
            'Change these passwords before real use.'))

    def seed(self, days):
        settings = ShopSettings.load()
        settings.business_name = 'Jenga Hardware'
        settings.tagline = 'Building materials · Tools · Plumbing · Electrical'
        settings.kra_pin = 'P051234567X'
        settings.phone_number = '0700 123 456'
        settings.address = 'Moi Avenue, Nairobi'
        settings.save()

        main, _ = Branch.objects.get_or_create(name='Main Branch', defaults={'location': 'Nairobi CBD', 'phone_number': '0700123456'})
        west, _ = Branch.objects.get_or_create(name='Westlands Branch', defaults={'location': 'Westlands', 'phone_number': '0700654321'})

        users = {}
        for username, role, branch, first in [
            ('owner', User.Role.OWNER, main, 'Wanjiku'), ('manager', User.Role.MANAGER, main, 'Brian'),
            ('cashier1', User.Role.CASHIER, main, 'Aisha'), ('cashier2', User.Role.CASHIER, west, 'Kevin'),
        ]:
            user = User.objects.filter(username=username).first()
            if user is None:
                create = User.objects.create_superuser if role == User.Role.OWNER else User.objects.create_user
                user = create(username=username, password=DEMO_PASSWORD, role=role, branch=branch, first_name=first)
            users[username] = user
        owner = users['owner']

        suppliers = [
            Supplier.objects.get_or_create(name=n, defaults={'contact_person': c, 'phone_number': p})[0]
            for n, c, p in SUPPLIERS
        ]
        products = []
        for cat, sku, name, brand, unit, cost, retail, wholesale, w_from, reorder, opening in CATALOGUE:
            category, _ = Category.objects.get_or_create(name=cat)
            product, created = Product.objects.get_or_create(sku=sku, defaults=dict(
                name=name, brand=brand, unit=unit, category=category, cost_price=cost, sell_price=retail,
                wholesale_price=wholesale, wholesale_min_qty=w_from, reorder_level=reorder,
            ))
            products.append(product)
            if created:
                for branch, share in ((main, 1.0), (west, 0.5)):
                    qty = int(opening * share)
                    supplier = random.choice(suppliers)
                    purchase = SupplierPurchase.objects.create(
                        supplier=supplier, product=product, branch=branch, quantity=qty,
                        cost_price=cost, is_paid=random.random() > 0.15, created_by=owner,
                        invoice_number=f'INV-{random.randint(1000, 9999)}',
                    )
                    adjust_stock(product, branch, qty, StockMovement.Kind.PURCHASE, user=owner,
                                 reference=f'Purchase #{purchase.pk}', note=f'From {supplier}')

        customers = []
        for name, ctype, phone, limit, opening in CUSTOMERS:
            customer, _ = Customer.objects.get_or_create(phone_number=phone, defaults=dict(
                name=name, customer_type=ctype, credit_limit=limit, balance_owed=opening,
            ))
            customers.append(customer)
        account_customers = [c for c in customers if c.credit_limit and not c.is_defaulter]

        self.generate_history(days, [main, west], users, products, account_customers, owner)
        self.generate_documents(users, products, account_customers)

    def generate_history(self, days, branches, users, products, account_customers, owner):
        now = timezone.now()
        cashiers = {branches[0]: [users['cashier1'], users['manager']], branches[1]: [users['cashier2']]}
        sale_count = 0
        for day_offset in range(days, -1, -1):
            day = now - timedelta(days=day_offset)
            busy = 1.4 if day.weekday() == 5 else (0.4 if day.weekday() == 6 else 1.0)
            for branch in branches:
                for _ in range(int(random.randint(4, 9) * busy * (1 if branch == branches[0] else 0.6))):
                    lines = [{'product_id': p.pk, 'qty': random.choice([1, 1, 2, 3, 5, 10, 25])}
                             for p in random.sample(products, random.randint(1, 4))]
                    method = random.choices(['CASH', 'MPESA_PAID', 'CARD', 'CREDIT'], weights=[45, 40, 5, 10])[0]
                    customer = random.choice(account_customers) if method == 'CREDIT' else None
                    try:
                        sale = checkout(
                            user=random.choice(cashiers[branch]), branch=branch, raw_items=lines,
                            customer=customer, payment_method='CARD' if method == 'MPESA_PAID' else method,
                        )
                    except SaleError:
                        continue
                    if method == 'MPESA_PAID':
                        sale.payments.update(method='MPESA', mpesa_receipt_number=f'S{random.randint(10**8, 10**9)}')
                    stamp = day.replace(hour=random.randint(7, 18), minute=random.randint(0, 59))
                    Sale.objects.filter(pk=sale.pk).update(created_at=stamp)
                    sale.payments.update(created_at=stamp)
                    sale_count += 1
            if day_offset % 7 == 0:
                for branch in branches:
                    expense = Expense.objects.create(branch=branch, category='LOADING', description='Offloading delivery lorry',
                                                     amount=random.choice([500, 800, 1200]), recorded_by=owner)
                    Expense.objects.filter(pk=expense.pk).update(created_at=day)
        for customer in account_customers[:2]:
            customer.refresh_from_db()
            if customer.balance_owed > 1000:
                record_debt_payment(customer, (customer.balance_owed / 2).quantize(Decimal('1')), owner,
                                    method='MPESA', reference='QDEMO12345')
        self.stdout.write(f'Generated {sale_count} historical sales.')

    def generate_documents(self, users, products, account_customers):
        """Quotations and invoices in every state, so the documents and dashboard look lived-in."""
        from sales.invoices import create_invoice
        from sales.models import Quotation
        from sales.quotations import save_quotation

        now = timezone.now()
        today = timezone.localdate()
        # A month of credit sales has used up most limits; give account customers room for new invoices.
        for customer in account_customers:
            customer.refresh_from_db()
            customer.credit_limit = customer.balance_owed + Decimal('150000')
            customer.save(update_fields=['credit_limit'])
        walk_ins = [('Mzee Otieno', '0722410233'), ('Mama Akinyi', '0711502876'), ('Kamau Builders', '0733190455'),
                    ('Fundi Joseph', '0700678120'), ('Wanjiru Hardware Agent', '0745003311')]

        def lines(n, branch):
            """Items actually in stock at the branch, in quantities it can supply."""
            from inventory.models import Stock
            stock = dict(Stock.objects.filter(branch=branch, quantity__gte=6).values_list('product_id', 'quantity'))
            pool = [p for p in products if p.pk in stock]
            return [{'product_id': p.pk, 'qty': min(random.choice([2, 5, 10, 20]), stock[p.pk] // 3)}
                    for p in random.sample(pool, min(n, len(pool)))]

        quotes = []
        for i in range(10):
            user = random.choice([users['cashier1'], users['manager'], users['cashier2']])
            name, phone = random.choice(walk_ins)
            customer = random.choice(account_customers) if i % 3 == 0 else None
            try:
                q = save_quotation(user=user, raw_items=lines(random.randint(2, 5), user.branch), customer=customer,
                                   customer_name='' if customer else name, customer_phone='' if customer else phone)
            except SaleError as exc:
                self.stdout.write(f'  skipped a quotation: {exc}')
                continue
            age = random.randint(0, 12)
            Quotation.objects.filter(pk=q.pk).update(created_at=now - timedelta(days=age, hours=random.randint(0, 8)),
                                                     valid_until=today - timedelta(days=age) + timedelta(days=14))
            quotes.append(q)
        # A few quotes go stale, a few are accepted and invoiced.
        for q in quotes[:2]:
            Quotation.objects.filter(pk=q.pk).update(valid_until=today - timedelta(days=3))
        for q in quotes[2:4]:
            Quotation.objects.filter(pk=q.pk).update(valid_until=today + timedelta(days=2))
        for q in quotes[4:7]:
            q.refresh_from_db()
            try:
                sale = create_invoice(
                    user=q.created_by, payment_method='CREDIT' if q.customer else 'CASH', customer=q.customer,
                    customer_name=q.customer_name, customer_phone=q.customer_phone, quotation=q,
                    raw_items=[{'product_id': i.product_id, 'qty': i.quantity, 'unit_price': str(i.unit_price)}
                               for i in q.items.all()],
                )
            except SaleError as exc:
                self.stdout.write(f'  skipped invoicing {q.reference}: {exc}')
                continue
            Quotation.objects.filter(pk=q.pk).update(status=Quotation.Status.CONVERTED)

        # Invoices on account: some current, some overdue, one paid.
        invoices = []
        for customer in account_customers:
            try:
                invoices.append(create_invoice(user=users['manager'], payment_method='CREDIT', customer=customer,
                                               raw_items=lines(2, users['manager'].branch), due_days=random.choice([14, 30])))
            except SaleError as exc:
                self.stdout.write(f'  skipped an invoice for {customer}: {exc}')
                continue
        for sale in invoices[:2]:
            Sale.objects.filter(pk=sale.pk).update(
                created_at=now - timedelta(days=40), due_date=today - timedelta(days=random.randint(3, 10)))
        if len(invoices) > 2:
            paid = invoices[2]
            paid.refresh_from_db()
            record_debt_payment(paid.customer, paid.balance_due, users['owner'], method='MPESA', reference='QPAID7781')
        self.stdout.write(f'Generated {len(quotes)} quotations and {len(invoices)} invoices.')
