from decimal import Decimal

from django.db import models


class Customer(models.Model):
    class CustomerType(models.TextChoices):
        RETAIL = "RETAIL", "Retail / walk-in"
        CONTRACTOR = "CONTRACTOR", "Contractor / fundi"
        COMPANY = "COMPANY", "Company / institution"

    name = models.CharField(max_length=200)
    customer_type = models.CharField(max_length=20, choices=CustomerType.choices, default=CustomerType.RETAIL)
    phone_number = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True)
    kra_pin = models.CharField("KRA PIN", max_length=20, blank=True, help_text="Printed on invoices for companies")
    address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    credit_limit = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Max debt allowed before blocking new purchases on credit",
    )
    balance_owed = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_defaulter(self):
        """True if the customer owes more than their allowed credit limit."""
        return self.balance_owed > self.credit_limit

    @property
    def available_credit(self):
        return max(self.credit_limit - self.balance_owed, Decimal("0.00"))


class DebtPayment(models.Model):
    """A payment a customer makes to reduce their outstanding balance (not tied to one sale)."""

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        MPESA = "MPESA", "M-Pesa"
        BANK = "BANK", "Bank transfer"
        CHEQUE = "CHEQUE", "Cheque"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="debt_payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.CASH)
    reference = models.CharField(max_length=100, blank=True, help_text="M-Pesa code, cheque number, etc.")
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    branch = models.ForeignKey("branches.Branch", on_delete=models.SET_NULL, null=True, blank=True)
    received_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.customer} paid {self.amount} on {self.created_at:%Y-%m-%d}"
