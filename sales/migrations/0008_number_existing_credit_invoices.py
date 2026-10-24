from datetime import timedelta

from django.db import migrations


def number_credit_sales(apps, schema_editor):
    """Credit sales made before invoices existed get INV numbers in date order and a default due date."""
    Sale = apps.get_model('sales', 'Sale')
    ShopSettings = apps.get_model('core', 'ShopSettings')
    settings = ShopSettings.objects.filter(pk=1).first()
    due_days = settings.invoice_due_days if settings else 30
    credit = Sale.objects.filter(sale_type='CREDIT').order_by('created_at', 'pk')
    for number, sale in enumerate(credit, start=1):
        sale.invoice_number = number
        sale.due_date = sale.created_at.date() + timedelta(days=due_days)
        sale.save(update_fields=['invoice_number', 'due_date'])


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0007_invoice_number_and_due_date'),
        ('core', '0004_invoice_payment_details'),
    ]

    operations = [
        migrations.RunPython(number_credit_sales, migrations.RunPython.noop),
    ]
