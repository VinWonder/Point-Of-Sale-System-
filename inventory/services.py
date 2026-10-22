"""
All stock level changes go through `adjust_stock` so that every change is
row-locked, validated against going negative, and written to the ledger.
"""
from django.db import transaction

from .models import Stock, StockMovement


class InsufficientStock(Exception):
    def __init__(self, product, branch, available, requested):
        self.product, self.branch = product, branch
        self.available, self.requested = available, requested
        super().__init__(
            f"Not enough stock for {product.name} at {branch.name} "
            f"(available: {available}, requested: {requested})."
        )


def available_quantity(product, branch):
    stock = Stock.objects.filter(product=product, branch=branch).only('quantity').first()
    return stock.quantity if stock else 0


@transaction.atomic
def adjust_stock(product, branch, delta, kind, user=None, reference='', note='', allow_negative=False):
    """
    Change stock of `product` at `branch` by `delta` (negative to remove).
    Raises InsufficientStock rather than letting the quantity drop below zero.
    """
    stock, _ = Stock.objects.select_for_update().get_or_create(product=product, branch=branch)
    new_quantity = stock.quantity + delta
    if new_quantity < 0 and not allow_negative:
        raise InsufficientStock(product, branch, stock.quantity, -delta)

    stock.quantity = new_quantity
    stock.save(update_fields=['quantity', 'updated_at'])
    StockMovement.objects.create(
        product=product, branch=branch, kind=kind, quantity=delta,
        balance_after=new_quantity, reference=reference, note=note,
        created_by=user if getattr(user, 'is_authenticated', False) else None,
    )
    return stock
