from decimal import Decimal

from django.db import models
from django.utils import timezone


TWO_PLACES = Decimal("0.01")


def vat_portion(gross, rate):
    """VAT contained in a VAT-inclusive amount, e.g. 116 @ 16% -> 16.00."""
    if not rate:
        return Decimal("0.00")
    return (gross * rate / (Decimal("100") + rate)).quantize(TWO_PLACES)


class Quotation(models.Model):
    """A price quote given to a customer before they commit to buying."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        CONVERTED = "CONVERTED", "Converted to Sale"
        EXPIRED = "EXPIRED", "Expired"

    number = models.PositiveIntegerField(
        unique=True, null=True, editable=False, help_text="Sequential quotation number: 1, 2, 3...",
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True)
    customer_name = models.CharField(
        max_length=150, blank=True, help_text="Name for a walk-in customer who isn't registered",
    )
    customer_phone = models.CharField(max_length=20, blank=True)
    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE)
    created_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    valid_until = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.number is None:
            self.number = next_quotation_number()
        super().save(*args, **kwargs)

    @property
    def reference(self):
        return f"QT-{self.number:04d}" if self.number else f"QT-{self.pk}"

    @property
    def client_name(self):
        """What to print in 'Client details': registered customer, named walk-in, or Walk-in."""
        if self.customer_id:
            return self.customer.name
        return self.customer_name or "Walk-in customer"

    @property
    def client_phone(self):
        return self.customer.phone_number if self.customer_id else self.customer_phone

    @property
    def total(self):
        return sum((item.subtotal for item in self.items.all()), Decimal("0.00"))

    @property
    def is_expired(self):
        return bool(self.valid_until and self.valid_until < timezone.localdate())

    def __str__(self):
        return f"{self.reference} - {self.client_name}"


def next_invoice_number():
    """Next INV number; same locking approach as quotations."""
    from django.db import transaction
    from django.db.models import Max
    from core.models import ShopSettings

    with transaction.atomic():
        ShopSettings.objects.select_for_update().get_or_create(pk=1)
        return (Sale.objects.aggregate(m=Max("invoice_number"))["m"] or 0) + 1


def next_quotation_number():
    """
    Next number in the 1, 2, 3... sequence. Locks the single settings row so
    two tills saving at the same moment can't get the same number. Must run
    inside a transaction (Quotation.save is called from atomic blocks).
    """
    from django.db import transaction
    from django.db.models import Max
    from core.models import ShopSettings

    with transaction.atomic():
        ShopSettings.objects.select_for_update().get_or_create(pk=1)
        return (Quotation.objects.aggregate(m=Max("number"))["m"] or 0) + 1


class QuotationItem(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("inventory.Product", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price


class Sale(models.Model):
    """A completed sale/receipt, optionally converted from a quotation."""

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partially Paid"
        PAID = "PAID", "Paid"

    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", "Completed"
        PENDING_PAYMENT = "PENDING", "Awaiting payment"
        VOIDED = "VOIDED", "Voided"

    class SaleType(models.TextChoices):
        CASH = "CASH", "Cash / immediate"
        CREDIT = "CREDIT", "On account"

    quotation = models.ForeignKey(Quotation, on_delete=models.SET_NULL, null=True, blank=True)
    invoice_number = models.PositiveIntegerField(
        unique=True, null=True, blank=True, editable=False,
        help_text="Set when a formal invoice is issued: INV-0001, INV-0002...",
    )
    due_date = models.DateField(null=True, blank=True, help_text="When an invoice must be paid")
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True)
    customer_name = models.CharField(max_length=150, blank=True, help_text="Walk-in customer's name, if given")
    customer_phone = models.CharField(max_length=20, blank=True)
    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE)
    served_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COMPLETED)
    sale_type = models.CharField(max_length=10, choices=SaleType.choices, default=SaleType.CASH)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)

    # Money is stored, not recomputed, so reports can aggregate in the database.
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), help_text="VAT included in total",
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cash_tendered = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    voided_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="voided_sales"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def receipt_number(self):
        return f"R{self.branch_id:02d}-{self.pk:06d}" if self.pk else ""

    @property
    def invoice_reference(self):
        return f"INV-{self.invoice_number:04d}" if self.invoice_number else ""

    @property
    def is_overdue(self):
        return bool(
            self.due_date and self.due_date < timezone.localdate()
            and self.balance_due > 0 and self.status != self.Status.VOIDED
        )

    @property
    def client_name(self):
        if self.customer_id:
            return self.customer.name
        return self.customer_name or "Walk-in customer"

    @property
    def balance_due(self):
        return self.total - self.amount_paid

    @property
    def change_given(self):
        if self.cash_tendered is None:
            return Decimal("0.00")
        return max(self.cash_tendered - self.total, Decimal("0.00"))

    @property
    def cost_total(self):
        return sum((item.cost_price * item.quantity for item in self.items.all()), Decimal("0.00"))

    @property
    def gross_profit(self):
        return self.total - self.cost_total

    @property
    def is_voided(self):
        return self.status == self.Status.VOIDED

    def recalculate_totals(self, vat_rate=Decimal("0")):
        """Recompute subtotal/total/VAT from the line items. Call after items change."""
        self.subtotal = sum((item.subtotal for item in self.items.all()), Decimal("0.00"))
        self.discount_amount = min(self.discount_amount, self.subtotal)
        self.total = self.subtotal - self.discount_amount
        self.tax_amount = vat_portion(self.total, Decimal(vat_rate))

    def refresh_payment_status(self):
        """Derive payment_status/amount_paid from successful payments."""
        from payments.models import Payment
        paid = self.payments.filter(status=Payment.Status.SUCCESS).aggregate(
            s=models.Sum("amount"))["s"] or Decimal("0.00")
        self.amount_paid = paid
        if paid >= self.total:
            self.payment_status = self.PaymentStatus.PAID
        elif paid > 0:
            self.payment_status = self.PaymentStatus.PARTIAL
        else:
            self.payment_status = self.PaymentStatus.UNPAID

    def __str__(self):
        return f"Receipt #{self.pk} - {self.branch}"


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    cost_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Product cost at the time of sale, for accurate profit reports",
    )
    returned_quantity = models.PositiveIntegerField(default=0)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    @property
    def returnable_quantity(self):
        return self.quantity - self.returned_quantity


class SaleReturn(models.Model):
    """Goods brought back by a customer. Stock is restored and money refunded or credited."""

    class RefundMethod(models.TextChoices):
        CASH = "CASH", "Cash refund"
        MPESA = "MPESA", "M-Pesa refund"
        ACCOUNT = "ACCOUNT", "Credit to customer account"

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="returns")
    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE)
    refund_method = models.CharField(max_length=10, choices=RefundMethod.choices)
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255)
    processed_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Return #{self.pk} on sale #{self.sale_id}"


class SaleReturnItem(models.Model):
    sale_return = models.ForeignKey(SaleReturn, on_delete=models.CASCADE, related_name="items")
    sale_item = models.ForeignKey(SaleItem, on_delete=models.PROTECT, related_name="return_lines")
    quantity = models.PositiveIntegerField()
    restock = models.BooleanField(default=True, help_text="Untick for damaged goods that can't be resold")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
