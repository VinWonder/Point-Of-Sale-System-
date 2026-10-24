import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.audit import log_action
from accounts.decorators import role_required
from accounts.models import User
from core.exports import csv_response
from core.filters import PRESETS, date_range_from_request, filter_by_date
from core.models import ShopSettings
from core.utils import paginate
from customers.models import Customer
from inventory.models import Category, Product, Stock
from payments.mpesa import InvalidPhoneNumber, normalize_phone, simulation_enabled
from registers.services import current_shift
from .models import Sale, SaleReturn, Quotation
from .quotations import save_quotation
from .services import SaleError, checkout, parse_lines, process_return, void_sale


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
        'open_shift': current_shift(request.user),
        'shift_required': settings.require_open_shift,
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
    if ShopSettings.load().require_open_shift and not current_shift(request.user):
        return JsonResponse({'error': 'Open your till shift before selling (Till > My Shift).'}, status=400)
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
    """Save a quotation from the POS cart or the Quotation Desk (no stock moves yet)."""
    try:
        data = _json_body(request)
        customer = None
        if data.get('customer_id'):
            customer = get_object_or_404(Customer, pk=data['customer_id'])
        quotation = None
        if data.get('quotation_id'):
            quotation = get_object_or_404(Quotation, pk=data['quotation_id'])
        quotation = save_quotation(
            user=request.user, raw_items=data.get('items', []), customer=customer,
            customer_name=data.get('customer_name', ''), customer_phone=data.get('customer_phone', ''),
            valid_days=data.get('valid_days'), notes=data.get('notes', ''), quotation=quotation,
        )
    except SaleError as exc:
        return JsonResponse({'error': str(exc)}, status=exc.status)
    return JsonResponse({'quotation_id': quotation.id, 'reference': quotation.reference})


@login_required
@require_POST
def convert_quotation(request, quotation_id):
    """Customer accepted the quote — turn it into a real sale at the quoted prices."""
    quotation = get_object_or_404(Quotation, pk=quotation_id, status=Quotation.Status.DRAFT)
    if quotation.is_expired:
        messages.error(request, 'This quotation has expired. Create a new one with current prices.')
        return redirect('sales:quotation', quotation_id=quotation.id)

    payment_method = request.POST.get('payment_method', 'CASH')
    mpesa_phone = ''
    if payment_method == 'MPESA':
        try:
            mpesa_phone = normalize_phone(request.POST.get('mpesa_phone'))
        except InvalidPhoneNumber as exc:
            messages.error(request, str(exc))
            return redirect(f"{reverse('sales:quotation', args=[quotation.id])}?pay=1")
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
                customer_name=quotation.customer_name, customer_phone=quotation.customer_phone,
                cash_tendered=request.POST.get('cash_tendered') if payment_method == 'CASH' else None,
            )
            quotation.status = Quotation.Status.CONVERTED
            quotation.save(update_fields=['status'])
    except SaleError as exc:
        messages.error(request, str(exc))
        return redirect('sales:quotation', quotation_id=quotation.id)

    messages.success(request, f'{quotation.reference} recorded as sale {sale.receipt_number}.')
    if payment_method == 'MPESA':
        return redirect(f"{reverse('sales:receipt', args=[sale.id])}?mpesa={mpesa_phone}")
    return redirect('sales:receipt', sale_id=sale.id)


@login_required
def receipt(request, sale_id):
    sale = get_object_or_404(
        Sale.objects.select_related('branch', 'customer', 'served_by'), pk=sale_id
    )
    phone = request.GET.get('mpesa') or (sale.customer.phone_number if sale.customer else sale.customer_phone)
    return render(request, 'sales/receipt.html', {
        'sale': sale,
        'mpesa_phone': phone,
        'mpesa_simulation': simulation_enabled(),
        'auto_mpesa': bool(request.GET.get('mpesa')),
    })


def _document_context(items, total):
    from .models import vat_portion
    return {
        'items': items,
        'total': total,
        'vat': vat_portion(total, ShopSettings.load().vat_rate),
        'filler_rows': range(max(0, 10 - len(items))),   # keep the printed grid the same height as the paper book
    }


@login_required
def quotation_view(request, quotation_id):
    quotation = get_object_or_404(
        Quotation.objects.select_related('customer', 'branch', 'created_by'), pk=quotation_id,
    )
    items = list(quotation.items.select_related('product'))
    can_sell = quotation.status == Quotation.Status.DRAFT and not quotation.is_expired
    return render(request, 'sales/quotation.html', {
        'quotation': quotation, 'can_sell': can_sell,
        'whatsapp_url': whatsapp_link(quotation, items),
        **_document_context(items, sum((i.subtotal for i in items), Decimal('0.00'))),
    })


