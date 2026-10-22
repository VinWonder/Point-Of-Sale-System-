from decimal import Decimal

from django.db import models


class Shift(models.Model):
    """A cashier's session at the till, from opening float to cash-up."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE, related_name="shifts")
    cashier = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="shifts")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    opening_float = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    closing_notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-opened_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cashier"], condition=models.Q(status="OPEN"), name="one_open_shift_per_cashier",
            ),
        ]

    def __str__(self):
        return f"Shift #{self.pk} {self.cashier} @ {self.branch}"

    @property
    def variance(self):
        """Counted minus expected: negative means cash is short."""
        if self.counted_cash is None or self.expected_cash is None:
            return None
        return self.counted_cash - self.expected_cash


class Expense(models.Model):
    """Money spent by the branch — paid from the till (petty cash) or elsewhere."""

    class Category(models.TextChoices):
        TRANSPORT = "TRANSPORT", "Transport / delivery"
        LOADING = "LOADING", "Loading & casual labour"
        UTILITIES = "UTILITIES", "Electricity & water"
        RENT = "RENT", "Rent"
        SALARIES = "SALARIES", "Salaries & wages"
        SUPPLIES = "SUPPLIES", "Shop supplies"
        AIRTIME = "AIRTIME", "Airtime & internet"
        LICENSES = "LICENSES", "Licences & permits"
        REPAIRS = "REPAIRS", "Repairs & maintenance"
        OTHER = "OTHER", "Other"

    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE, related_name="expenses")
    category = models.CharField(max_length=20, choices=Category.choices)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_from_till = models.BooleanField(
        default=True, help_text="Cash taken from the till (reduces expected cash at cash-up)",
    )
    reference = models.CharField(max_length=100, blank=True, help_text="Receipt / M-Pesa code")
    recorded_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_category_display()}: {self.amount}"
