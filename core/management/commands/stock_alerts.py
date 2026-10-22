"""
Print items at or below their reorder level, grouped by branch.
Pipe it into email/SMS from cron, e.g.  python manage.py stock_alerts | mail -s "Low stock" owner@shop
"""
from django.core.management.base import BaseCommand
from django.db.models import F

from inventory.models import Stock


class Command(BaseCommand):
    help = 'List low and out-of-stock items per branch.'

    def add_arguments(self, parser):
        parser.add_argument('--branch', help='Only this branch (name)')

    def handle(self, *args, **options):
        stocks = Stock.objects.select_related('product', 'branch').filter(
            product__is_active=True, quantity__lte=F('product__reorder_level'),
        ).order_by('branch__name', 'quantity')
        if options['branch']:
            stocks = stocks.filter(branch__name__iexact=options['branch'])
        if not stocks:
            self.stdout.write(self.style.SUCCESS('All stock levels are above reorder level.'))
            return
        current = None
        for stock in stocks:
            if stock.branch_id != current:
                current = stock.branch_id
                self.stdout.write(self.style.MIGRATE_HEADING(f'\n{stock.branch.name}'))
            status = 'OUT ' if stock.quantity <= 0 else 'LOW '
            self.stdout.write(
                f'  {status} {stock.product.sku:<14} {stock.product.name:<40} '
                f'{stock.quantity:>5} {stock.product.unit} (reorder at {stock.product.reorder_level})'
            )
        self.stdout.write(f'\n{stocks.count()} item(s) need attention.')