def whatsapp_link(quotation, items):
    """wa.me link with the quotation as a message — how most fundis ask for prices."""
    from urllib.parse import quote as urlquote

    shop = ShopSettings.load()
    lines = [f"*{shop.business_name}*", f"Quotation {quotation.reference} for {quotation.client_name}"]
    lines.append('')
    for n, item in enumerate(items, start=1):
        lines.append(f"{n}. {item.product.name} - {item.quantity} {item.product.unit} x "
                     f"{item.unit_price:,.0f} = {item.subtotal:,.0f}")
    lines += ['', f"*TOTAL: KES {sum((i.subtotal for i in items), Decimal('0')):,.2f}*"]
    if shop.phone_number:
        lines.append(f"Call/WhatsApp: {shop.phone_number}")
    try:
        number = normalize_phone(quotation.client_phone) if quotation.client_phone else ''
    except InvalidPhoneNumber:
        number = ''
    return f"https://wa.me/{number}?text={urlquote(chr(10).join(lines))}"


@login_required
@require_POST
def quotation_requote(request, quotation_id):
    """Copy a quotation into a new one at today's prices (prices of cement and steel move often)."""
    original = get_object_or_404(Quotation, pk=quotation_id)
    items = [{'product_id': i.product_id, 'qty': i.quantity}
             for i in original.items.select_related('product') if i.product.is_active]
    try:
        quotation = save_quotation(
            user=request.user, raw_items=items, customer=original.customer,
            customer_name=original.customer_name, customer_phone=original.customer_phone,
            notes=original.notes,
        )
    except SaleError as exc:
        messages.error(request, str(exc))
        return redirect('sales:quotation', quotation_id=original.id)
    messages.success(request, f"{quotation.reference} created from {original.reference} at today's prices. Review and save.")
    return redirect('sales:quotation_edit', quotation_id=quotation.id)


@login_required
def sale_invoice(request, sale_id):
    """A4 invoice in the same layout as the quotation — for credit customers and companies."""
    sale = get_object_or_404(
        Sale.objects.select_related('customer', 'branch', 'served_by', 'quotation'), pk=sale_id,
    )
    items = list(sale.items.select_related('product'))
    context = _document_context(items, sale.subtotal)
    context.update({'sale': sale, 'payments': sale.payments.filter(status='SUCCESS')})
    return render(request, 'sales/invoice.html', context)


def filtered_sales(request):
    """Sales matching the history page filters. Cashiers only see their own branch."""
    start, end, preset = date_range_from_request(request)
    sales = filter_by_date(
        Sale.objects.select_related('customer', 'branch', 'served_by'), start, end,
    )
    branch = request.GET.get('branch', '')
    if request.user.role == User.Role.CASHIER:
        branch = str(request.user.branch_id or '')
    if branch.isdigit():
        sales = sales.filter(branch_id=branch)
    cashier = request.GET.get('cashier', '')
    if cashier.isdigit():
        sales = sales.filter(served_by_id=cashier)
    status = request.GET.get('status', '')
    if status in Sale.PaymentStatus.values:
        sales = sales.filter(payment_status=status).exclude(status=Sale.Status.VOIDED)
    elif status == 'VOIDED':
        sales = sales.filter(status=Sale.Status.VOIDED)
    sale_type = request.GET.get('type', '')
    if sale_type in Sale.SaleType.values:
        sales = sales.filter(sale_type=sale_type)
    q = request.GET.get('q', '').strip()
    if q:
        number = q.upper().split('-')[-1].lstrip('R0') or '0'
        query = Q(customer__name__icontains=q) | Q(customer__phone_number__icontains=q)             | Q(payments__mpesa_receipt_number__iexact=q)
        if number.isdigit():
            query |= Q(pk=int(number))
        sales = sales.filter(query).distinct()
    filters = {
        'start': start, 'end': end, 'preset': preset, 'current_branch': branch,
        'current_cashier': cashier, 'status': status, 'sale_type': sale_type, 'q': q,
    }
    return sales.order_by('-created_at'), filters


@login_required
def sale_list(request):
    from branches.models import Branch

    sales, filters = filtered_sales(request)
    live = sales.exclude(status=Sale.Status.VOIDED)
    totals = live.aggregate(
        revenue=Coalesce(Sum('total'), Value(Decimal('0.00'))),
        paid=Coalesce(Sum('amount_paid'), Value(Decimal('0.00'))),
        count=Count('id'),
    )
    totals['outstanding'] = totals['revenue'] - totals['paid']
    return render(request, 'sales/sale_list.html', {
        'page_obj': paginate(request, sales),
        'totals': totals,
        'branches': Branch.objects.order_by('name'),
        'cashiers': User.objects.filter(sale__isnull=False).distinct().order_by('username'),
        'date_presets': PRESETS,
        **filters,
    })


