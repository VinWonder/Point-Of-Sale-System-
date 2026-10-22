from django.db import models


class Branch(models.Model):
    name = models.CharField(max_length=150)
    location = models.CharField(max_length=255, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class StockTransfer(models.Model):
    """Movement of stock from one branch to another."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        IN_TRANSIT = "IN_TRANSIT", "In Transit"
        RECEIVED = "RECEIVED", "Received"
        CANCELLED = "CANCELLED", "Cancelled"

    product = models.ForeignKey("inventory.Product", on_delete=models.CASCADE)
    from_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="transfers_out")
    to_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="transfers_in")
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    requested_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="transfers_requested"
    )
    received_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="transfers_received"
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.product} x{self.quantity}: {self.from_branch} -> {self.to_branch}"
