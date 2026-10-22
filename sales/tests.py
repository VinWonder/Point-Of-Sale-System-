import json
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from branches.models import Branch
from customers.models import Customer
from inventory.models import Product, Stock, StockMovement
from payments.models import Payment
from .models import Sale, Quotation, QuotationItem
from .services import SaleError, CustomerBlocked, checkout, void_sale


class SaleTestMixin:
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name='Main')
        cls.cashier = User.objects.create_user(
            username='cashier', password='pw-123456!', role=User.Role.CASHIER, branch=cls.branch,
        )
        cls.manager = User.objects.create_user(
            username='manager', password='pw-123456!', role=User.Role.MANAGER, branch=cls.branch,
        )
        cls.cement = Product.objects.create(
            sku='CEM', name='Cement 50kg', cost_price=650, sell_price=800,
            wholesale_price=750, wholesale_min_qty=10,
        )
        cls.nails = Product.objects.create(sku='NAIL', name='Nails 1kg', cost_price=100, sell_price=150)

    def setUp(self):
        Stock.objects.create(product=self.cement, branch=self.branch, quantity=50)
        Stock.objects.create(product=self.nails, branch=self.branch, quantity=20)

    def stock_of(self, product):
        return Stock.objects.get(product=product, branch=self.branch).quantity

    def sell(self, items, **kwargs):
        kwargs.setdefault('payment_method', 'CASH')
        return checkout(user=kwargs.pop('user', self.cashier), branch=self.branch, raw_items=items, **kwargs)


class CheckoutServiceTests(SaleTestMixin, TestCase):
    def test_cash_sale_deducts_stock_and_is_paid(self):
        sale = self.sell([{'product_id': self.nails.pk, 'qty': 3}])
        self.assertEqual(sale.total, Decimal('450.00'))
        self.assertEqual(sale.payment_status, Sale.PaymentStatus.PAID)
        self.assertEqual(sale.amount_paid, Decimal('450.00'))
        self.assertEqual(self.stock_of(self.nails), 17)
        self.assertEqual(StockMovement.objects.filter(kind=StockMovement.Kind.SALE).count(), 1)

    def test_vat_is_extracted_from_inclusive_total(self):
        sale = self.sell([{'product_id': self.cement.pk, 'qty': 1}])
        self.assertEqual(sale.tax_amount, Decimal('110.34'))

    def test_line_records_cost_price_for_profit(self):
        sale = self.sell([{'product_id': self.cement.pk, 'qty': 2}])
        self.assertEqual(sale.gross_profit, Decimal('300.00'))

    def test_negative_quantity_rejected(self):
        with self.assertRaises(SaleError):
            self.sell([{'product_id': self.nails.pk, 'qty': -5}])
        self.assertEqual(self.stock_of(self.nails), 20)

    def test_zero_quantity_rejected(self):
        with self.assertRaises(SaleError):
            self.sell([{'product_id': self.nails.pk, 'qty': 0}])

    def test_duplicate_lines_are_merged_before_stock_check(self):
        with self.assertRaises(SaleError):
            self.sell([{'product_id': self.nails.pk, 'qty': 15}, {'product_id': self.nails.pk, 'qty': 15}])
        self.assertEqual(self.stock_of(self.nails), 20)
        self.assertFalse(Sale.objects.exists())

    def test_oversell_rolls_back_whole_sale(self):
        with self.assertRaises(SaleError):
            self.sell([{'product_id': self.cement.pk, 'qty': 2}, {'product_id': self.nails.pk, 'qty': 99}])
        self.assertEqual(self.stock_of(self.cement), 50)
        self.assertFalse(Sale.objects.exists())

    def test_wholesale_price_applies_from_threshold(self):
        sale = self.sell([{'product_id': self.cement.pk, 'qty': 10}])
        self.assertEqual(sale.items.get().unit_price, Decimal('750.00'))
        self.assertEqual(sale.total, Decimal('7500.00'))

    def test_inactive_product_cannot_be_sold(self):
        self.nails.is_active = False
        self.nails.save()
        with self.assertRaises(SaleError):
            self.sell([{'product_id': self.nails.pk, 'qty': 1}])

    def test_invalid_payment_method_rejected(self):
        with self.assertRaises(SaleError):
            self.sell([{'product_id': self.nails.pk, 'qty': 1}], payment_method='BITCOIN')

    def test_cashier_discount_capped(self):
        with self.assertRaises(SaleError):
            self.sell([{'product_id': self.cement.pk, 'qty': 1}], discount=100)

    def test_manager_can_give_larger_discount(self):
        sale = self.sell([{'product_id': self.cement.pk, 'qty': 1}], discount=100, user=self.manager)
        self.assertEqual(sale.total, Decimal('700.00'))

    def test_cash_tendered_must_cover_total(self):
        with self.assertRaises(SaleError):
            self.sell([{'product_id': self.cement.pk, 'qty': 1}], cash_tendered=500)

    def test_change_is_calculated(self):
        sale = self.sell([{'product_id': self.cement.pk, 'qty': 1}], cash_tendered=1000)
        self.assertEqual(sale.change_given, Decimal('200.00'))

    def test_no_branch_rejected(self):
        with self.assertRaises(SaleError):
            checkout(user=self.cashier, branch=None, raw_items=[{'product_id': self.nails.pk, 'qty': 1}])


