import json
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from branches.models import Branch
from core.models import ShopSettings
from customers.models import Customer
from customers.services import record_debt_payment
from inventory.models import Product, Stock
from sales.services import checkout, process_return
from .models import Expense, Shift
from .services import ShiftError, close_shift, open_shift, shift_summary


class ShiftTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Main')
        self.cashier = User.objects.create_user(
            username='c', password='pw-123456!', role=User.Role.CASHIER, branch=self.branch,
        )
        self.manager = User.objects.create_user(
            username='m', password='pw-123456!', role=User.Role.MANAGER, branch=self.branch,
        )
        self.product = Product.objects.create(sku='P', name='Hammer', cost_price=300, sell_price=500)
        Stock.objects.create(product=self.product, branch=self.branch, quantity=100)

    def sell(self, qty, method='CASH', **kw):
        return checkout(user=self.cashier, branch=self.branch, payment_method=method,
                        raw_items=[{'product_id': self.product.pk, 'qty': qty}], **kw)

    def test_expected_cash_combines_float_sales_refunds_and_expenses(self):
        shift = open_shift(self.cashier, Decimal('1000'))
        sale = self.sell(4)                    # +2000 cash
        self.sell(1, method='CARD')            # card, not in drawer
        customer = Customer.objects.create(name='K', phone_number='2547', credit_limit=5000)
        self.sell(2, method='CREDIT', customer=customer)
        record_debt_payment(customer, Decimal('400'), self.cashier)          # +400 cash
        process_return(sale, self.cashier, {sale.items.get().pk: 1}, 'x', 'CASH')  # -500
        Expense.objects.create(branch=self.branch, category='LOADING', description='Lorry',
                               amount=Decimal('150'), recorded_by=self.cashier)    # -150

        summary = shift_summary(shift)
        self.assertEqual(summary['expected_cash'], Decimal('2750.00'))
        self.assertEqual(summary['by_method']['CARD'], Decimal('500.00'))
        self.assertEqual(summary['sales_count'], 3)
        self.assertEqual(summary['credit_sales'], Decimal('1000.00'))

    def test_close_records_variance(self):
        shift = open_shift(self.cashier, Decimal('500'))
        self.sell(1)
        shift = close_shift(shift, self.cashier, Decimal('950'))
        self.assertEqual(shift.expected_cash, Decimal('1000.00'))
        self.assertEqual(shift.variance, Decimal('-50.00'))
        self.assertEqual(shift.status, Shift.Status.CLOSED)

    def test_cannot_open_two_shifts(self):
        open_shift(self.cashier, Decimal('0'))
        with self.assertRaises(ShiftError):
            open_shift(self.cashier, Decimal('0'))

    def test_db_enforces_single_open_shift(self):
        Shift.objects.create(branch=self.branch, cashier=self.cashier)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Shift.objects.create(branch=self.branch, cashier=self.cashier)

    def test_cannot_close_twice(self):
        shift = open_shift(self.cashier, Decimal('0'))
        close_shift(shift, self.cashier, Decimal('0'))
        with self.assertRaises(ShiftError):
            close_shift(shift, self.cashier, Decimal('0'))

    def test_other_cashiers_takings_not_counted(self):
        shift = open_shift(self.cashier, Decimal('0'))
        checkout(user=self.manager, branch=self.branch, payment_method='CASH',
                 raw_items=[{'product_id': self.product.pk, 'qty': 1}])
        self.assertEqual(shift_summary(shift)['expected_cash'], Decimal('0.00'))

    def test_shift_required_blocks_pos_sale(self):
        settings = ShopSettings.load()
        settings.require_open_shift = True
        settings.save()
        self.client.force_login(self.cashier)
        payload = json.dumps({'items': [{'product_id': self.product.pk, 'qty': 1}], 'payment_method': 'CASH'})
        url = reverse('sales:create_sale')
        self.assertEqual(self.client.post(url, payload, content_type='application/json').status_code, 400)
        open_shift(self.cashier, Decimal('0'))
        self.assertEqual(self.client.post(url, payload, content_type='application/json').status_code, 200)

    def test_shift_views(self):
        self.client.force_login(self.cashier)
        self.client.post(reverse('registers:my_shift'), {'opening_float': '200'})
        shift = Shift.objects.get()
        self.assertEqual(self.client.get(reverse('registers:my_shift')).status_code, 200)
        res = self.client.post(reverse('registers:shift_close', args=[shift.pk]), {'counted_cash': '200'})
        self.assertRedirects(res, reverse('registers:shift_detail', args=[shift.pk]))

    def test_cashier_cannot_view_others_shift(self):
        shift = open_shift(self.manager, Decimal('0'))
        self.client.force_login(self.cashier)
        res = self.client.get(reverse('registers:shift_detail', args=[shift.pk]))
        self.assertRedirects(res, reverse('registers:my_shift'))

    def test_expense_form_rejects_zero(self):
        self.client.force_login(self.cashier)
        self.client.post(reverse('registers:expense_list'),
                         {'category': 'OTHER', 'description': 'x', 'amount': '0'})
        self.assertFalse(Expense.objects.exists())
