from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from .forms import CustomerForm, DebtPaymentForm
from .models import Customer, DebtPayment


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
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Customer added.')
            return redirect('customers:customer_list')
    else:
        form = CustomerForm()
    return render(request, 'customers/customer_form.html', {'form': form, 'title': 'Add Customer'})


@login_required
def customer_edit(request, customer_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, 'Customer updated.')
            return redirect('customers:customer_list')
    else:
        form = CustomerForm(instance=customer)
    return render(request, 'customers/customer_form.html', {'form': form, 'title': 'Edit Customer'})


@login_required
def record_debt_payment(request, customer_id):
    """Staff records a customer clearing part/all of their outstanding debt."""
    customer = get_object_or_404(Customer, pk=customer_id)
    if request.method == 'POST':
        form = DebtPaymentForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            DebtPayment.objects.create(customer=customer, amount=amount, received_by=request.user)
            customer.balance_owed = max(customer.balance_owed - amount, Decimal('0.00'))
            customer.save(update_fields=['balance_owed'])
            messages.success(request, f'Recorded KES {amount} payment from {customer.name}.')
    return redirect('customers:customer_list')
