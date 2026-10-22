import json
import logging
import uuid
from decimal import ROUND_CEILING

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.audit import log_action
from sales.models import Sale
from sales.services import mark_completed_if_paid
from .models import Payment
from .mpesa import InvalidPhoneNumber, normalize_phone, simulation_enabled

logger = logging.getLogger(__name__)


@login_required
@require_POST
def initiate_mpesa_payment(request, sale_id):
    """Trigger an STK push prompt on the customer's phone for this sale's balance."""
    sale = get_object_or_404(Sale, pk=sale_id)
    if sale.status == Sale.Status.VOIDED:
        return JsonResponse({'error': 'This sale has been voided.'}, status=400)

    try:
        phone_number = normalize_phone(request.POST.get('phone_number'))
    except InvalidPhoneNumber as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    amount = sale.balance_due
    if amount <= 0:
        return JsonResponse({'error': 'Nothing left to pay on this sale.'}, status=400)
    # M-Pesa only accepts whole shillings; round up so the sale is fully covered.
    whole_amount = int(amount.to_integral_value(rounding=ROUND_CEILING))

    payment = Payment.objects.create(
        sale=sale, method=Payment.Method.MPESA, amount=whole_amount,
        status=Payment.Status.PENDING, phone_number=phone_number, received_by=request.user,
    )

    if simulation_enabled():
        payment.checkout_request_id = f'SIM-{uuid.uuid4().hex[:16]}'
        payment.save(update_fields=['checkout_request_id'])
        return JsonResponse({
            'payment_id': payment.id, 'simulated': True,
            'status': 'Simulated STK push (no Daraja credentials configured).',
        })

    try:
        from django_daraja.mpesa.core import MpesaClient
        response = MpesaClient().stk_push(
            phone_number=phone_number,
            amount=whole_amount,
            account_reference=f"SALE-{sale.id}",
            transaction_desc=f"Payment for Sale #{sale.id}",
            callback_url=settings.MPESA_CALLBACK_URL,
        )
        checkout_request_id = getattr(response, 'checkout_request_id', '')
    except Exception:  # network errors, bad credentials, Daraja outages
        logger.exception('STK push failed for sale %s', sale.id)
        checkout_request_id = ''

    if not checkout_request_id:
        payment.status = Payment.Status.FAILED
        payment.result_description = 'Could not reach M-Pesa'
        payment.save(update_fields=['status', 'result_description'])
        return JsonResponse(
            {'error': 'Could not send the M-Pesa prompt. Check the number or take cash instead.'},
            status=502,
        )

    # Save the CheckoutRequestID so the callback can match it back to this payment
    payment.checkout_request_id = checkout_request_id
    payment.save(update_fields=['checkout_request_id'])
    return JsonResponse({'payment_id': payment.id, 'status': 'STK push sent, check your phone'})


def apply_mpesa_result(payment, result_code, receipt='', description=''):
    """Record the outcome of an STK push. Safe to call twice for the same payment."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status != Payment.Status.PENDING:
            return payment  # Safaricom retries callbacks; ignore repeats

        if result_code == 0:
            payment.status = Payment.Status.SUCCESS
            payment.mpesa_receipt_number = receipt
        else:
            payment.status = Payment.Status.FAILED
        payment.result_description = (description or '')[:255]
        payment.save()

        sale = Sale.objects.select_for_update().get(pk=payment.sale_id)
        sale.refresh_payment_status()
        mark_completed_if_paid(sale)
        sale.save(update_fields=['payment_status', 'amount_paid', 'status'])
    return payment


@csrf_exempt
@require_POST
def mpesa_callback(request):
    """
    Safaricom calls this URL directly (no login) once the customer has
    entered their M-Pesa PIN or cancelled/timed out.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Malformed payload'}, status=400)

    result = data.get('Body', {}).get('stkCallback', {})
    checkout_request_id = result.get('CheckoutRequestID')

    payment = Payment.objects.filter(checkout_request_id=checkout_request_id).first()
    if not checkout_request_id or payment is None:
        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Payment record not found, ignored'})

    items = result.get('CallbackMetadata', {}).get('Item', [])
    receipt = next((i.get('Value') for i in items if i.get('Name') == 'MpesaReceiptNumber'), '')
    apply_mpesa_result(payment, result.get('ResultCode'), str(receipt or ''), result.get('ResultDesc', ''))
    return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})


@login_required
def check_payment_status(request, payment_id):
    """Polled by the frontend while showing 'Check your phone...' screen."""
    payment = get_object_or_404(Payment, pk=payment_id)
    return JsonResponse({
        'status': payment.status,
        'receipt': payment.mpesa_receipt_number,
        'message': payment.result_description,
    })


@login_required
@require_POST
def simulate_mpesa_result(request, payment_id):
    """DEBUG-only stand-in for Safaricom's callback so the flow can be demoed offline."""
    if not simulation_enabled():
        return JsonResponse({'error': 'Simulation is only available in DEBUG without Daraja credentials.'},
                            status=404)
    payment = get_object_or_404(Payment, pk=payment_id, method=Payment.Method.MPESA)
    success = request.POST.get('outcome', 'success') == 'success'
    payment = apply_mpesa_result(
        payment, 0 if success else 1032,
        receipt=f'SIM{uuid.uuid4().hex[:7].upper()}' if success else '',
        description='Simulated payment' if success else 'Request cancelled by user (simulated)',
    )
    log_action(request.user, f'Simulated M-Pesa {payment.status.lower()} for sale #{payment.sale_id}', payment)
    return JsonResponse({'status': payment.status})
