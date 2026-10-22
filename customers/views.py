from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from accounts.audit import log_action
from core.utils import paginate
from sales.models import Sale
from .forms import CustomerForm, DebtPaymentForm
from .models import Customer
from .services import DebtPaymentError, record_debt_payment


@login_required
def customer_list(request):
    customers = Customer.objects.all()
    q = request.GET.get('q', '').strip()
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(phone_number__icontains=q) | Q(kra_pin__iexact=q))
    status = request.GET.get('status', '')
    if status == 'owing':
        customers = customers.filter(balance_owed__gt=0)
    elif status == 'blocked':
        customers = customers.filter(balance_owed__gt=F('credit_limit'))
    elif status == 'inactive':
        customers = customers.filter(is_active=False)
    ctype = request.GET.get('type', '')
    if ctype in Customer.CustomerType.values:
        customers = customers.filter(customer_type=ctype)

    totals = Customer.objects.aggregate(
        owed=Coalesce(Sum('balance_owed'), Value(Decimal('0.00'))),
        blocked=Count('id', filter=Q(balance_owed__gt=F('credit_limit'))),
    )
    return render(request, 'customers/customer_list.html', {
        'page_obj': paginate(request, customers.order_by('name')),
        'q': q, 'status': status, 'ctype': ctype,
        'types': Customer.CustomerType.choices,
        'totals': totals,
    })


@login_required
def customer_detail(request, customer_id):
    """Customer profile with an account statement (credit sales vs repayments, running balance)."""
    customer = get_object_or_404(Customer, pk=customer_id)
    sales = customer.sale_set.select_related('branch').order_by('-created_at')

    entries = [
        {'date': s.created_at, 'kind': 'sale', 'ref': s.receipt_number, 'obj': s,
         'debit': s.total, 'credit': Decimal('0.00')}
        for s in sales.filter(sale_type=Sale.SaleType.CREDIT).exclude(status=Sale.Status.VOIDED)
    ] + [
        {'date': p.created_at, 'kind': 'payment', 'ref': p.reference or p.get_method_display(), 'obj': p,
         'debit': Decimal('0.00'), 'credit': p.amount}
        for p in customer.debt_payments.select_related('received_by')
    ]
    entries.sort(key=lambda e: e['date'])
    running = Decimal('0.00')
    for e in entries:
        running += e['debit'] - e['credit']
        e['balance'] = running
    entries.reverse()

    stats = sales.exclude(status=Sale.Status.VOIDED).aggregate(
        spent=Coalesce(Sum('total'), Value(Decimal('0.00'))), count=Count('id'),
    )
    return render(request, 'customers/customer_detail.html', {
        'customer': customer,
        'statement': entries[:100],
        'recent_sales': sales[:10],
        'stats': stats,
        'payment_form': DebtPaymentForm(),
    })


@login_required
def customer_create(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST, user=request.user)
        if form.is_valid():
            customer = form.save()
            log_action(request.user, f'Added customer {customer.name}', customer)
            messages.success(request, 'Customer added.')
            return redirect('customers:customer_detail', customer_id=customer.id)
    else:
        form = CustomerForm(user=request.user)
    return render(request, 'customers/customer_form.html', {'form': form, 'title': 'Add Customer'})


@login_required
def customer_edit(request, customer_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    old_limit = customer.credit_limit
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer, user=request.user)
        if form.is_valid():
            form.save()
            if customer.credit_limit != old_limit:
                log_action(request.user, f'Changed credit limit of {customer.name}', customer,
                           f'{old_limit} -> {customer.credit_limit}')
            messages.success(request, 'Customer updated.')
            return redirect('customers:customer_detail', customer_id=customer.id)
    else:
        form = CustomerForm(instance=customer, user=request.user)
    return render(request, 'customers/customer_form.html', {'form': form, 'title': 'Edit Customer'})


@login_required
@require_POST
def record_debt_payment_view(request, customer_id):
    """Staff records a customer clearing part/all of their outstanding debt."""
    customer = get_object_or_404(Customer, pk=customer_id)
    form = DebtPaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Enter a valid amount.')
    else:
        try:
            record_debt_payment(
                customer, form.cleaned_data['amount'], request.user,
                method=form.cleaned_data['method'], reference=form.cleaned_data['reference'],
            )
            messages.success(request, f"Recorded KES {form.cleaned_data['amount']:,.2f} payment from {customer.name}.")
        except DebtPaymentError as exc:
            messages.error(request, str(exc))
    return redirect(request.POST.get('next') or 'customers:customer_list')
