import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.audit import log_action
from accounts.decorators import role_required
from accounts.models import User
from core.models import ShopSettings
from customers.models import Customer
from inventory.models import Category, Product, Stock
from payments.mpesa import simulation_enabled
from .models import Sale, Quotation, QuotationItem
from .services import SaleError, checkout, parse_lines, void_sale


def _json_body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        raise SaleError('Malformed request.')


@login_required
def pos_screen(request):
    """The till. Products carry this branch's stock so the cashier sees what can be sold."""
    branch = request.user.branch
    stock_by_product = dict(
        Stock.objects.filter(branch=branch).values_list('product_id', 'quantity')
    ) if branch else {}
    products = [
        {
            'id': p.id, 'name': p.name, 'sku': p.sku, 'barcode': p.barcode, 'brand': p.brand,
            'unit': p.unit, 'category': p.category_id,
            'price': float(p.sell_price),
            'wholesale_price': float(p.wholesale_price) if p.wholesale_price else None,
            'wholesale_min_qty': p.wholesale_min_qty,
            'stock': stock_by_product.get(p.id, 0),
        }
        for p in Product.objects.filter(is_active=True).order_by('name')
    ]
    customers = [
        {
            'id': c.id, 'name': c.name, 'phone': c.phone_number, 'type': c.get_customer_type_display(),
            'balance': float(c.balance_owed), 'limit': float(c.credit_limit),
            'available': float(c.available_credit), 'blocked': c.is_defaulter,
        }
        for c in Customer.objects.filter(is_active=True).order_by('name')
    ]
    categories = list(
        Category.objects.filter(product__is_active=True).distinct().order_by('name').values('id', 'name')
    )
    settings = ShopSettings.load()
    return render(request, 'sales/pos.html', {
        'products_data': products,
        'customers_data': customers,
        'categories_data': categories,
        'pos_config': {
            'maxCashierDiscount': float(settings.max_cashier_discount_percent),
            'isCashier': request.user.role == 'CASHIER',
            'mpesaSimulation': simulation_enabled(),
            'hasBranch': bool(branch),
        },
    })


@login_required
@require_POST
def create_sale(request):
    """
    Creates a Sale from the POS cart. All rules (defaulter block, credit
    limit, stock, discounts) are enforced in sales.services.checkout.
    """
    try:
        data = _json_body(request)
        customer = None
        if data.get('customer_id'):
            customer = get_object_or_404(Customer, pk=data['customer_id'])
        sale = checkout(
            user=request.user,
            branch=request.user.branch,
            raw_items=data.get('items', []),
            customer=customer,
            payment_method=data.get('payment_method'),
            discount=data.get('discount') or 0,
            cash_tendered=data.get('cash_tendered'),
            notes=data.get('notes', ''),
        )
    except SaleError as exc:
        return JsonResponse({'error': str(exc)}, status=exc.status)

    return JsonResponse({
        'sale_id': sale.id,
        'total': str(sale.total),
        'change': str(sale.change_given),
        'payment_method': data.get('payment_method'),
    })


@login_required
@require_POST
def create_quotation(request):
    """Creates a printable Quotation (no stock deduction — nothing has been sold yet)."""
    try:
        data = _json_body(request)
        if not request.user.branch_id:
            raise SaleError('Your account is not assigned to a branch. Contact your manager.')
        lines = parse_lines(data.get('items', []))
    except SaleError as exc:
        return JsonResponse({'error': str(exc)}, status=exc.status)

    customer_id = data.get('customer_id')
    customer = get_object_or_404(Customer, pk=customer_id) if customer_id else None
    validity = ShopSettings.load().quotation_validity_days

    with transaction.atomic():
        quotation = Quotation.objects.create(
            customer=customer, branch=request.user.branch, created_by=request.user,
            valid_until=timezone.localdate() + timedelta(days=validity),
            notes=str(data.get('notes', ''))[:255],
        )
        for product, qty in lines.items():
            QuotationItem.objects.create(
                quotation=quotation, product=product, quantity=qty,
                unit_price=product.price_for_quantity(qty),
            )
    log_action(request.user, f'Created quotation #{quotation.pk}', quotation)
    return JsonResponse({'quotation_id': quotation.id})


@login_required
@require_POST
def convert_quotation(request, quotation_id):
    """Customer accepted the quote — turn it into a real sale at the quoted prices."""
    quotation = get_object_or_404(Quotation, pk=quotation_id, status=Quotation.Status.DRAFT)
    if quotation.is_expired:
        messages.error(request, 'This quotation has expired. Create a new one with current prices.')
        return redirect('sales:quotation', quotation_id=quotation.id)

    payment_method = request.POST.get('payment_method', 'CASH')
    items = list(quotation.items.select_related('product'))
    lines = {}
    for item in items:
        lines[item.product] = lines.get(item.product, 0) + item.quantity
    prices = {item.product_id: item.unit_price for item in items}

    try:
        with transaction.atomic():
            sale = checkout(
                user=request.user, branch=quotation.branch, lines=lines, customer=quotation.customer,
                payment_method=payment_method, quotation=quotation, prices=prices,
            )
            quotation.status = Quotation.Status.CONVERTED
            quotation.save(update_fields=['status'])
    except SaleError as exc:
        messages.error(request, str(exc))
        return redirect('sales:quotation', quotation_id=quotation.id)

    messages.success(request, f'Quotation #{quotation.id} converted to sale #{sale.id}.')
    return redirect('sales:receipt', sale_id=sale.id)


@login_required
def receipt(request, sale_id):
    sale = get_object_or_404(
        Sale.objects.select_related('branch', 'customer', 'served_by'), pk=sale_id
    )
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


@role_required(User.Role.OWNER, User.Role.MANAGER)
@require_POST
def void_sale_view(request, sale_id):
    """Manager cancels a sale made in error. Stock is returned; credit charges reversed."""
    sale = get_object_or_404(Sale, pk=sale_id)
    try:
        void_sale(sale, request.user, request.POST.get('reason', ''))
    except SaleError as exc:
        messages.error(request, str(exc))
    else:
        sale.refresh_from_db()
        msg = f'Sale #{sale.id} voided and stock returned.'
        if sale.amount_paid:
            msg += f' Refund KES {sale.amount_paid:,.2f} to the customer.'
        messages.success(request, msg)
    return redirect('sales:receipt', sale_id=sale.id)