class CreditSaleTests(SaleTestMixin, TestCase):
    def test_credit_sale_increases_balance(self):
        customer = Customer.objects.create(name='Fundi', phone_number='254711', credit_limit=5000)
        sale = self.sell([{'product_id': self.cement.pk, 'qty': 2}], payment_method='CREDIT', customer=customer)
        customer.refresh_from_db()
        self.assertEqual(customer.balance_owed, Decimal('1600.00'))
        self.assertEqual(sale.payment_status, Sale.PaymentStatus.UNPAID)
        self.assertEqual(sale.sale_type, Sale.SaleType.CREDIT)

    def test_credit_sale_cannot_exceed_limit(self):
        customer = Customer.objects.create(name='Fundi', phone_number='254711', credit_limit=1000)
        with self.assertRaises(SaleError):
            self.sell([{'product_id': self.cement.pk, 'qty': 2}], payment_method='CREDIT', customer=customer)
        customer.refresh_from_db()
        self.assertEqual(customer.balance_owed, 0)

    def test_credit_needs_customer(self):
        with self.assertRaises(SaleError):
            self.sell([{'product_id': self.nails.pk, 'qty': 1}], payment_method='CREDIT')

    def test_defaulter_blocked_even_for_cash(self):
        customer = Customer.objects.create(
            name='Late', phone_number='254722', credit_limit=1000, balance_owed=2000,
        )
        with self.assertRaises(CustomerBlocked):
            self.sell([{'product_id': self.nails.pk, 'qty': 1}], customer=customer)


class VoidSaleTests(SaleTestMixin, TestCase):
    def test_void_restores_stock(self):
        sale = self.sell([{'product_id': self.nails.pk, 'qty': 5}])
        void_sale(sale, self.manager, 'Rang up wrong item')
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.VOIDED)
        self.assertEqual(self.stock_of(self.nails), 20)

    def test_void_reverses_credit(self):
        customer = Customer.objects.create(name='Fundi', phone_number='254711', credit_limit=5000)
        sale = self.sell([{'product_id': self.cement.pk, 'qty': 1}], payment_method='CREDIT', customer=customer)
        void_sale(sale, self.manager, 'Customer changed mind')
        customer.refresh_from_db()
        self.assertEqual(customer.balance_owed, 0)

    def test_cannot_void_twice(self):
        sale = self.sell([{'product_id': self.nails.pk, 'qty': 1}])
        void_sale(sale, self.manager, 'Mistake')
        with self.assertRaises(SaleError):
            void_sale(sale, self.manager, 'Again')

    def test_void_needs_reason(self):
        sale = self.sell([{'product_id': self.nails.pk, 'qty': 1}])
        with self.assertRaises(SaleError):
            void_sale(sale, self.manager, '   ')


