from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from branches.models import Branch
from customers.models import Customer
from inventory.models import Product, Stock
from registers.models import Expense
from sales.models import Sale
from sales.services import checkout, process_return, void_sale
from . import metrics


class MetricsTestBase(TestCase):
    def setUp(self):
        self.main = Branch.objects.create(name='Main')
        self.west = Branch.objects.create(name='West')
        self.owner = User.objects.create_user(username='o', password='pw-123456!', role=User.Role.OWNER,
                                              branch=self.main)
        self.cashier = User.objects.create_user(username='c', password='pw-123456!', role=User.Role.CASHIER,
                                                branch=self.main)
        self.pipe = Product.objects.create(sku='PIPE', name='PVC pipe 3m', cost_price=400, sell_price=500,
                                           reorder_level=10)
        Stock.objects.create(product=self.pipe, branch=self.main, quantity=100)
        Stock.objects.create(product=self.pipe, branch=self.west, quantity=100)
        self.today = timezone.localdate()

    def sell(self, qty, branch=None, **kw):
        kw.setdefault('payment_method', 'CASH')
        return checkout(user=self.owner, branch=branch or self.main,
                        raw_items=[{'product_id': self.pipe.pk, 'qty': qty}], **kw)


class SalesTotalsTests(MetricsTestBase):
    def test_profit_excludes_voids_and_returns(self):
        self.sell(4)                                        # 2000 revenue, 1600 cost
        voided = self.sell(10)
        void_sale(voided, self.owner, 'mistake')
        returned = self.sell(2)                             # 1000 revenue
        process_return(returned, self.owner, {returned.items.get().pk: 1}, 'extra', 'CASH')

        t = metrics.sales_totals(self.today, self.today)
        self.assertEqual(t['count'], 2)
        self.assertEqual(t['revenue'], Decimal('3000.00'))
        self.assertEqual(t['refunds'], Decimal('500.00'))
        self.assertEqual(t['net_revenue'], Decimal('2500.00'))
        self.assertEqual(t['cost'], Decimal('2000.00'))
        self.assertEqual(t['gross_profit'], Decimal('500.00'))
        self.assertEqual(t['margin'], 20.0)

    def test_branch_scoping(self):
        self.sell(1)
        self.sell(3, branch=self.west)
        self.assertEqual(metrics.sales_totals(self.today, self.today, self.west)['revenue'], Decimal('1500.00'))
        self.assertEqual(metrics.sales_totals(self.today, self.today)['revenue'], Decimal('2000.00'))

    def test_daily_series_zero_fills(self):
        self.sell(1)
        series = metrics.daily_series(self.today - timedelta(days=6), self.today)
        self.assertEqual(len(series), 7)
        self.assertEqual(series[-1]['revenue'], 500.0)
        self.assertEqual(series[0]['revenue'], 0.0)

    def test_top_products_net_of_returns(self):
        sale = self.sell(3)
        process_return(sale, self.owner, {sale.items.get().pk: 3}, 'all back', 'CASH')
        self.assertEqual(metrics.top_products(self.today, self.today), [])


class ReportViewTests(MetricsTestBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)
        customer = Customer.objects.create(name='Fundi', phone_number='254711', credit_limit=10000)
        self.sell(2, payment_method='CREDIT', customer=customer)
        Expense.objects.create(branch=self.main, category='RENT', description='Oct rent', amount=300,
                               recorded_by=self.owner)

    def test_all_reports_render(self):
        for name in ('index', 'profit_and_loss', 'product_sales', 'staff_performance', 'debt_aging',
                     'reorder', 'vat'):
            with self.subTest(report=name):
                self.assertEqual(self.client.get(reverse(f'reports:{name}')).status_code, 200)

    def test_csv_exports(self):
        for name in ('product_sales', 'debt_aging', 'reorder', 'vat'):
            with self.subTest(report=name):
                res = self.client.get(reverse(f'reports:{name}'), {'export': 'csv'})
                self.assertEqual(res['Content-Type'], 'text/csv; charset=utf-8')

    def test_pnl_net_profit(self):
        res = self.client.get(reverse('reports:profit_and_loss'))
        self.assertEqual(res.context['net_profit'], Decimal('-100.00'))   # 200 gross profit - 300 rent

    def test_debt_aging_totals_match_balance(self):
        res = self.client.get(reverse('reports:debt_aging'))
        self.assertEqual(res.context['totals']['total'], Decimal('1000.00'))
        self.assertEqual(res.context['totals']['current'], Decimal('1000.00'))

    def test_cashier_cannot_see_reports(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse('reports:profit_and_loss')).status_code, 403)

    def test_dashboard_renders_for_each_role(self):
        for user in (self.owner, self.cashier):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('dashboard:index')).status_code, 200)

    def test_cashier_dashboard_hides_profit(self):
        self.client.force_login(self.cashier)
        self.assertNotContains(self.client.get(reverse('dashboard:index')), 'Gross profit today')


class DashboardAttentionTests(MetricsTestBase):
    def test_overdue_invoice_and_money_in_today(self):
        from datetime import timedelta
        from sales.invoices import create_invoice
        customer = Customer.objects.create(name='Late Payer', phone_number='254799', credit_limit=10000)
        sale = create_invoice(user=self.owner, raw_items=[{'product_id': self.pipe.pk, 'qty': 2}],
                              payment_method='CREDIT', customer=customer)
        Sale.objects.filter(pk=sale.pk).update(due_date=self.today - timedelta(days=5))
        self.sell(1)                                   # 500 cash in today
        self.client.force_login(self.owner)
        ctx = self.client.get(reverse('dashboard:index')).context
        titles = [a['title'] for a in ctx['attention']]
        self.assertIn('1 overdue invoice', titles)
        self.assertEqual(ctx['collected_today'], Decimal('500.00'))
        self.assertEqual(ctx['unpaid_invoices'], 1)
        self.assertEqual(ctx['unpaid_invoice_balance'], Decimal('1000.00'))

    def test_all_clear_when_nothing_pending(self):
        Stock.objects.update(quantity=100)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('dashboard:index')), 'All clear')
