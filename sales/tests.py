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
        self.assertContains(res, q.reference)


class QuotationNumberingTests(SaleTestMixin, TestCase):
    def test_numbers_are_sequential_from_one(self):
        refs = [Quotation.objects.create(branch=self.branch, created_by=self.cashier).reference for _ in range(3)]
        self.assertEqual(refs, ['QT-0001', 'QT-0002', 'QT-0003'])

    def test_deleting_does_not_reuse_number_in_the_middle(self):
        first = Quotation.objects.create(branch=self.branch)
        Quotation.objects.create(branch=self.branch)
        first.delete()
        self.assertEqual(Quotation.objects.create(branch=self.branch).number, 3)

    def test_walk_in_name_carried_to_sale(self):
        q = Quotation.objects.create(branch=self.branch, created_by=self.cashier,
                                     customer_name='Mzee Otieno', customer_phone='0722111222')
        QuotationItem.objects.create(quotation=q, product=self.nails, quantity=1, unit_price=150)
        self.client.force_login(self.cashier)
        self.client.post(reverse('sales:convert_quotation', args=[q.pk]))
        sale = Sale.objects.get()
        self.assertEqual(sale.client_name, 'Mzee Otieno')
        self.assertContains(self.client.get(reverse('sales:receipt', args=[sale.pk])), 'Mzee Otieno')

    def test_search_by_reference(self):
        q = Quotation.objects.create(branch=self.branch, created_by=self.cashier)
        self.client.force_login(self.cashier)
        res = self.client.get(reverse('sales:quotation_list'), {'q': q.reference, 'status': 'all'})
        self.assertEqual(list(res.context['page_obj']), [q])


class SaveQuotationTests(SaleTestMixin, TestCase):
    def save(self, user=None, items=None, **kw):
        from .quotations import save_quotation
        items = items if items is not None else [{'product_id': self.cement.pk, 'qty': 2}]
        return save_quotation(user=user or self.cashier, raw_items=items, **kw)

    def test_list_price_and_wholesale_default(self):
        q = self.save(items=[{'product_id': self.cement.pk, 'qty': 12}])
        self.assertEqual(q.items.get().unit_price, Decimal('750.00'))
        self.assertEqual(q.reference, 'QT-0001')

    def test_cashier_can_negotiate_within_cap(self):
        q = self.save(items=[{'product_id': self.cement.pk, 'qty': 1, 'unit_price': '760'}])   # 5% off 800
        self.assertEqual(q.total, Decimal('760.00'))

    def test_cashier_cannot_go_below_cap(self):
        with self.assertRaises(SaleError):
            self.save(items=[{'product_id': self.cement.pk, 'qty': 1, 'unit_price': '700'}])

    def test_manager_floor_is_cost(self):
        self.save(user=self.manager, items=[{'product_id': self.cement.pk, 'qty': 1, 'unit_price': '650'}])
        with self.assertRaises(SaleError):
            self.save(user=self.manager, items=[{'product_id': self.cement.pk, 'qty': 1, 'unit_price': '600'}])

    def test_owner_can_price_below_cost(self):
        owner = User.objects.create_user(username='boss', password='x-123456!', role=User.Role.OWNER,
                                         branch=self.branch)
        q = self.save(user=owner, items=[{'product_id': self.cement.pk, 'qty': 1, 'unit_price': '500'}])
        self.assertEqual(q.total, Decimal('500.00'))

    def test_bad_prices_and_validity(self):
        for kw in ({'items': [{'product_id': self.cement.pk, 'qty': 1, 'unit_price': 'abc'}]},
                   {'items': [{'product_id': self.cement.pk, 'qty': 1, 'unit_price': '0'}]},
                   {'items': []}, {'valid_days': 0}, {'valid_days': 400}):
            with self.subTest(kw=kw), self.assertRaises(SaleError):
                self.save(**kw)

    def test_walk_in_name_ignored_when_customer_registered(self):
        customer = Customer.objects.create(name='Fundi', phone_number='254711', credit_limit=1000)
        q = self.save(customer=customer, customer_name='Someone else')
        self.assertEqual(q.customer_name, '')
        self.assertEqual(q.client_name, 'Fundi')

    def test_edit_keeps_number(self):
        q = self.save()
        edited = self.save(quotation=q, items=[{'product_id': self.nails.pk, 'qty': 4}], valid_days=7)
        self.assertEqual(edited.number, q.number)
        self.assertEqual(edited.items.get().product, self.nails)
        self.assertEqual(Quotation.objects.count(), 1)

    def test_cannot_edit_converted(self):
        q = self.save()
        q.status = Quotation.Status.CONVERTED
        q.save()
        with self.assertRaises(SaleError):
            self.save(quotation=q)

    def test_endpoint_returns_reference(self):
        self.client.force_login(self.cashier)
        res = self.client.post(reverse('sales:create_quotation'), json.dumps({
            'items': [{'product_id': self.nails.pk, 'qty': 2}], 'customer_name': 'Mama Wanjiku',
        }), content_type='application/json')
        self.assertEqual(res.json()['reference'], 'QT-0001')
        self.assertEqual(Quotation.objects.get().client_name, 'Mama Wanjiku')


