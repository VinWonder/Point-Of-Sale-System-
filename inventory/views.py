from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.audit import log_action
from accounts.decorators import role_required
from accounts.models import User
from .forms import CategoryForm, ProductForm, StockAdjustmentForm, SupplierForm, SupplierPurchaseForm
from core.utils import paginate
from .models import Category, Product, Stock, StockMovement, Supplier, SupplierPurchase
from .services import InsufficientStock, adjust_stock, available_quantity


@login_required
def product_list(request):
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    show = request.GET.get('show', 'active')

    products = Product.objects.select_related('category').annotate(
        total_stock=Coalesce(Sum('stock_levels__quantity'), Value(0)),
    )
    if show == 'active':
        products = products.filter(is_active=True)
    elif show == 'inactive':
        products = products.filter(is_active=False)
    if q:
        products = products.filter(
            Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__iexact=q) | Q(brand__icontains=q)
        )
    if category.isdigit():
        products = products.filter(category_id=category)

    return render(request, 'inventory/product_list.html', {
        'page_obj': paginate(request, products.order_by('name')),
        'categories': Category.objects.order_by('name'),
        'q': q, 'current_category': category, 'show': show,
    })


@login_required
def product_detail(request, product_id):
    """Everything about one product: stock at each branch and its movement history."""
    from sales.models import Sale, SaleItem

    product = get_object_or_404(Product.objects.select_related('category'), pk=product_id)
    stocks = product.stock_levels.select_related('branch').order_by('branch__name')
    movements = product.movements.select_related('branch', 'created_by')
    branch = request.GET.get('branch', '')
    if branch.isdigit():
        movements = movements.filter(branch_id=branch)

    sold = SaleItem.objects.filter(product=product).exclude(sale__status=Sale.Status.VOIDED).aggregate(
        qty=Coalesce(Sum('quantity'), Value(0)),
    )
    return render(request, 'inventory/product_detail.html', {
        'product': product,
        'stocks': stocks,
        'total_stock': sum(s.quantity for s in stocks),
        'page_obj': paginate(request, movements, per_page=20),
        'units_sold': sold['qty'],
        'current_branch': branch,
    })


@role_required(User.Role.OWNER, User.Role.MANAGER)
def product_create(request):
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product added.')
            return redirect('inventory:product_list')
    else:
        form = ProductForm()
    return render(request, 'inventory/product_form.html', {'form': form, 'title': 'Add Product'})


