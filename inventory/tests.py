from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from branches.models import Branch, StockTransfer
from .forms import ProductForm
from .importer import import_rows, parse
from .models import Category, Product, Stock, StockMovement, Supplier, SupplierPurchase
from .services import InsufficientStock, adjust_stock


class InventoryTestBase(TestCase):
    def setUp(self):
        self.main = Branch.objects.create(name='Main Branch')
        self.west = Branch.objects.create(name='West')
        self.owner = User.objects.create_user(username='o', password='pw-123456!', role=User.Role.OWNER,
                                              branch=self.main)
        self.manager = User.objects.create_user(username='m', password='pw-123456!', role=User.Role.MANAGER,
                                                branch=self.main)
        self.cashier = User.objects.create_user(username='c', password='pw-123456!', role=User.Role.CASHIER,
                                                branch=self.main)
        self.paint = Product.objects.create(sku='PNT', name='Paint 4L', cost_price=1500, sell_price=1850,
                                            reorder_level=5)

    def qty(self, branch, product=None):
        stock = Stock.objects.filter(product=product or self.paint, branch=branch).first()
        return stock.quantity if stock else 0


class AdjustStockTests(InventoryTestBase):
    def test_ledger_records_running_balance(self):
        adjust_stock(self.paint, self.main, 10, StockMovement.Kind.PURCHASE)
        adjust_stock(self.paint, self.main, -3, StockMovement.Kind.SALE)
        balances = list(StockMovement.objects.order_by('id').values_list('balance_after', flat=True))
        self.assertEqual(balances, [10, 7])

    def test_cannot_go_negative(self):
        with self.assertRaises(InsufficientStock):
            adjust_stock(self.paint, self.main, -1, StockMovement.Kind.SALE)
        self.assertFalse(StockMovement.objects.exists())


class StockAdjustViewTests(InventoryTestBase):
    def test_set_counted_quantity(self):
        adjust_stock(self.paint, self.main, 10, StockMovement.Kind.PURCHASE)
        self.client.force_login(self.manager)
        self.client.post(reverse('inventory:stock_adjust'), {
            'product': self.paint.pk, 'branch': self.main.pk, 'mode': 'set', 'quantity': 8,
            'reason': 'Stock count correction',
        })
        self.assertEqual(self.qty(self.main), 8)
        self.assertEqual(StockMovement.objects.first().quantity, -2)  # newest first

    def test_manager_cannot_adjust_other_branch(self):
        self.client.force_login(self.manager)
        self.client.post(reverse('inventory:stock_adjust'), {
            'product': self.paint.pk, 'branch': self.west.pk, 'mode': 'change', 'quantity': 5, 'reason': 'Other',
        })
        self.assertEqual(self.qty(self.west), 0)

    def test_cashier_forbidden(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse('inventory:stock_adjust')).status_code, 403)


class PurchaseTests(InventoryTestBase):
    def test_restock_adds_stock_and_updates_cost(self):
        supplier = Supplier.objects.create(name='Crown Paints')
        self.client.force_login(self.manager)
        self.client.post(reverse('inventory:supplier_purchase_create'), {
            'supplier': supplier.pk, 'product': self.paint.pk, 'branch': self.main.pk,
            'quantity': 12, 'cost_price': '1550', 'is_paid': 'on', 'invoice_number': 'INV-9',
        })
        self.assertEqual(self.qty(self.main), 12)
        self.paint.refresh_from_db()
        self.assertEqual(self.paint.cost_price, Decimal('1550.00'))
        self.assertEqual(SupplierPurchase.objects.get().total_cost, Decimal('18600.00'))

    def test_mark_purchase_paid(self):
        purchase = SupplierPurchase.objects.create(product=self.paint, branch=self.main, quantity=1,
                                                   cost_price=1500, is_paid=False)
        self.client.force_login(self.owner)
        self.client.post(reverse('inventory:purchase_mark_paid', args=[purchase.pk]))
        purchase.refresh_from_db()
        self.assertTrue(purchase.is_paid)
        self.assertIsNotNone(purchase.paid_at)