class QuotationDeskViewTests(SaleTestMixin, TestCase):
    def test_new_desk_shows_next_number(self):
        Quotation.objects.create(branch=self.branch)
        self.client.force_login(self.cashier)
        res = self.client.get(reverse('sales:quotation_desk'))
        self.assertEqual(res.context['desk_config']['nextReference'], 'QT-0002')

    def test_edit_desk_preloads_lines_and_walk_in(self):
        q = Quotation.objects.create(branch=self.branch, customer_name='Mama Akinyi')
        QuotationItem.objects.create(quotation=q, product=self.nails, quantity=4, unit_price=145)
        self.client.force_login(self.cashier)
        initial = self.client.get(reverse('sales:quotation_edit', args=[q.pk])).context['desk_config']['initial']
        self.assertEqual(initial['customer_name'], 'Mama Akinyi')
        self.assertEqual(initial['items'][0]['qty'], 4)
        self.assertEqual(initial['items'][0]['unit_price'], '145.00')

    def test_converted_quotation_cannot_be_edited(self):
        q = Quotation.objects.create(branch=self.branch, status=Quotation.Status.CONVERTED)
        self.client.force_login(self.cashier)
        res = self.client.get(reverse('sales:quotation_edit', args=[q.pk]))
        self.assertRedirects(res, reverse('sales:quotation', args=[q.pk]))


class RecordSaleFromQuotationTests(SaleTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.cashier)

    def quote(self, **kw):
        q = Quotation.objects.create(branch=self.branch, created_by=self.cashier, **kw)
        QuotationItem.objects.create(quotation=q, product=self.cement, quantity=2, unit_price=780)
        return q

    def record(self, q, **data):
        return self.client.post(reverse('sales:convert_quotation', args=[q.pk]), data)

    def test_cash_with_change(self):
        q = self.quote()
        self.record(q, payment_method='CASH', cash_tendered='2000')
        sale = Sale.objects.get()
        self.assertEqual(sale.total, Decimal('1560.00'))
        self.assertEqual(sale.change_given, Decimal('440.00'))
        self.assertEqual(self.stock_of(self.cement), 48)

    def test_mpesa_goes_to_receipt_awaiting_payment(self):
        q = self.quote(customer_name='Wanjiru', customer_phone='0722000111')
        res = self.record(q, payment_method='MPESA', mpesa_phone='0722 000 111')
        sale = Sale.objects.get()
        self.assertEqual(sale.status, Sale.Status.PENDING_PAYMENT)
        self.assertRedirects(res, reverse('sales:receipt', args=[sale.pk]) + '?mpesa=254722000111')
        self.assertContains(self.client.get(res.url), 'Request M-Pesa payment')

    def test_mpesa_bad_phone_does_not_sell(self):
        q = self.quote()
        self.record(q, payment_method='MPESA', mpesa_phone='12')
        self.assertFalse(Sale.objects.exists())

    def test_credit_needs_registered_customer(self):
        q = self.quote(customer_name='Not registered')
        self.record(q, payment_method='CREDIT')
        self.assertFalse(Sale.objects.exists())

    def test_credit_for_registered_customer_and_invoice(self):
        customer = Customer.objects.create(name='Otieno Builders', phone_number='254711000222',
                                           credit_limit=10000, kra_pin='P051111111A')
        q = self.quote(customer=customer)
        self.record(q, payment_method='CREDIT')
        sale = Sale.objects.get()
        customer.refresh_from_db()
        self.assertEqual(customer.balance_owed, Decimal('1560.00'))
        res = self.client.get(reverse('sales:invoice', args=[sale.pk]))
        self.assertContains(res, 'Invoice')
        self.assertContains(res, 'P051111111A')
        self.assertContains(res, 'Kenya Shillings One Thousand Five Hundred and Sixty Only')

    def test_quotation_page_renders_paper(self):
        q = self.quote(customer_name='Mzee Otieno')
        res = self.client.get(reverse('sales:quotation', args=[q.pk]))
        self.assertContains(res, 'Mzee Otieno')
        self.assertContains(res, q.reference)
        self.assertEqual(len(res.context['filler_rows']), 9)

    def test_register_walk_in_from_quotation_attaches_customer(self):
        q = self.quote(customer_name='Kamau Hardware Fundi', customer_phone='0733000444')
        form = self.client.get(reverse('customers:customer_create'),
                               {'name': q.customer_name, 'phone': q.customer_phone, 'quotation': q.pk})
        self.assertEqual(form.context['form'].initial['name'], 'Kamau Hardware Fundi')
        self.client.post(reverse('customers:customer_create'), {
            'name': 'Kamau Hardware Fundi', 'customer_type': 'CONTRACTOR', 'phone_number': '0733000444',
            'credit_limit': '0', 'is_active': 'on', 'quotation': q.pk,
        })
        q.refresh_from_db()
        self.assertEqual(q.customer.phone_number, '254733000444')
        self.assertEqual(q.customer_name, '')


