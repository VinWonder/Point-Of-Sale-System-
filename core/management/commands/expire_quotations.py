"""Mark draft quotations past their validity date as expired. Run daily (cron / Task Scheduler)."""
from django.core.management.base import BaseCommand
from django.utils import timezone

from sales.models import Quotation


class Command(BaseCommand):
    help = 'Mark quotations past their valid-until date as EXPIRED.'

    def handle(self, *args, **options):
        count = Quotation.objects.filter(
            status=Quotation.Status.DRAFT, valid_until__lt=timezone.localdate(),
        ).update(status=Quotation.Status.EXPIRED)
        self.stdout.write(self.style.SUCCESS(f'{count} quotation(s) expired.'))
