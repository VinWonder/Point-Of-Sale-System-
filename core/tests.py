import io
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.models import Customer
from inventory.models import Product, Stock
from sales.models import Quotation, Sale
from .models import ShopSettings
from .templatetags.pos_tags import money


class MoneyFilterTests(TestCase):
    def test_formats(self):
        self.assertEqual(money(Decimal('12500')), 'KES 12,500.00')
        self.assertEqual(money(-50), '-KES 50.00')
        self.assertEqual(money(None), 'KES 0.00')
        self.assertEqual(money('abc'), 'abc')


class ShopSettingsTests(TestCase):
    def test_singleton(self):
        ShopSettings.load()
        ShopSettings(business_name='Other').save()
        self.assertEqual(ShopSettings.objects.count(), 1)
        self.assertEqual(ShopSettings.load().business_name, 'Other')


class SiteSmokeTests(TestCase):
    """Seed a demo shop, then open every page as each role. Nothing may error."""

    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo', days=3, stdout=io.StringIO())

    def pages(self):
        sale = Sale.objects.first()
        customer = Customer.objects.first()
        product = Product.objects.first()
        quotation = Quotation.objects.create(branch=sale.branch, created_by=User.objects.get(username='owner'))
        return [
            reverse('dashboard:index'), reverse('sales:pos'), reverse('sales:sale_list'),
            reverse('sales:sale_export'), reverse('sales:quotation_list'),
            reverse('sales:quotation', args=[quotation.pk]), reverse('sales:receipt', args=[sale.pk]),
            reverse('sales:sale_return', args=[sale.pk]),
            reverse('customers:customer_list'), reverse('customers:customer_create'),
            reverse('customers:customer_detail', args=[customer.pk]),
            reverse('customers:customer_edit', args=[customer.pk]),
            reverse('inventory:product_list'), reverse('inventory:product_detail', args=[product.pk]),
            reverse('inventory:product_create'), reverse('inventory:product_edit', args=[product.pk]),
            reverse('inventory:stock_list'), reverse('inventory:stock_adjust'),
            reverse('inventory:supplier_purchase_create'), reverse('inventory:purchase_list'),
            reverse('inventory:supplier_list'), reverse('inventory:category_list'),
            reverse('inventory:product_import'), reverse('inventory:product_export'),
            reverse('inventory:shelf_labels'),
            reverse('branches:branch_list'), reverse('branches:transfer_list'),
            reverse('branches:transfer_create'),
            reverse('registers:my_shift'), reverse('registers:shift_list'), reverse('registers:expense_list'),
            reverse('reports:index'), reverse('reports:profit_and_loss'), reverse('reports:product_sales'),
            reverse('reports:staff_performance'), reverse('reports:debt_aging'), reverse('reports:reorder'),
            reverse('reports:vat'),
            reverse('accounts:staff_list'), reverse('accounts:staff_create'), reverse('accounts:audit_log'),
            reverse('accounts:change_password'), reverse('core:settings'),
        ]

    def test_every_page_for_every_role(self):
        pages = self.pages()
        for username in ('owner', 'manager', 'cashier1'):
            self.client.force_login(User.objects.get(username=username))
            for url in pages:
                with self.subTest(user=username, url=url):
                    status = self.client.get(url).status_code
                    self.assertIn(status, (200, 403), f'{url} returned {status}')

    def test_cashier_locked_out_of_management(self):
        self.client.force_login(User.objects.get(username='cashier1'))
        for name in ('reports:index', 'accounts:staff_list', 'core:settings', 'accounts:audit_log',
                     'inventory:stock_adjust', 'inventory:product_import'):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_anonymous_redirected_to_login(self):
        res = self.client.get(reverse('dashboard:index'))
        self.assertRedirects(res, f"{reverse('login')}?next=/")

    def test_seed_data_is_consistent(self):
        self.assertFalse(Stock.objects.filter(quantity__lt=0).exists())
        self.assertGreater(Sale.objects.count(), 5)
        call_command('seed_demo', stdout=io.StringIO())   # second run is a no-op
        self.assertEqual(User.objects.filter(username='owner').count(), 1)
