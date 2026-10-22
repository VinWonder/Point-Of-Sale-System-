from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    sku = models.CharField(max_length=50, unique=True, help_text="Barcode / SKU code")
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    unit = models.CharField(max_length=30, default="pcs", help_text="e.g. pcs, kg, metre, bag")
    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    sell_price = models.DecimalField(max_digits=12, decimal_places=2)
    reorder_level = models.PositiveIntegerField(default=5, help_text="Alert when stock falls to/below this")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.sku})"


class Stock(models.Model):
    """Stock quantity of a product at a specific branch."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_levels")
    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE, related_name="stock_levels")
    quantity = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("product", "branch")

    def __str__(self):
        return f"{self.product} @ {self.branch}: {self.quantity}"

    @property
    def is_low(self):
        return self.quantity <= self.product.reorder_level


class Supplier(models.Model):
    name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name


class SupplierPurchase(models.Model):
    """A stock purchase from a supplier that increases branch stock."""

    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    is_paid = models.BooleanField(default=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product} x{self.quantity} from {self.supplier}"