class QuotationExtrasTests(SaleTestMixin, TestCase):
    def test_whatsapp_link_has_number_items_and_total(self):
        from urllib.parse import unquote
        q = Quotation.objects.create(branch=self.branch, customer_name='Akinyi', customer_phone='0722 333 444')
        QuotationItem.objects.create(quotation=q, product=self.cement, quantity=10, unit_price=750)
        self.client.force_login(self.cashier)
        url = unquote(self.client.get(reverse('sales:quotation', args=[q.pk])).context['whatsapp_url'])
        self.assertTrue(url.startswith('https://wa.me/254722333444?text='))
        self.assertIn('Cement 50kg - 10 pcs x 750 = 7,500', url)
        self.assertIn('*TOTAL: KES 7,500.00*', url)

    def test_requote_uses_current_prices(self):
        q = Quotation.objects.create(branch=self.branch, customer_name='Akinyi')
        QuotationItem.objects.create(quotation=q, product=self.nails, quantity=2, unit_price=120)
        self.client.force_login(self.cashier)
        res = self.client.post(reverse('sales:quotation_requote', args=[q.pk]))
        new = Quotation.objects.exclude(pk=q.pk).get()
        self.assertRedirects(res, reverse('sales:quotation_edit', args=[new.pk]))
        self.assertEqual(new.items.get().unit_price, Decimal('150.00'))
        self.assertEqual(new.client_name, 'Akinyi')
        self.assertEqual(new.number, q.number + 1)


class InvoiceServiceTests(SaleTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.customer = Customer.objects.create(name='Otieno Builders', phone_number='254711000222',
                                                credit_limit=20000)

    def invoice(self, **kw):
        from .invoices import create_invoice
        kw.setdefault('raw_items', [{'product_id': self.cement.pk, 'qty': 2}])
        kw.setdefault('payment_method', 'CREDIT')
        kw.setdefault('customer', self.customer)
        return create_invoice(user=kw.pop('user', self.cashier), **kw)

    def test_credit_invoice_numbered_with_due_date(self):
        from datetime import timedelta
        from django.utils import timezone
        sale = self.invoice(due_days=14)
        self.assertEqual(sale.invoice_reference, 'INV-0001')
        self.assertEqual(sale.due_date, timezone.localdate() + timedelta(days=14))
        self.assertEqual(sale.sale_type, Sale.SaleType.CREDIT)
        self.assertEqual(self.stock_of(self.cement), 48)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.balance_owed, Decimal('1600.00'))

    def test_default_terms_from_settings(self):
        from datetime import timedelta
        from django.utils import timezone
        self.assertEqual(self.invoice().due_date, timezone.localdate() + timedelta(days=30))

    def test_numbers_run_in_sequence(self):
        refs = [self.invoice().invoice_reference for _ in range(3)]
        self.assertEqual(refs, ['INV-0001', 'INV-0002', 'INV-0003'])

    def test_cash_invoice_due_today_and_paid(self):
        from django.utils import timezone
        sale = self.invoice(payment_method='CASH', customer=None, customer_name='Mzee Otieno',
                            cash_tendered='2000')
        self.assertEqual(sale.due_date, timezone.localdate())
        self.assertEqual(sale.payment_status, Sale.PaymentStatus.PAID)
        self.assertEqual(sale.client_name, 'Mzee Otieno')
        self.assertFalse(sale.is_overdue)

    def test_credit_needs_registered_customer(self):
        with self.assertRaises(SaleError):
            self.invoice(customer=None, customer_name='Walk-in Kamau')
        self.assertFalse(Sale.objects.exists())

    def test_negotiated_price_rules_apply(self):
        sale = self.invoice(raw_items=[{'product_id': self.cement.pk, 'qty': 1, 'unit_price': '770'}])
        self.assertEqual(sale.total, Decimal('770.00'))
        with self.assertRaises(SaleError):
            self.invoice(raw_items=[{'product_id': self.cement.pk, 'qty': 1, 'unit_price': '600'}])

    def test_overdue(self):
        from datetime import timedelta
        from django.utils import timezone
        sale = self.invoice()
        sale.due_date = timezone.localdate() - timedelta(days=1)
        self.assertTrue(sale.is_overdue)

    def test_issue_invoice_is_idempotent(self):
        from .invoices import issue_invoice
        sale = self.sell([{'product_id': self.nails.pk, 'qty': 1}])
        first = issue_invoice(sale)
        again = issue_invoice(sale)
        self.assertEqual(first.invoice_number, again.invoice_number)


