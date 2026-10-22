from django.db import models


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        MPESA = "MPESA", "M-Pesa"
        CARD = "CARD", "Card"
        BANK = "BANK", "Bank transfer"
        CHEQUE = "CHEQUE", "Cheque"
        CREDIT_NOTE = "CREDIT_NOTE", "Credit note (returned goods)"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    sale = models.ForeignKey("sales.Sale", on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=20, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reference = models.CharField(max_length=100, blank=True, help_text="Card slip / bank / cheque reference")
    received_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True)
    debt_payment = models.ForeignKey(
        "customers.DebtPayment", on_delete=models.CASCADE, null=True, blank=True, related_name="allocations",
        help_text="Set when this payment is a share of a customer's debt repayment",
    )

    # M-Pesa specific fields
    phone_number = models.CharField(max_length=20, blank=True)
    checkout_request_id = models.CharField(
        max_length=100, blank=True, db_index=True, help_text="From STK push response",
    )
    mpesa_receipt_number = models.CharField(max_length=50, blank=True)
    result_description = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.method} - {self.amount} - {self.status}"
