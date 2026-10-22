import json
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from branches.models import Branch
from inventory.models import Product, Stock
from sales.models import Sale
from sales.services import checkout
from .models import Payment
from .mpesa import InvalidPhoneNumber, normalize_phone


class NormalizePhoneTests(TestCase):
    def test_accepts_common_formats(self):
        for raw in ('0712345678', '0712 345 678', '+254712345678', '254712345678', '712345678'):
            self.assertEqual(normalize_phone(raw), '254712345678')

    def test_accepts_new_011_prefix(self):
        self.assertEqual(normalize_phone('0110123456'), '254110123456')

    def test_rejects_garbage(self):
        for raw in ('', '12345', '0812345678', 'abc', None):
            with self.assertRaises(InvalidPhoneNumber):
                normalize_phone(raw)


def callback_payload(checkout_id, code=0, receipt='QWE123RTY'):
    body = {'Body': {'stkCallback': {
        'CheckoutRequestID': checkout_id, 'ResultCode': code, 'ResultDesc': 'ok',
        'CallbackMetadata': {'Item': [{'Name': 'MpesaReceiptNumber', 'Value': receipt}]},
    }}}
    return json.dumps(body)


@override_settings(DEBUG=True, MPESA_CONSUMER_KEY='', MPESA_CONSUMER_SECRET='', MPESA_PASSKEY='')
class MpesaFlowTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Main')
        self.user = User.objects.create_user(username='c', password='pw-123456!', branch=self.branch)
        product = Product.objects.create(sku='P', name='Paint 4L', cost_price=900, sell_price=1250.50)
        Stock.objects.create(product=product, branch=self.branch, quantity=10)
        self.sale = checkout(
            user=self.user, branch=self.branch, raw_items=[{'product_id': product.pk, 'qty': 1}],
            payment_method='MPESA',
        )
        self.client.force_login(self.user)

    def initiate(self, phone='0712345678'):
        return self.client.post(reverse('payments:mpesa_initiate', args=[self.sale.pk]), {'phone_number': phone})

    def test_mpesa_sale_waits_for_payment(self):
        self.assertEqual(self.sale.status, Sale.Status.PENDING_PAYMENT)
        self.assertEqual(self.sale.payment_status, Sale.PaymentStatus.UNPAID)

    def test_initiate_rounds_up_to_whole_shillings(self):
        res = self.initiate()
        self.assertEqual(res.status_code, 200)
        payment = Payment.objects.get(pk=res.json()['payment_id'])
        self.assertEqual(payment.amount, Decimal('1251'))
        self.assertEqual(payment.phone_number, '254712345678')

    def test_initiate_rejects_bad_phone(self):
        self.assertEqual(self.initiate('123').status_code, 400)

    def test_initiate_requires_post(self):
        res = self.client.get(reverse('payments:mpesa_initiate', args=[self.sale.pk]))
        self.assertEqual(res.status_code, 405)

    def test_successful_callback_marks_sale_paid(self):
        payment = Payment.objects.get(pk=self.initiate().json()['payment_id'])
        self.client.post(reverse('payments:mpesa_callback'), callback_payload(payment.checkout_request_id),
                         content_type='application/json')
        payment.refresh_from_db()
        self.sale.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCESS)
        self.assertEqual(payment.mpesa_receipt_number, 'QWE123RTY')
        self.assertEqual(self.sale.payment_status, Sale.PaymentStatus.PAID)
        self.assertEqual(self.sale.status, Sale.Status.COMPLETED)

    def test_failed_callback_after_success_is_ignored(self):
        payment = Payment.objects.get(pk=self.initiate().json()['payment_id'])
        url = reverse('payments:mpesa_callback')
        self.client.post(url, callback_payload(payment.checkout_request_id), content_type='application/json')
        self.client.post(url, callback_payload(payment.checkout_request_id, code=1032),
                         content_type='application/json')
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCESS)

    def test_cancelled_callback_marks_failed(self):
        payment = Payment.objects.get(pk=self.initiate().json()['payment_id'])
        self.client.post(reverse('payments:mpesa_callback'),
                         callback_payload(payment.checkout_request_id, code=1032),
                         content_type='application/json')
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.payment_status, Sale.PaymentStatus.UNPAID)

    def test_callback_with_unknown_id_is_acknowledged(self):
        res = self.client.post(reverse('payments:mpesa_callback'), callback_payload('nope'),
                               content_type='application/json')
        self.assertEqual(res.json()['ResultCode'], 0)

    def test_callback_rejects_malformed_body(self):
        res = self.client.post(reverse('payments:mpesa_callback'), 'xx', content_type='application/json')
        self.assertEqual(res.status_code, 400)

    def test_simulator_completes_payment(self):
        payment_id = self.initiate().json()['payment_id']
        res = self.client.post(reverse('payments:mpesa_simulate', args=[payment_id]), {'outcome': 'success'})
        self.assertEqual(res.json()['status'], 'SUCCESS')
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.payment_status, Sale.PaymentStatus.PAID)
