import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from sales.models import Sale
from .models import Payment

# django-daraja handles OAuth + STK push request building for you.
# pip install django-daraja, then add 'django_daraja' to INSTALLED_APPS.
from django_daraja.mpesa.core import MpesaClient


@login_required
def initiate_mpesa_payment(request, sale_id):
    """Trigger an STK push prompt on the customer's phone for this sale's balance."""
    sale = get_object_or_404(Sale, pk=sale_id)
    phone_number = request.POST.get('phone_number')  # format: 2547XXXXXXXX
    amount = int(sale.balance_due)

    payment = Payment.objects.create(
        sale=sale,
        method=Payment.Method.MPESA,
        amount=amount,
        status=Payment.Status.PENDING,
        phone_number=phone_number,
    )

    cl = MpesaClient()
    response = cl.stk_push(
        phone_number=phone_number,
        amount=amount,
        account_reference=f"SALE-{sale.id}",
        transaction_desc=f"Payment for Sale #{sale.id}",
        callback_url=settings.MPESA_CALLBACK_URL,
    )

    # Save the CheckoutRequestID so the callback can match it back to this payment
    payment.checkout_request_id = response.checkout_request_id
    payment.save(update_fields=['checkout_request_id'])

    return JsonResponse({'payment_id': payment.id, 'status': 'STK push sent, check your phone'})


@csrf_exempt
def mpesa_callback(request):
    """
    Safaricom calls this URL directly (no login) once the customer has
    entered their M-Pesa PIN or cancelled/timed out.
    """
    data = json.loads(request.body)
    result = data.get('Body', {}).get('stkCallback', {})
    checkout_request_id = result.get('CheckoutRequestID')
    result_code = result.get('ResultCode')

    try:
        payment = Payment.objects.get(checkout_request_id=checkout_request_id)
    except Payment.DoesNotExist:
        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Payment record not found, ignored'})

    if result_code == 0:
        # Successful payment — pull out the M-Pesa receipt number from callback metadata
        items = result.get('CallbackMetadata', {}).get('Item', [])
        receipt = next((i['Value'] for i in items if i['Name'] == 'MpesaReceiptNumber'), '')
        payment.status = Payment.Status.SUCCESS
        payment.mpesa_receipt_number = receipt
    else:
        payment.status = Payment.Status.FAILED

    payment.save()

    # Update the sale's payment_status based on total paid so far
    sale = payment.sale
    if sale.balance_due <= 0:
        sale.payment_status = sale.PaymentStatus.PAID
    elif sale.amount_paid > 0:
        sale.payment_status = sale.PaymentStatus.PARTIAL
    sale.save(update_fields=['payment_status'])

    return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})


@login_required
def check_payment_status(request, payment_id):
    """Polled by the frontend while showing 'Check your phone...' screen."""
    payment = get_object_or_404(Payment, pk=payment_id)
    return JsonResponse({'status': payment.status, 'receipt': payment.mpesa_receipt_number})