class TransferTests(InventoryTestBase):
    def setUp(self):
        super().setUp()
        adjust_stock(self.paint, self.main, 20, StockMovement.Kind.PURCHASE)
        self.client.force_login(self.owner)

    def dispatch(self, qty=5, to=None):
        return self.client.post(reverse('branches:transfer_create'), {
            'product': self.paint.pk, 'from_branch': self.main.pk, 'to_branch': (to or self.west).pk,
            'quantity': qty,
        })

    def test_dispatch_and_receive(self):
        self.dispatch()
        transfer = StockTransfer.objects.get()
        self.assertEqual(self.qty(self.main), 15)
        self.client.post(reverse('branches:transfer_receive', args=[transfer.pk]))
        self.assertEqual(self.qty(self.west), 5)

    def test_cancel_returns_stock(self):
        self.dispatch()
        self.client.post(reverse('branches:transfer_cancel', args=[StockTransfer.objects.get().pk]))
        self.assertEqual(self.qty(self.main), 20)

    def test_receive_via_get_not_allowed(self):
        self.dispatch()
        res = self.client.get(reverse('branches:transfer_receive', args=[StockTransfer.objects.get().pk]))
        self.assertEqual(res.status_code, 405)

    def test_same_branch_rejected(self):
        self.dispatch(to=self.main)
        self.assertFalse(StockTransfer.objects.exists())

    def test_insufficient_stock_rejected(self):
        self.dispatch(qty=500)
        self.assertFalse(StockTransfer.objects.exists())
        self.assertEqual(self.qty(self.main), 20)


class ProductFormTests(TestCase):
    def data(self, **kw):
        base = {'sku': 'X', 'name': 'X', 'unit': 'pcs', 'cost_price': '100', 'sell_price': '150',
                'reorder_level': 5, 'wholesale_min_qty': 0, 'is_active': True}
        base.update(kw)
        return base

    def test_rejects_selling_below_cost(self):
        self.assertFalse(ProductForm(self.data(sell_price='90')).is_valid())

    def test_wholesale_needs_threshold(self):
        self.assertFalse(ProductForm(self.data(wholesale_price='140')).is_valid())

    def test_wholesale_above_retail_rejected(self):
        self.assertFalse(ProductForm(self.data(wholesale_price='160', wholesale_min_qty=10)).is_valid())

    def test_price_for_quantity(self):
        p = Product(sell_price=Decimal('150'), wholesale_price=Decimal('130'), wholesale_min_qty=10)
        self.assertEqual(p.price_for_quantity(9), Decimal('150'))
        self.assertEqual(p.price_for_quantity(10), Decimal('130'))


class ImporterTests(InventoryTestBase):
    HEADER = 'sku,name,brand,category,unit,cost_price,sell_price,reorder_level,branch,stock_quantity\n'

    def csv(self, body):
        return SimpleUploadedFile('p.csv', ('﻿' + self.HEADER + body).encode('utf-8'))

    def test_creates_and_updates(self):
        rows, errors = parse(self.csv(
            'PNT,Paint 4L White,Crown,Paint,tin,1600,1900,4,Main Branch,30\n'
            'NAIL-3,Nails 3 inch,,Fasteners,kg,100,150,,,\n'
        ))
        self.assertEqual(errors, [])
        created, updated = import_rows(rows, self.owner)
        self.assertEqual((created, updated), (1, 1))
        self.paint.refresh_from_db()
        self.assertEqual(self.paint.sell_price, Decimal('1900.00'))
        self.assertEqual(self.qty(self.main), 30)
        self.assertTrue(Category.objects.filter(name='Fasteners').exists())

    def test_bad_rows_reported(self):
        rows, errors = parse(self.csv(
            'A,Thing,,,,abc,100,,,\n'
            'B,,,,,10,5,,,\n'
            'C,Other,,,,10,20,,Nowhere,5\n'
            'A,Dup,,,,1,2,,,\n'
        ))
        self.assertEqual(len(errors), 4)

    def test_missing_columns(self):
        _, errors = parse(SimpleUploadedFile('p.csv', b'sku,name\nA,B\n'))
        self.assertIn('Missing column', errors[0])

    def test_import_view_is_all_or_nothing(self):
        self.client.force_login(self.manager)
        self.client.post(reverse('inventory:product_import'), {'file': self.csv(
            'NEW1,Good row,,,,10,20,,,\nNEW2,Bad row,,,,10,5,,,\n'
        )})
        self.assertFalse(Product.objects.filter(sku='NEW1').exists())

    def test_export_round_trips(self):
        self.client.force_login(self.owner)
        res = self.client.get(reverse('inventory:product_export'))
        rows, errors = parse(SimpleUploadedFile('e.csv', res.content))
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]['sku'], 'PNT')


class PageTests(InventoryTestBase):
    def test_pages_render(self):
        self.client.force_login(self.owner)
        for name, args in [('product_list', []), ('product_detail', [self.paint.pk]), ('stock_list', []),
                           ('purchase_list', []), ('supplier_list', []), ('category_list', []),
                           ('product_import', []), ('stock_adjust', [])]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(f'inventory:{name}', args=args)).status_code, 200)

    def test_cashier_does_not_see_cost(self):
        self.client.force_login(self.cashier)
        self.assertNotContains(self.client.get(reverse('inventory:product_list')), '1,500.00')
