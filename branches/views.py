from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.audit import log_action
from accounts.decorators import role_required
from accounts.models import User
from inventory.models import StockMovement
from inventory.services import adjust_stock, InsufficientStock
from .forms import BranchForm, StockTransferForm
from .models import Branch, StockTransfer


@login_required
def branch_list(request):
    """Branches with today's takings, stock value and who is on duty."""
    from decimal import Decimal
    from django.db.models import Count, DecimalField, F, Q, Sum, Value
    from django.db.models.functions import Coalesce

    today = timezone.localdate()
    zero = Value(Decimal('0.00'), output_field=DecimalField(max_digits=14, decimal_places=2))
    branches = Branch.objects.annotate(
        staff_count=Count('staff', filter=Q(staff__is_active=True), distinct=True),
    ).order_by('-is_active', 'name')
    stats = {}
    for b in branches:
        stats[b.pk] = {
            'today': b.sale_set.filter(created_at__date=today).exclude(status='VOIDED').aggregate(
                s=Coalesce(Sum('total'), zero), n=Count('id')),
            'stock_value': b.stock_levels.filter(quantity__gt=0).aggregate(
                s=Coalesce(Sum(F('quantity') * F('product__cost_price'),
                               output_field=DecimalField(max_digits=14, decimal_places=2)), zero))['s'],
            'low': b.stock_levels.filter(quantity__lte=F('product__reorder_level'), product__is_active=True).count(),
            'open_tills': b.shifts.filter(status='OPEN').count(),
        }
    for b in branches:
        b.stats = stats[b.pk]
    return render(request, 'branches/branch_list.html', {'branches': branches})


@role_required(User.Role.OWNER)
def branch_create(request):
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            branch = form.save()
            log_action(request.user, f'Created branch {branch.name}', branch)
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
            log_action(request.user, f'Updated branch {branch.name}', branch)
            messages.success(request, 'Branch updated.')
            return redirect('branches:branch_list')
    else:
        form = BranchForm(instance=branch)
    return render(request, 'branches/branch_form.html', {'form': form, 'title': 'Edit Branch'})


def _can_act_for_branch(user, branch):
    """Owners act for any branch; managers only for their own."""
    return user.role == User.Role.OWNER or user.branch_id == branch.id


@role_required(User.Role.OWNER, User.Role.MANAGER)
def transfer_create(request):
    """Dispatch stock from one branch to another. Deducts the source branch immediately."""
    initial = {'from_branch': request.user.branch} if request.user.branch_id else {}
    if request.method == 'POST':
        form = StockTransferForm(request.POST)
        if form.is_valid():
            transfer = form.save(commit=False)
            if not _can_act_for_branch(request.user, transfer.from_branch):
                messages.error(request, 'Managers can only dispatch stock from their own branch.')
                return render(request, 'branches/transfer_form.html', {'form': form})
            try:
                with transaction.atomic():
                    transfer.requested_by = request.user
                    transfer.status = StockTransfer.Status.IN_TRANSIT
                    transfer.save()
                    adjust_stock(
                        transfer.product, transfer.from_branch, -transfer.quantity,
                        StockMovement.Kind.TRANSFER_OUT, user=request.user,
                        reference=f'Transfer #{transfer.pk}', note=f'To {transfer.to_branch}',
                    )
            except InsufficientStock as exc:
                messages.error(request, str(exc))
                return render(request, 'branches/transfer_form.html', {'form': form})

            log_action(request.user, f'Dispatched transfer #{transfer.pk}', transfer, str(transfer))
            messages.success(request, 'Stock transfer created and dispatched.')
            return redirect('branches:transfer_list')
    else:
        form = StockTransferForm(initial=initial)
    return render(request, 'branches/transfer_form.html', {'form': form})


@login_required
def transfer_list(request):
    transfers = StockTransfer.objects.select_related(
        'product', 'from_branch', 'to_branch', 'requested_by', 'received_by'
    ).order_by('-created_at')
    status = request.GET.get('status')
    if status in StockTransfer.Status.values:
        transfers = transfers.filter(status=status)
    return render(request, 'branches/transfer_list.html', {
        'transfers': transfers, 'statuses': StockTransfer.Status.choices, 'current_status': status,
    })


@role_required(User.Role.OWNER, User.Role.MANAGER)
@require_POST
@transaction.atomic
def transfer_receive(request, transfer_id):
    """Destination branch confirms receipt — adds the stock to their side."""
    transfer = get_object_or_404(
        StockTransfer.objects.select_for_update(), pk=transfer_id, status=StockTransfer.Status.IN_TRANSIT
    )
    if not _can_act_for_branch(request.user, transfer.to_branch):
        messages.error(request, 'Only the receiving branch can confirm this transfer.')
        return redirect('branches:transfer_list')

    adjust_stock(
        transfer.product, transfer.to_branch, transfer.quantity, StockMovement.Kind.TRANSFER_IN,
        user=request.user, reference=f'Transfer #{transfer.pk}', note=f'From {transfer.from_branch}',
    )
    transfer.status = StockTransfer.Status.RECEIVED
    transfer.received_at = timezone.now()
    transfer.received_by = request.user
    transfer.save(update_fields=['status', 'received_at', 'received_by'])

    log_action(request.user, f'Received transfer #{transfer.pk}', transfer)
    messages.success(request, f'Received {transfer.quantity} x {transfer.product.name} at {transfer.to_branch}.')
    return redirect('branches:transfer_list')


@role_required(User.Role.OWNER, User.Role.MANAGER)
@require_POST
@transaction.atomic
def transfer_cancel(request, transfer_id):
    """Call back a transfer that hasn't been received — the stock returns to the source branch."""
    transfer = get_object_or_404(
        StockTransfer.objects.select_for_update(), pk=transfer_id, status=StockTransfer.Status.IN_TRANSIT
    )
    if not _can_act_for_branch(request.user, transfer.from_branch):
        messages.error(request, 'Only the sending branch can cancel this transfer.')
        return redirect('branches:transfer_list')

    adjust_stock(
        transfer.product, transfer.from_branch, transfer.quantity, StockMovement.Kind.TRANSFER_CANCEL,
        user=request.user, reference=f'Transfer #{transfer.pk}', note='Transfer cancelled',
    )
    transfer.status = StockTransfer.Status.CANCELLED
    transfer.save(update_fields=['status'])

    log_action(request.user, f'Cancelled transfer #{transfer.pk}', transfer)
    messages.info(request, f'Transfer #{transfer.pk} cancelled and stock returned to {transfer.from_branch}.')
    return redirect('branches:transfer_list')
