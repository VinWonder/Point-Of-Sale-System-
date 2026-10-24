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
            reverse('sales:sale_return', args=[sale.pk]), reverse('sales:invoice', args=[sale.pk]),
            reverse('sales:quotation_desk'), reverse('sales:invoice_desk'), reverse('sales:invoice_list'),
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


class LogoUploadTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='boss', password='pw-123456!', role=User.Role.OWNER)
        self.client.force_login(self.owner)

    def post(self, upload, **extra):
        data = {'business_name': 'Jenga Hardware', 'show_logo': 'on', 'vat_rate': '16',
                'max_cashier_discount_percent': '5', 'quotation_validity_days': '14', 'invoice_due_days': '30',
                'logo_upload': upload}
        data.update(extra)
        return self.client.post(reverse('core:settings'), data)

    def png(self, size=(1200, 600)):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', size, (0, 120, 200)).save(buffer, format='PNG')
        return SimpleUploadedFile('logo.png', buffer.getvalue(), content_type='image/png')

    def test_logo_is_resized_and_stored(self):
        import base64
        from PIL import Image
        self.post(self.png())
        logo = ShopSettings.load().logo
        self.assertTrue(logo.startswith('data:image/png;base64,'))
        image = Image.open(io.BytesIO(base64.b64decode(logo.split(',', 1)[1])))
        self.assertEqual(max(image.size), 400)

    def test_non_image_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake = SimpleUploadedFile('logo.png', b'<script>alert(1)</script>', content_type='image/png')
        res = self.post(fake)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(ShopSettings.load().logo, '')

    def test_remove_logo(self):
        self.post(self.png())
        self.post('', remove_logo='on')
        self.assertEqual(ShopSettings.load().logo, '')

    def test_logo_shown_in_layout(self):
        self.post(self.png())
        self.assertContains(self.client.get(reverse('dashboard:index')), 'data:image/png;base64,')


class AmountInWordsTests(TestCase):
    def test_examples(self):
        from .words import amount_in_words
        self.assertEqual(amount_in_words(0), 'Kenya Shillings Zero Only')
        self.assertEqual(amount_in_words(15), 'Kenya Shillings Fifteen Only')
        self.assertEqual(amount_in_words(1005), 'Kenya Shillings One Thousand and Five Only')
        self.assertEqual(amount_in_words(Decimal('12550.50')),
                         'Kenya Shillings Twelve Thousand Five Hundred and Fifty and Fifty Cents Only')
        self.assertEqual(amount_in_words(2_340_000),
                         'Kenya Shillings Two Million Three Hundred and Forty Thousand Only')
        self.assertEqual(amount_in_words(99), 'Kenya Shillings Ninety-Nine Only')
