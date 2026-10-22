from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from accounts.decorators import role_required
from accounts.models import User
from inventory.models import Stock
from .forms import BranchForm, StockTransferForm
from .models import Branch, StockTransfer


@login_required
def branch_list(request):
    branches = Branch.objects.all().order_by('name')
    return render(request, 'branches/branch_list.html', {'branches': branches})


@role_required(User.Role.OWNER)
def branch_create(request):
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Branch added.')
            return redirect('branches:branch_list')
    else:
        form = BranchForm()
    return render(request, 'branches/branch_form.html', {'form': form, 'title': 'Add Branch'})


@role_required(User.Role.OWNER)
def branch_edit(request, branch_id):
    branch = get_object_or_404(Branch, pk=branch_id)
    if request.method == 'POST':
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            form.save()
            messages.success(request, 'Branch updated.')
            return redirect('branches:branch_list')
    else:
        form = BranchForm(instance=branch)
    return render(request, 'branches/branch_form.html', {'form': form, 'title': 'Edit Branch'})


@role_required(User.Role.OWNER, User.Role.MANAGER)
@transaction.atomic
def transfer_create(request):
    """Request moving stock from one branch to another. Deducts source branch immediately."""
    if request.method == 'POST':
        form = StockTransferForm(request.POST)
        if form.is_valid():
            transfer = form.save(commit=False)
            source_stock = Stock.objects.filter(
                product=transfer.product, branch=transfer.from_branch
            ).first()
            if not source_stock or source_stock.quantity < transfer.quantity:
                messages.error(request, 'Not enough stock at the source branch for this transfer.')
                return render(request, 'branches/transfer_form.html', {'form': form})

            source_stock.quantity -= transfer.quantity
            source_stock.save(update_fields=['quantity'])

            transfer.requested_by = request.user
            transfer.status = StockTransfer.Status.IN_TRANSIT
            transfer.save()

            messages.success(request, 'Stock transfer created and dispatched.')
            return redirect('branches:transfer_list')
    else:
        form = StockTransferForm()
    return render(request, 'branches/transfer_form.html', {'form': form})


@login_required
def transfer_list(request):
    transfers = StockTransfer.objects.select_related('product', 'from_branch', 'to_branch').order_by('-created_at')
    return render(request, 'branches/transfer_list.html', {'transfers': transfers})


@role_required(User.Role.OWNER, User.Role.MANAGER)
@transaction.atomic
def transfer_receive(request, transfer_id):
    """Destination branch confirms receipt — adds the stock to their side."""
    transfer = get_object_or_404(StockTransfer, pk=transfer_id, status=StockTransfer.Status.IN_TRANSIT)

    dest_stock, _ = Stock.objects.get_or_create(product=transfer.product, branch=transfer.to_branch)
    dest_stock.quantity += transfer.quantity
    dest_stock.save(update_fields=['quantity'])

    transfer.status = StockTransfer.Status.RECEIVED
    transfer.received_at = timezone.now()
    transfer.save(update_fields=['status', 'received_at'])

    messages.success(request, f'Received {transfer.quantity} x {transfer.product.name} at {transfer.to_branch}.')
    return redirect('branches:transfer_list')
