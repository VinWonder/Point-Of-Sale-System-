from decimal import Decimal

from django.db import models


class ShopSettings(models.Model):
    """Single-row, shop-wide configuration shown on receipts and used for tax maths."""

    business_name = models.CharField(max_length=150, default="Hardware Shop")
    tagline = models.CharField(max_length=200, blank=True, default="Quality tools & building materials")
    kra_pin = models.CharField("KRA PIN", max_length=20, blank=True)
    phone_number = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    currency = models.CharField(max_length=10, default="KES")
    vat_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("16.00"),
        help_text="VAT percentage. Selling prices are treated as VAT-inclusive.",
    )
    receipt_footer = models.CharField(
        max_length=255, blank=True,
        default="Goods once sold are not returnable without a receipt. Thank you!",
    )
    max_cashier_discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("5.00"),
        help_text="Largest discount a cashier may give without a manager.",
    )
    quotation_validity_days = models.PositiveIntegerField(default=14)
    require_open_shift = models.BooleanField(
        default=False, help_text="Cashiers must open a till shift (with a float) before they can sell.",
    )

    class Meta:
        verbose_name = "Shop settings"
        verbose_name_plural = "Shop settings"

    def __str__(self):
        return self.business_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
