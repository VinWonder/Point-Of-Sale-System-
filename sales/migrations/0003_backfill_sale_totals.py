from decimal import Decimal

from django.db import migrations


def backfill(apps, schema_editor):
    """Populate the new stored money fields for sales made before they existed."""
    Sale = apps.get_model('sales', 'Sale')
    SaleItem = apps.get_model('sales', 'SaleItem')
    Payment = apps.get_model('payments', 'Payment')

    for item in SaleItem.objects.select_related('product'):
        item.cost_price = item.product.cost_price
        item.save(update_fields=['cost_price'])

    for sale in Sale.objects.all():
        subtotal = sum(
            (i.quantity * i.unit_price for i in SaleItem.objects.filter(sale=sale)), Decimal('0.00')
        )
        paid = sum(
            (p.amount for p in Payment.objects.filter(sale=sale, status='SUCCESS')), Decimal('0.00')
        )
        sale.subtotal = subtotal
        sale.total = subtotal
        sale.tax_amount = (subtotal * Decimal('16') / Decimal('116')).quantize(Decimal('0.01'))
        sale.amount_paid = paid
        if sale.customer_id and paid < subtotal:
            sale.sale_type = 'CREDIT'
        sale.save(update_fields=['subtotal', 'total', 'tax_amount', 'amount_paid', 'sale_type'])


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0002_stored_totals_discounts_and_voids'),
        ('payments', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
