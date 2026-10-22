from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from accounts.audit import log_action
from .forms import CustomerForm, DebtPaymentForm
from .models import Customer
from .services import DebtPaymentError, record_debt_payment


@login_required
def customer_list(request):
    customers = Customer.objects.all().order_by('name')
    return render(request, 'customers/customer_list.html', {
        'customers': customers,
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
            return redirect('customers:customer_list')
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
            return redirect('customers:customer_list')
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
