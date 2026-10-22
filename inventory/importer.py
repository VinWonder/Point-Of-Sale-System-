"""
Bulk product import from CSV. Rows are matched on SKU: existing products
are updated, new SKUs are created. Every row is validated before anything
is saved, so a bad file never half-imports.
"""
import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction

from branches.models import Branch
from .models import Category, Product, StockMovement
from .services import adjust_stock, available_quantity

COLUMNS = [
    'sku', 'name', 'barcode', 'brand', 'category', 'unit', 'cost_price', 'sell_price',
    'wholesale_price', 'wholesale_min_qty', 'reorder_level', 'branch', 'stock_quantity',
]
REQUIRED = ['sku', 'name', 'cost_price', 'sell_price']


def _decimal(value, field, errors, required=False):
    value = (value or '').strip().replace(',', '')
    if not value:
        if required:
            errors.append(f'{field} is required')
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        errors.append(f'{field} "{value}" is not a number')
        return None
    if number < 0:
        errors.append(f'{field} cannot be negative')
    return number


def _int(value, field, errors):
    value = (value or '').strip()
    if not value:
        return None
    if not value.isdigit():
        errors.append(f'{field} "{value}" must be a whole number')
        return None
    return int(value)


def parse(file_obj):
    """Return (rows, errors). Each row is a dict of cleaned values; errors are 'Row N: ...' strings."""
    raw = file_obj.read()
    text = raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in headers]
    if missing:
        return [], [f'Missing column(s): {", ".join(missing)}. Expected: {", ".join(COLUMNS)}']

    branches = {b.name.lower(): b for b in Branch.objects.all()}
    rows, errors, seen = [], [], set()
    for number, record in enumerate(reader, start=2):
        record = {(k or '').strip().lower(): (v or '').strip() for k, v in record.items()}
        if not any(record.values()):
            continue
        row_errors = []
        sku = record.get('sku', '')
        if not sku:
            row_errors.append('sku is required')
        elif sku.lower() in seen:
            row_errors.append(f'duplicate SKU {sku} in file')
        seen.add(sku.lower())
        if not record.get('name'):
            row_errors.append('name is required')

        cleaned = {
            'sku': sku, 'name': record.get('name', ''), 'barcode': record.get('barcode', ''),
            'brand': record.get('brand', ''), 'category': record.get('category', ''),
            'unit': record.get('unit') or 'pcs',
            'cost_price': _decimal(record.get('cost_price'), 'cost_price', row_errors, required=True),
            'sell_price': _decimal(record.get('sell_price'), 'sell_price', row_errors, required=True),
            'wholesale_price': _decimal(record.get('wholesale_price'), 'wholesale_price', row_errors),
            'wholesale_min_qty': _int(record.get('wholesale_min_qty'), 'wholesale_min_qty', row_errors) or 0,
            'reorder_level': _int(record.get('reorder_level'), 'reorder_level', row_errors),
            'stock_quantity': _int(record.get('stock_quantity'), 'stock_quantity', row_errors),
            'branch': None,
        }
        if record.get('branch'):
            cleaned['branch'] = branches.get(record['branch'].lower())
            if cleaned['branch'] is None:
                row_errors.append(f'unknown branch "{record["branch"]}"')
        if cleaned['stock_quantity'] is not None and cleaned['branch'] is None and not row_errors:
            row_errors.append('stock_quantity needs a branch column')
        if (cleaned['cost_price'] is not None and cleaned['sell_price'] is not None
                and cleaned['sell_price'] < cleaned['cost_price']):
            row_errors.append('sell_price is below cost_price')

        if row_errors:
            errors.append(f'Row {number} ({sku or "no SKU"}): ' + '; '.join(row_errors))
        else:
            rows.append(cleaned)
    if not rows and not errors:
        errors.append('The file has no product rows.')
    return rows, errors


@transaction.atomic
def import_rows(rows, user):
    """Create/update products and set stock. Returns (created, updated) counts."""
    created = updated = 0
    for row in rows:
        category = None
        if row['category']:
            category, _ = Category.objects.get_or_create(name=row['category'])
        defaults = {
            'name': row['name'], 'barcode': row['barcode'], 'brand': row['brand'], 'category': category,
            'unit': row['unit'], 'cost_price': row['cost_price'], 'sell_price': row['sell_price'],
            'wholesale_price': row['wholesale_price'], 'wholesale_min_qty': row['wholesale_min_qty'],
            'is_active': True,
        }
        if row['reorder_level'] is not None:
            defaults['reorder_level'] = row['reorder_level']
        product, was_created = Product.objects.update_or_create(sku=row['sku'], defaults=defaults)
        created += was_created
        updated += not was_created

        if row['branch'] is not None and row['stock_quantity'] is not None:
            delta = row['stock_quantity'] - available_quantity(product, row['branch'])
            if delta:
                adjust_stock(product, row['branch'], delta, StockMovement.Kind.ADJUSTMENT, user=user,
                             reference='CSV import', note='Stock set from product import')
    return created, updated