class InvoiceViewTests(SaleTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.customer = Customer.objects.create(name='Otieno Builders', phone_number='254711000222',
                                                credit_limit=20000, kra_pin='P051234567Q')
        self.client.force_login(self.cashier)

    def post_invoice(self, **data):
        payload = {'items': [{'product_id': self.cement.pk, 'qty': 3}], 'payment_method': 'CREDIT',
                   'customer_id': self.customer.pk, 'due_days': 14}
        payload.update(data)
        return self.client.post(reverse('sales:create_invoice'), json.dumps(payload),
                                content_type='application/json')

    def test_issue_from_desk_endpoint(self):
        res = self.post_invoice()
        self.assertEqual(res.json()['reference'], 'INV-0001')
        page = self.client.get(res.json()['redirect'])
        self.assertContains(page, 'Bill To')
        self.assertContains(page, 'P051234567Q')
        self.assertContains(page, 'Received by')
        self.assertContains(page, 'BALANCE DUE')

    def test_mpesa_invoice_redirects_to_receipt_prompt(self):
        res = self.post_invoice(payment_method='MPESA', customer_id=None, customer_name='Akinyi',
                                mpesa_phone='0712 345 678')
        self.assertIn('?mpesa=254712345678', res.json()['redirect'])

    def test_bad_mpesa_phone_rejected(self):
        res = self.post_invoice(payment_method='MPESA', mpesa_phone='12')
        self.assertEqual(res.status_code, 400)
        self.assertFalse(Sale.objects.exists())

    def test_quotation_conversion_issues_invoice(self):
        q = Quotation.objects.create(branch=self.branch, created_by=self.cashier, customer=self.customer)
        QuotationItem.objects.create(quotation=q, product=self.nails, quantity=2, unit_price=150)
        res = self.client.post(reverse('sales:convert_quotation', args=[q.pk]),
                               {'payment_method': 'CREDIT', 'due_days': '7'})
        sale = Sale.objects.get()
        self.assertRedirects(res, reverse('sales:invoice', args=[sale.pk]))
        self.assertEqual(sale.invoice_reference, 'INV-0001')
        self.assertContains(self.client.get(reverse('sales:invoice', args=[sale.pk])), q.reference)

    def test_issue_number_for_till_sale(self):
        sale = self.sell([{'product_id': self.nails.pk, 'qty': 1}])
        page = self.client.get(reverse('sales:invoice', args=[sale.pk]))
        self.assertContains(page, 'Cash Sale')
        self.client.post(reverse('sales:issue_invoice', args=[sale.pk]))
        sale.refresh_from_db()
        self.assertEqual(sale.invoice_reference, 'INV-0001')

    def test_invoice_list_filters(self):
        from datetime import timedelta
        from django.utils import timezone
        self.post_invoice()
        late = Sale.objects.get()
        Sale.objects.filter(pk=late.pk).update(due_date=timezone.localdate() - timedelta(days=3))
        self.post_invoice(payment_method='CASH', customer_id=None)
        res = self.client.get(reverse('sales:invoice_list'), {'status': 'overdue'})
        self.assertEqual([s.pk for s in res.context['page_obj']], [late.pk])
        self.assertEqual(res.context['overdue_total'], Decimal('2400.00'))
        paid = self.client.get(reverse('sales:invoice_list'), {'status': 'paid'})
        self.assertEqual(len(paid.context['page_obj']), 1)

    def test_quotation_has_no_validity_or_signatures(self):
        q = Quotation.objects.create(branch=self.branch, created_by=self.cashier)
        QuotationItem.objects.create(quotation=q, product=self.nails, quantity=1, unit_price=150)
        page = self.client.get(reverse('sales:quotation', args=[q.pk]))
        self.assertNotContains(page, 'Valid for')
        self.assertNotContains(page, 'Customer signature')
        self.assertContains(page, 'This is a quotation, not a receipt')
