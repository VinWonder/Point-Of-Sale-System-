from django.db import migrations


def number_existing(apps, schema_editor):
    """Give quotations made before numbering existed QT-0001, QT-0002... in the order they were made."""
    Quotation = apps.get_model('sales', 'Quotation')
    for number, quotation in enumerate(Quotation.objects.order_by('created_at', 'pk'), start=1):
        quotation.number = number
        quotation.save(update_fields=['number'])


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0005_quotation_number_and_walk_in_names'),
    ]

    operations = [
        migrations.RunPython(number_existing, migrations.RunPython.noop),
    ]