@role_required(User.Role.OWNER, User.Role.MANAGER)
def product_edit(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product updated.')
            return redirect('inventory:product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'inventory/product_form.html', {'form': form, 'title': 'Edit Product'})


@login_required
def stock_list(request):
    """Stock levels across branches, with value at cost and retail."""
    from branches.models import Branch

    stocks = Stock.objects.select_related('product', 'product__category', 'branch').filter(
        product__is_active=True,
    ).annotate(
        cost_value=F('quantity') * F('product__cost_price'),
        retail_value=F('quantity') * F('product__sell_price'),
    )
    branch = request.GET.get('branch', '')
    if request.user.role == User.Role.CASHIER and request.user.branch_id:
        branch = str(request.user.branch_id)
    if branch.isdigit():
        stocks = stocks.filter(branch_id=branch)
    q = request.GET.get('q', '').strip()
    if q:
        stocks = stocks.filter(Q(product__name__icontains=q) | Q(product__sku__icontains=q))
    level = request.GET.get('level', '')
    if level == 'low':
        stocks = stocks.filter(quantity__lte=F('product__reorder_level'), quantity__gt=0)
    elif level == 'out':
        stocks = stocks.filter(quantity__lte=0)

    totals = stocks.aggregate(
        cost=Coalesce(Sum('cost_value'), Value(0, output_field=DecimalField())),
        retail=Coalesce(Sum('retail_value'), Value(0, output_field=DecimalField())),
        units=Coalesce(Sum('quantity'), Value(0)),
    )
    return render(request, 'inventory/stock_list.html', {
        'page_obj': paginate(request, stocks.order_by('branch__name', 'product__name'), per_page=50),
        'branches': Branch.objects.filter(is_active=True).order_by('name'),
        'current_branch': branch, 'q': q, 'level': level, 'totals': totals,
    })


@role_required(User.Role.OWNER, User.Role.MANAGER)
@transaction.atomic
def supplier_purchase_create(request):
    """Recording a purchase from a supplier restocks the branch automatically."""
    if request.method == 'POST':
        form = SupplierPurchaseForm(request.POST)
        if form.is_valid():
            purchase = form.save(commit=False)
            purchase.created_by = request.user
            purchase.save()

            adjust_stock(
                purchase.product, purchase.branch, purchase.quantity, StockMovement.Kind.PURCHASE,
                user=request.user, reference=f'Purchase #{purchase.pk}',
                note=f'From {purchase.supplier}' if purchase.supplier else '',
            )
            # Keep the product's cost price in line with what we last paid
            if purchase.cost_price != purchase.product.cost_price:
                purchase.product.cost_price = purchase.cost_price
                purchase.product.save(update_fields=['cost_price', 'updated_at'])
            log_action(request.user, f'Restocked {purchase.quantity} x {purchase.product.name}', purchase)

            messages.success(request, f'Restocked {purchase.quantity} x {purchase.product.name} at {purchase.branch}.')
            if 'add_another' in request.POST:
                return redirect('inventory:supplier_purchase_create')
            return redirect('inventory:purchase_list')
    else:
        form = SupplierPurchaseForm()
    return render(request, 'inventory/supplier_purchase_form.html', {'form': form})


@role_required(User.Role.OWNER, User.Role.MANAGER)
def stock_adjust(request):
    """Manual stock correction with a mandatory reason, written to the movement ledger."""
    initial = {'product': request.GET.get('product'), 'branch': request.user.branch_id}
    form = StockAdjustmentForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        product, branch = data['product'], data['branch']
        if request.user.role == User.Role.MANAGER and branch.id != request.user.branch_id:
            messages.error(request, 'Managers can only adjust stock at their own branch.')
        else:
            current = available_quantity(product, branch)
            delta = data['quantity'] - current if data['mode'] == form.MODE_SET else data['quantity']
            if delta == 0:
                messages.info(request, f'{product.name} at {branch.name} is already {current}. Nothing changed.')
                return redirect('inventory:product_detail', product_id=product.id)
            note = data['reason'] + (f": {data['note']}" if data['note'] else '')
            try:
                stock = adjust_stock(
                    product, branch, delta, StockMovement.Kind.ADJUSTMENT,
                    user=request.user, reference='Manual adjustment', note=note,
                )
            except InsufficientStock as exc:
                messages.error(request, str(exc))
            else:
                log_action(request.user, f'Adjusted {product.name} at {branch.name} by {delta:+d}', stock, note)
                messages.success(request, f'{product.name} at {branch.name}: {current} → {stock.quantity}.')
                return redirect('inventory:product_detail', product_id=product.id)
    return render(request, 'inventory/stock_adjust.html', {'form': form})


@role_required(User.Role.OWNER, User.Role.MANAGER)
def category_list(request):
    """List categories and add new ones inline."""
    form = CategoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        category = form.save()
        messages.success(request, f'Category "{category.name}" added.')
        return redirect('inventory:category_list')
    categories = Category.objects.annotate(product_count=Count('product')).order_by('name')
    return render(request, 'inventory/category_list.html', {'categories': categories, 'form': form})


@role_required(User.Role.OWNER, User.Role.MANAGER)
def supplier_list(request):
    suppliers = Supplier.objects.annotate(
        purchase_count=Count('supplierpurchase'),
        unpaid=Coalesce(
            Sum(F('supplierpurchase__quantity') * F('supplierpurchase__cost_price'),
                filter=Q(supplierpurchase__is_paid=False)),
            Value(0, output_field=DecimalField()),
        ),
    ).order_by('name')
    return render(request, 'inventory/supplier_list.html', {'suppliers': suppliers})


@role_required(User.Role.OWNER, User.Role.MANAGER)
def supplier_form(request, supplier_id=None):
    supplier = get_object_or_404(Supplier, pk=supplier_id) if supplier_id else None
    form = SupplierForm(request.POST or None, instance=supplier)
    if request.method == 'POST' and form.is_valid():
        supplier = form.save()
        messages.success(request, f'Supplier {supplier.name} saved.')
        return redirect('inventory:supplier_list')
    return render(request, 'inventory/simple_form.html', {
        'form': form, 'title': 'Edit Supplier' if supplier else 'Add Supplier',
        'back_url': 'inventory:supplier_list',
    })


@role_required(User.Role.OWNER, User.Role.MANAGER)
def purchase_list(request):
    purchases = SupplierPurchase.objects.select_related('supplier', 'product', 'branch', 'created_by')
    supplier = request.GET.get('supplier', '')
    if supplier.isdigit():
        purchases = purchases.filter(supplier_id=supplier)
    if request.GET.get('unpaid'):
        purchases = purchases.filter(is_paid=False)
    return render(request, 'inventory/purchase_list.html', {
        'page_obj': paginate(request, purchases),
        'suppliers': Supplier.objects.order_by('name'),
        'current_supplier': supplier,
        'unpaid_only': bool(request.GET.get('unpaid')),
    })


@role_required(User.Role.OWNER, User.Role.MANAGER)
@require_POST
def purchase_mark_paid(request, purchase_id):
    purchase = get_object_or_404(SupplierPurchase, pk=purchase_id, is_paid=False)
    purchase.is_paid = True
    purchase.paid_at = timezone.now()
    purchase.save(update_fields=['is_paid', 'paid_at'])
    log_action(request.user, f'Marked purchase #{purchase.pk} as paid', purchase)
    messages.success(request, f'Purchase #{purchase.pk} marked as paid.')
    return redirect(request.POST.get('next') or 'inventory:purchase_list')


@login_required
def product_export(request):
    """Whole catalogue as CSV, in the same column layout the importer accepts."""
    from core.exports import csv_response
    from .importer import COLUMNS

    products = Product.objects.select_related('category').order_by('name')
    rows = (
        [p.sku, p.name, p.barcode, p.brand, p.category.name if p.category else '', p.unit,
         p.cost_price if request.user.role != User.Role.CASHIER else '', p.sell_price,
         p.wholesale_price or '', p.wholesale_min_qty, p.reorder_level, '', '']
        for p in products
    )
    return csv_response('products', COLUMNS, rows)


@role_required(User.Role.OWNER, User.Role.MANAGER)
def product_import(request):
    from . import importer

    errors, preview = [], None
    if request.method == 'POST' and request.FILES.get('file'):
        upload = request.FILES['file']
        if upload.size > 5 * 1024 * 1024:
            errors = ['File is too large (max 5 MB).']
        else:
            rows, errors = importer.parse(upload)
            if not errors:
                created, updated = importer.import_rows(rows, request.user)
                log_action(request.user, f'Imported products: {created} new, {updated} updated', None,
                           upload.name)
                messages.success(request, f'Import complete: {created} new products, {updated} updated.')
                return redirect('inventory:product_list')
    return render(request, 'inventory/product_import.html', {
        'errors': errors[:50], 'error_count': len(errors), 'columns': importer.COLUMNS, 'preview': preview,
    })


@role_required(User.Role.OWNER, User.Role.MANAGER)
def product_import_template(request):
    from core.exports import csv_response
    from .importer import COLUMNS

    return csv_response('product-import-template', COLUMNS, [
        ['CEM-BAM-50', 'Bamburi Cement 50kg', '', 'Bamburi', 'Cement & Building', 'bag',
         '680', '780', '750', '20', '20', 'Main Branch', '100'],
        ['PNT-CRN-4L', 'Crown Emulsion White 4L', '6161100000012', 'Crown', 'Paint', 'tin',
         '1500', '1850', '', '0', '5', '', ''],
    ])


@login_required
def shelf_labels(request):
    """Printable shelf-edge price labels with scannable barcodes."""
    products = Product.objects.filter(is_active=True).select_related('category').order_by('category__name', 'name')
    category = request.GET.get('category', '')
    if category.isdigit():
        products = products.filter(category_id=category)
    q = request.GET.get('q', '').strip()
    if q:
        products = products.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(brand__icontains=q))
    return render(request, 'inventory/shelf_labels.html', {
        'products': products[:300],
        'categories': Category.objects.order_by('name'),
        'current_category': category, 'q': q,
    })


@login_required
def product_search_api(request):
    """
    Type-ahead search for quotation/invoice lines. Exact SKU or barcode hits
    come first, then names starting with the text, then any other match.
    """
    from django.db.models import Case, IntegerField, When
    from django.http import JsonResponse

    q = request.GET.get('q', '').strip()
    if len(q) < 1:
        return JsonResponse({'results': []})
    products = (
        Product.objects.filter(is_active=True)
        .filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode=q) | Q(brand__icontains=q))
        .annotate(rank=Case(
            When(Q(sku__iexact=q) | Q(barcode=q), then=0),
            When(name__istartswith=q, then=1),
            default=2, output_field=IntegerField(),
        ))
        .order_by('rank', 'name')[:15]
    )
    stock = dict(Stock.objects.filter(
        branch_id=request.user.branch_id, product__in=products,
    ).values_list('product_id', 'quantity')) if request.user.branch_id else {}
    return JsonResponse({'results': [
        {
            'id': p.id, 'name': p.name, 'sku': p.sku, 'brand': p.brand, 'unit': p.unit,
            'price': str(p.sell_price),
            'wholesale_price': str(p.wholesale_price) if p.wholesale_price else None,
            'wholesale_min_qty': p.wholesale_min_qty,
            'stock': stock.get(p.id, 0),
        }
        for p in products
    ]})
