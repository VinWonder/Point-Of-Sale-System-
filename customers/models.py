from decimal import Decimal

from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True)
    credit_limit = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Max debt allowed before blocking new purchases on credit",
    )
    balance_owed = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

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

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="debt_payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    received_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer} paid {self.amount} on {self.created_at:%Y-%m-%d}"
