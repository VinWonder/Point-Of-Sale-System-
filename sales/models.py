from decimal import Decimal

from django.db import models


class Quotation(models.Model):
    """A price quote given to a customer before they commit to buying."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        CONVERTED = "CONVERTED", "Converted to Sale"
        EXPIRED = "EXPIRED", "Expired"

    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True)
    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE)
    created_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def total(self):
        return sum((item.subtotal for item in self.items.all()), Decimal("0.00"))

    def __str__(self):
        return f"Quotation #{self.pk} - {self.customer or 'Walk-in'}"


class QuotationItem(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("inventory.Product", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price


class Sale(models.Model):
    """A completed (or in-progress) sale/receipt, optionally converted from a quotation."""

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partially Paid"
        PAID = "PAID", "Paid"

    quotation = models.ForeignKey(Quotation, on_delete=models.SET_NULL, null=True, blank=True)
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True)
    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE)
    served_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def total(self):
        return sum((item.subtotal for item in self.items.all()), Decimal("0.00"))

    @property
    def amount_paid(self):
        return sum((p.amount for p in self.payments.all()), Decimal("0.00"))

    @property
    def balance_due(self):
        return self.total - self.amount_paid

    def __str__(self):
        return f"Receipt #{self.pk} - {self.branch}"


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("inventory.Product", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price
