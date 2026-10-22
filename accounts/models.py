from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom staff/user model with role-based access per branch."""

    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        MANAGER = "MANAGER", "Branch Manager"
        CASHIER = "CASHIER", "Cashier"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CASHIER)
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="staff",
    )
    phone_number = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.role})"

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER


class AuditLog(models.Model):
    """Tracks who did what, for accountability across branches."""

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=255)
    entity = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=50, blank=True)
    details = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} - {self.user} - {self.action}"
