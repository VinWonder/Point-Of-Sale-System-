from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from branches.models import Branch
from inventory.models import Product, Stock
from sales.models import Sale
from sales.services import checkout
from .forms import CustomerForm
from .models import Customer, DebtPayment
from .services import DebtPaymentError, record_debt_payment


class DebtPaymentTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Main')
        self.user = User.objects.create_user(
            username='m', password='pw-123456!', role=User.Role.MANAGER, branch=self.branch,
        )
        self.product = Product.objects.create(sku='T', name='Timber 2x4', cost_price=200, sell_price=300)
        Stock.objects.create(product=self.product, branch=self.branch, quantity=100)
        self.customer = Customer.objects.create(name='Fundi Ken', phone_number='254711000111', credit_limit=10000)

    def credit_sale(self, qty):
        return checkout(
            user=self.user, branch=self.branch, raw_items=[{'product_id': self.product.pk, 'qty': qty}],
            customer=self.customer, payment_method='CREDIT',
        )

    def test_payment_reduces_balance(self):
        self.credit_sale(10)
        record_debt_payment(self.customer, Decimal('1000'), self.user)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.balance_owed, Decimal('2000.00'))
        self.assertEqual(DebtPayment.objects.get().balance_after, Decimal('2000.00'))

    def test_overpayment_rejected(self):
        self.credit_sale(1)
        with self.assertRaises(DebtPaymentError):
            record_debt_payment(self.customer, Decimal('500'), self.user)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.balance_owed, Decimal('300.00'))

    def test_zero_payment_rejected(self):
        self.credit_sale(1)
        with self.assertRaises(DebtPaymentError):
            record_debt_payment(self.customer, Decimal('0'), self.user)

    def test_payment_settles_oldest_sale_first(self):
        first = self.credit_sale(2)   # 600
        second = self.credit_sale(3)  # 900
        record_debt_payment(self.customer, Decimal('800'), self.user, method='MPESA', reference='QAB12')
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.payment_status, Sale.PaymentStatus.PAID)
        self.assertEqual(second.payment_status, Sale.PaymentStatus.PARTIAL)
        self.assertEqual(second.amount_paid, Decimal('200.00'))

    def test_record_payment_view(self):
        self.credit_sale(2)
        self.client.force_login(self.user)
        res = self.client.post(reverse('customers:record_payment', args=[self.customer.pk]),
                               {'amount': '600', 'method': 'CASH'})
        self.assertEqual(res.status_code, 302)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.balance_owed, 0)

    def test_record_payment_view_rejects_get(self):
        self.client.force_login(self.user)
        res = self.client.get(reverse('customers:record_payment', args=[self.customer.pk]))
        self.assertEqual(res.status_code, 405)


class CustomerFormTests(TestCase):
    def test_phone_is_normalised(self):
        form = CustomerForm(data={
            'name': 'A', 'customer_type': 'RETAIL', 'phone_number': '0722 000 111', 'credit_limit': '0',
            'is_active': True,
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['phone_number'], '254722000111')

    def test_cashier_cannot_set_credit_limit(self):
        cashier = User(role=User.Role.CASHIER)
        form = CustomerForm(user=cashier)
        self.assertTrue(form.fields['credit_limit'].disabled)

    def test_defaulter_flag(self):
        c = Customer(credit_limit=100, balance_owed=150)
        self.assertTrue(c.is_defaulter)
        self.assertEqual(c.available_credit, 0)
