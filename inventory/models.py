from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    sku = models.CharField(max_length=50, unique=True, help_text="Internal SKU code")
    barcode = models.CharField(
        max_length=64, blank=True, db_index=True,
        help_text="Manufacturer barcode (EAN/UPC) for scanning at the till",
    )
    name = models.CharField(max_length=200)
    brand = models.CharField(max_length=100, blank=True, help_text="e.g. Bamburi, Crown, Stanley")
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    unit = models.CharField(max_length=30, default="pcs", help_text="e.g. pcs, kg, metre, bag")
    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    sell_price = models.DecimalField(max_digits=12, decimal_places=2)
    wholesale_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Discounted unit price for bulk buyers / contractors",
    )
    wholesale_min_qty = models.PositiveIntegerField(
        default=0, help_text="Quantity at which the wholesale price kicks in (0 = never)",
    )
    reorder_level = models.PositiveIntegerField(default=5, help_text="Alert when stock falls to/below this")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def price_for_quantity(self, quantity):
        """Unit price for a line of `quantity` units — wholesale once the bulk threshold is hit."""
        if self.wholesale_price and self.wholesale_min_qty and quantity >= self.wholesale_min_qty:
            return self.wholesale_price
        return self.sell_price

    @property
    def margin(self):
        return self.sell_price - self.cost_price

    @property
    def margin_percent(self):
        if not self.sell_price:
            return 0
        return round(self.margin / self.sell_price * 100, 1)


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
    contact_person = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    kra_pin = models.CharField("KRA PIN", max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

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
