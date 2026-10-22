import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from customers.models import Customer
from inventory.models import Product, Stock
from payments.models import Payment
from .models import Sale, SaleItem, Quotation, QuotationItem


@login_required
def pos_screen(request):
    products = Product.objects.filter(is_active=True)
    customers = Customer.objects.all().order_by('name')
    return render(request, 'sales/pos.html', {'products': products, 'customers': customers})


@login_required
@require_POST
@transaction.atomic
def create_sale(request):
    """
    Creates a Sale from the POS cart, enforcing:
    - customer defaulter block (cannot buy while balance_owed > credit_limit)
    - stock availability + deduction at the cashier's branch
    - immediate PAID status for cash, UNPAID pending confirmation for M-Pesa,
      or added straight to the customer's balance_owed for 'on account' credit sales
    """
    data = json.loads(request.body)
    customer_id = data.get('customer_id')
    items = data.get('items', [])
    payment_method = data.get('payment_method')  # CASH | MPESA | CREDIT

    if not items:
        return JsonResponse({'error': 'Cart is empty.'}, status=400)

    branch = request.user.branch
    if not branch:
        return JsonResponse({'error': 'Your account is not assigned to a branch. Contact your manager.'}, status=400)

    customer = None
    if customer_id:
        customer = get_object_or_404(Customer, pk=customer_id)
        if customer.is_defaulter:
            return JsonResponse({
                'error': f'{customer.name} owes KES {customer.balance_owed} and has exceeded their credit '
                         f'limit of KES {customer.credit_limit}. Settle the outstanding balance before a new sale.'
            }, status=403)

    # Validate stock availability up-front, before creating anything
    stocks = {}
    for line in items:
        product = get_object_or_404(Product, pk=line['product_id'])
        stock = Stock.objects.select_for_update().filter(product=product, branch=branch).first()
        available = stock.quantity if stock else 0
        if available < line['qty']:
            return JsonResponse({
                'error': f'Not enough stock for {product.name} at {branch.name} (available: {available}).'
            }, status=400)
        stocks[line['product_id']] = stock

    sale = Sale.objects.create(customer=customer, branch=branch, served_by=request.user)

    for line in items:
        product = get_object_or_404(Product, pk=line['product_id'])
        qty = line['qty']
        SaleItem.objects.create(sale=sale, product=product, quantity=qty, unit_price=product.sell_price)

        stock = stocks[line['product_id']]
        stock.quantity -= qty
        stock.save(update_fields=['quantity'])

    if payment_method == 'CASH':
        Payment.objects.create(sale=sale, method=Payment.Method.CASH, amount=sale.total, status=Payment.Status.SUCCESS)
        sale.payment_status = Sale.PaymentStatus.PAID
        sale.save(update_fields=['payment_status'])

    elif payment_method == 'CREDIT':
        if not customer:
            return JsonResponse({'error': 'A customer must be selected for credit/on-account sales.'}, status=400)
        customer.balance_owed += sale.total
        customer.save(update_fields=['balance_owed'])
        # payment_status stays UNPAID until the customer later pays down their balance

    # For MPESA: sale stays UNPAID; the frontend calls payments:mpesa_initiate next,
    # and the M-Pesa callback marks it PAID once Safaricom confirms.

    return JsonResponse({'sale_id': sale.id, 'total': str(sale.total), 'payment_method': payment_method})


@login_required
@require_POST
def create_quotation(request):
    """Creates a printable Quotation (no stock deduction — nothing has been sold yet)."""
    data = json.loads(request.body)
    customer_id = data.get('customer_id')
    items = data.get('items', [])

    if not items:
        return JsonResponse({'error': 'Cart is empty.'}, status=400)

    branch = request.user.branch
    customer = get_object_or_404(Customer, pk=customer_id) if customer_id else None

    quotation = Quotation.objects.create(customer=customer, branch=branch, created_by=request.user)
    for line in items:
        product = get_object_or_404(Product, pk=line['product_id'])
        QuotationItem.objects.create(
            quotation=quotation, product=product, quantity=line['qty'], unit_price=product.sell_price
        )

    return JsonResponse({'quotation_id': quotation.id})


@login_required
@transaction.atomic
def convert_quotation(request, quotation_id):
    """Customer accepted the quote — turn it into a real sale (stock deducted, defaulter-checked)."""
    quotation = get_object_or_404(Quotation, pk=quotation_id, status=Quotation.Status.DRAFT)

    if quotation.customer and quotation.customer.is_defaulter:
        from django.contrib import messages
        messages.error(request, f'{quotation.customer.name} has an outstanding balance. Settle it before converting this quotation to a sale.')
        return redirect('sales:quotation', quotation_id=quotation.id)

    sale = Sale.objects.create(
        quotation=quotation, customer=quotation.customer, branch=quotation.branch, served_by=request.user
    )
    for item in quotation.items.all():
        stock, _ = Stock.objects.get_or_create(product=item.product, branch=quotation.branch)
        stock.quantity -= item.quantity
        stock.save(update_fields=['quantity'])
        SaleItem.objects.create(sale=sale, product=item.product, quantity=item.quantity, unit_price=item.unit_price)

    quotation.status = Quotation.Status.CONVERTED
    quotation.save(update_fields=['status'])

    return redirect('sales:receipt', sale_id=sale.id)


@login_required
def receipt(request, sale_id):
    sale = get_object_or_404(Sale, pk=sale_id)
    return render(request, 'sales/receipt.html', {'sale': sale})


@login_required
def quotation_view(request, quotation_id):
    quotation = get_object_or_404(Quotation, pk=quotation_id)
    return render(request, 'sales/quotation.html', {'quotation': quotation})


@login_required
def sale_list(request):
    sales = Sale.objects.select_related('customer', 'branch').order_by('-created_at')[:100]
    return render(request, 'sales/sale_list.html', {'sales': sales})


@login_required
def quotation_list(request):
    quotations = Quotation.objects.select_related('customer', 'branch').order_by('-created_at')[:100]
    return render(request, 'sales/quotation_list.html', {'quotations': quotations})
