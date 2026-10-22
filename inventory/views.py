from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect, get_object_or_404

from accounts.audit import log_action
from accounts.decorators import role_required
from accounts.models import User
from .forms import ProductForm, StockAdjustmentForm, SupplierPurchaseForm
from core.utils import paginate
from .models import Category, Product, Stock, StockMovement, SupplierPurchase
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
            return redirect('inventory:stock_list')
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