@login_required
def quotation_list(request):
    quotations = Quotation.objects.select_related('customer', 'branch', 'created_by').prefetch_related('items')
    if request.user.role == User.Role.CASHIER and request.user.branch_id:
        quotations = quotations.filter(branch_id=request.user.branch_id)
    status = request.GET.get('status', 'open')
    today = timezone.localdate()
    if status == 'open':
        quotations = quotations.filter(status=Quotation.Status.DRAFT).exclude(valid_until__lt=today)
    elif status == 'expired':
        quotations = quotations.filter(
            Q(status=Quotation.Status.EXPIRED) | Q(status=Quotation.Status.DRAFT, valid_until__lt=today)
        )
    elif status == 'converted':
        quotations = quotations.filter(status=Quotation.Status.CONVERTED)
    q = request.GET.get('q', '').strip()
    if q:
        query = Q(customer__name__icontains=q) | Q(customer__phone_number__icontains=q) | Q(notes__icontains=q)
        digits = q.upper().replace('QT', '').strip('-# ')
        if digits.isdigit():
            query |= Q(number=int(digits))
        query |= Q(customer_name__icontains=q) | Q(customer_phone__icontains=q)
        quotations = quotations.filter(query)
    return render(request, 'sales/quotation_list.html', {
        'page_obj': paginate(request, quotations.order_by('-created_at')),
        'status': status, 'q': q,
    })


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


@login_required
def sale_export(request):
    """Download the filtered sales history as CSV (for the accountant / KRA returns)."""
    sales, _ = filtered_sales(request)
    rows = (
        [
            s.receipt_number, timezone.localtime(s.created_at).strftime('%Y-%m-%d %H:%M'), s.branch.name,
            s.served_by.username if s.served_by else '', s.customer.name if s.customer else 'Walk-in',
            s.get_sale_type_display(), s.get_status_display(), s.get_payment_status_display(),
            s.subtotal, s.discount_amount, s.total, s.tax_amount, s.amount_paid, s.balance_due,
        ]
        for s in sales.iterator()
    )
    return csv_response('sales', [
        'Receipt', 'Date', 'Branch', 'Served by', 'Customer', 'Type', 'Status', 'Payment',
        'Subtotal', 'Discount', 'Total', 'VAT', 'Paid', 'Balance',
    ], rows)


@role_required(User.Role.OWNER, User.Role.MANAGER)
def sale_return_create(request, sale_id):
    """Pick the lines and quantities the customer is bringing back."""
    sale = get_object_or_404(Sale.objects.select_related('customer', 'branch'), pk=sale_id)
    items = list(sale.items.select_related('product'))
    if request.method == 'POST':
        quantities = {item.pk: request.POST.get(f'qty_{item.pk}') or 0 for item in items}
        restock = {item.pk: request.POST.get(f'restock_{item.pk}') == 'on' for item in items}
        try:
            sale_return = process_return(
                sale, request.user, quantities, request.POST.get('reason', ''),
                request.POST.get('refund_method', ''), restock=restock,
            )
        except SaleError as exc:
            messages.error(request, str(exc))
        else:
            how = sale_return.get_refund_method_display().lower()
            messages.success(request, f'Return recorded: KES {sale_return.refund_amount:,.2f} ({how}).')
            return redirect('sales:receipt', sale_id=sale.id)
    return render(request, 'sales/return_form.html', {
        'sale': sale, 'items': items, 'refund_methods': SaleReturn.RefundMethod.choices,
    })


@login_required
def quotation_desk(request, quotation_id=None):
    """
    Paper-style editor: build a quotation line by line, print it as a draft,
    save it (numbered QT-0001...), then record the sale when the customer pays.
    """
    from django.db.models import Max

    quotation, initial = None, None
    if quotation_id:
        quotation = get_object_or_404(Quotation.objects.select_related('customer'), pk=quotation_id)
        if quotation.status != Quotation.Status.DRAFT:
            messages.error(request, f'{quotation.reference} is {quotation.get_status_display().lower()} and can no longer be edited.')
            return redirect('sales:quotation', quotation_id=quotation.id)
        customer = quotation.customer
        initial = {
            'id': quotation.id,
            'reference': quotation.reference,
            'notes': quotation.notes,
            'customer': {
                'id': customer.id, 'name': customer.name, 'phone': customer.phone_number,
                'kra_pin': customer.kra_pin, 'address': customer.address,
                'balance': str(customer.balance_owed), 'available': str(customer.available_credit),
                'blocked': customer.is_defaulter,
            } if customer else None,
            'customer_name': quotation.customer_name,
            'customer_phone': quotation.customer_phone,
            'items': [
                {'product_id': i.product_id, 'name': i.product.name, 'sku': i.product.sku, 'unit': i.product.unit,
                 'qty': i.quantity, 'unit_price': str(i.unit_price), 'list_price': str(i.product.sell_price),
                 'wholesale_price': str(i.product.wholesale_price) if i.product.wholesale_price else None,
                 'wholesale_min_qty': i.product.wholesale_min_qty}
                for i in quotation.items.select_related('product')
            ],
        }
    settings = ShopSettings.load()
    next_number = (Quotation.objects.aggregate(m=Max('number'))['m'] or 0) + 1
    return render(request, 'sales/quotation_desk.html', {
        'quotation': quotation,
        'desk_config': {
            'initial': initial,
            'nextReference': f'QT-{next_number:04d}',
            'maxDiscount': float(settings.max_cashier_discount_percent),
            'role': request.user.role,
            'vatRate': float(settings.vat_rate),
            'urls': {
                'products': reverse('inventory:product_search_api'),
                'customers': reverse('customers:customer_search_api'),
                'save': reverse('sales:create_quotation'),
            },
        },
        'today': timezone.localdate(),
    })
