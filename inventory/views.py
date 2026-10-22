from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404

from accounts.decorators import role_required
from accounts.models import User
from .forms import ProductForm, SupplierPurchaseForm
from .models import Product, Stock, SupplierPurchase


@login_required
def product_list(request):
    products = Product.objects.filter(is_active=True).order_by('name')
    return render(request, 'inventory/product_list.html', {'products': products})


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
    """Stock levels across all branches (or filtered to the user's own branch)."""
    stocks = Stock.objects.select_related('product', 'branch').order_by('branch__name', 'product__name')
    if request.user.role == User.Role.CASHIER and request.user.branch_id:
        stocks = stocks.filter(branch=request.user.branch)
    return render(request, 'inventory/stock_list.html', {'stocks': stocks})


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

            stock, _ = Stock.objects.get_or_create(product=purchase.product, branch=purchase.branch)
            stock.quantity += purchase.quantity
            stock.save(update_fields=['quantity'])

            messages.success(request, f'Restocked {purchase.quantity} x {purchase.product.name} at {purchase.branch}.')
            return redirect('inventory:stock_list')
    else:
        form = SupplierPurchaseForm()
    return render(request, 'inventory/supplier_purchase_form.html', {'form': form})