class SaleEndpointTests(SaleTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.cashier)

    def post_sale(self, payload):
        return self.client.post(reverse('sales:create_sale'), json.dumps(payload), content_type='application/json')

    def test_create_sale_endpoint(self):
        res = self.post_sale({'items': [{'product_id': self.nails.pk, 'qty': 2}], 'payment_method': 'CASH'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['total'], '300.00')

    def test_defaulter_gets_403(self):
        customer = Customer.objects.create(
            name='Late', phone_number='254722', credit_limit=1000, balance_owed=2000,
        )
        res = self.post_sale({
            'items': [{'product_id': self.nails.pk, 'qty': 1}], 'payment_method': 'CASH',
            'customer_id': customer.pk,
        })
        self.assertEqual(res.status_code, 403)

    def test_malformed_json_is_400(self):
        res = self.client.post(reverse('sales:create_sale'), 'not json', content_type='application/json')
        self.assertEqual(res.status_code, 400)

    def test_card_sale_records_successful_payment(self):
        res = self.post_sale({'items': [{'product_id': self.nails.pk, 'qty': 1}], 'payment_method': 'CARD'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Payment.objects.get().method, 'CARD')


class QuotationTests(SaleTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.cashier)

    def make_quote(self, qty):
        q = Quotation.objects.create(branch=self.branch, created_by=self.cashier)
        QuotationItem.objects.create(quotation=q, product=self.nails, quantity=qty, unit_price=140)
        return q

    def test_convert_honours_quoted_price(self):
        q = self.make_quote(2)
        self.client.post(reverse('sales:convert_quotation', args=[q.pk]))
        sale = Sale.objects.get()
        self.assertEqual(sale.total, Decimal('280.00'))
        self.assertEqual(self.stock_of(self.nails), 18)
        q.refresh_from_db()
        self.assertEqual(q.status, Quotation.Status.CONVERTED)

    def test_convert_does_not_oversell(self):
        q = self.make_quote(500)
        self.client.post(reverse('sales:convert_quotation', args=[q.pk]))
        self.assertFalse(Sale.objects.exists())
        self.assertEqual(self.stock_of(self.nails), 20)
        q.refresh_from_db()
        self.assertEqual(q.status, Quotation.Status.DRAFT)

    def test_convert_requires_post(self):
        q = self.make_quote(1)
        res = self.client.get(reverse('sales:convert_quotation', args=[q.pk]))
        self.assertEqual(res.status_code, 405)


class VoidEndpointTests(SaleTestMixin, TestCase):
    def test_cashier_cannot_void(self):
        sale = self.sell([{'product_id': self.nails.pk, 'qty': 1}])
        self.client.force_login(self.cashier)
        res = self.client.post(reverse('sales:void_sale', args=[sale.pk]), {'reason': 'x'})
        self.assertEqual(res.status_code, 403)

    def test_manager_voids_via_endpoint(self):
        sale = self.sell([{'product_id': self.nails.pk, 'qty': 4}])
        self.client.force_login(self.manager)
        self.client.post(reverse('sales:void_sale', args=[sale.pk]), {'reason': 'Wrong customer'})
        sale.refresh_from_db()
        self.assertTrue(sale.is_voided)
        self.assertEqual(self.stock_of(self.nails), 20)


class ReturnTests(SaleTestMixin, TestCase):
    def test_return_restocks_and_refunds(self):
        from .services import process_return
        sale = self.sell([{'product_id': self.nails.pk, 'qty': 5}])
        item = sale.items.get()
        ret = process_return(sale, self.cashier, {item.pk: 2}, 'Too many', 'CASH')
        self.assertEqual(ret.refund_amount, Decimal('300.00'))
        self.assertEqual(self.stock_of(self.nails), 17)
        item.refresh_from_db()
        self.assertEqual(item.returnable_quantity, 3)

    def test_cannot_return_more_than_sold(self):
        from .services import process_return
        sale = self.sell([{'product_id': self.nails.pk, 'qty': 2}])
        item = sale.items.get()
        process_return(sale, self.cashier, {item.pk: 2}, 'Wrong size', 'CASH')
        with self.assertRaises(SaleError):
            process_return(sale, self.cashier, {item.pk: 1}, 'Again', 'CASH')

    def test_damaged_return_not_restocked(self):
        from .services import process_return
        sale = self.sell([{'product_id': self.nails.pk, 'qty': 2}])
        item = sale.items.get()
        process_return(sale, self.cashier, {item.pk: 1}, 'Rusty', 'CASH', restock={item.pk: False})
        self.assertEqual(self.stock_of(self.nails), 18)

    def test_refund_shares_discount(self):
        from .services import process_return
        sale = self.sell([{'product_id': self.cement.pk, 'qty': 2}], discount=160, user=self.manager)
        item = sale.items.get()
        ret = process_return(sale, self.manager, {item.pk: 1}, 'Extra bag', 'CASH')
        self.assertEqual(ret.refund_amount, Decimal('720.00'))

    def test_account_refund_reduces_debt(self):
        from .services import process_return
        customer = Customer.objects.create(name='Fundi', phone_number='254711', credit_limit=5000)
        sale = self.sell([{'product_id': self.cement.pk, 'qty': 3}], payment_method='CREDIT', customer=customer)
        process_return(sale, self.cashier, {sale.items.get().pk: 1}, 'Unused', 'ACCOUNT')
        customer.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(customer.balance_owed, Decimal('1600.00'))
        self.assertEqual(sale.balance_due, Decimal('1600.00'))

    def test_account_refund_rejected_on_paid_sale(self):
        from .services import process_return
        customer = Customer.objects.create(name='Fundi', phone_number='254711', credit_limit=5000)
        sale = self.sell([{'product_id': self.nails.pk, 'qty': 1}], customer=customer)
        with self.assertRaises(SaleError):
            process_return(sale, self.cashier, {sale.items.get().pk: 1}, 'x', 'ACCOUNT')
        self.assertEqual(self.stock_of(self.nails), 19)


class QuotationExpiryTests(SaleTestMixin, TestCase):
    def test_expired_quotes_listed_and_not_convertible(self):
        import io
        from datetime import timedelta
        from django.core.management import call_command
        from django.utils import timezone
        q = Quotation.objects.create(branch=self.branch, created_by=self.cashier,
                                     valid_until=timezone.localdate() - timedelta(days=1))
        QuotationItem.objects.create(quotation=q, product=self.nails, quantity=1, unit_price=150)
        self.client.force_login(self.cashier)
        self.client.post(reverse('sales:convert_quotation', args=[q.pk]))
        self.assertFalse(Sale.objects.exists())

        call_command('expire_quotations', stdout=io.StringIO())
        q.refresh_from_db()
        self.assertEqual(q.status, Quotation.Status.EXPIRED)
        res = self.client.get(reverse('sales:quotation_list'), {'status': 'expired'})
        self.assertContains(res, f'Q-{q.pk}')
