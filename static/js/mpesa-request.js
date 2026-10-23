/* "Request M-Pesa payment" panel on the receipt: STK push for the balance, then poll until paid. */
function mpesaRequest(saleId, initialPhone, autoStart) {
    const csrf = (document.cookie.match('(^|;)\s*csrftoken=([^;]*)') || [])[2] || '';
    const post = (url, body) => fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrf },
        body,
    });
    return {
        phone: initialPhone, busy: false, message: '', error: false, paymentId: null,

        init() { if (autoStart && this.phone) this.send(); },

        async send() {
            this.busy = true; this.error = false; this.message = 'Sending prompt…';
            const res = await post(`/payments/mpesa/initiate/${saleId}/`, `phone_number=${encodeURIComponent(this.phone)}`);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) { this.fail(data.error || 'Could not send the M-Pesa prompt.'); return; }
            this.paymentId = data.payment_id;
            this.message = data.simulated ? 'Demo mode: pick the outcome below.' : 'Prompt sent — ask the customer to enter their M-Pesa PIN.';
            this.poll();
        },
        async poll() {
            for (let i = 0; i < 40; i++) {
                await new Promise(r => setTimeout(r, 3000));
                const res = await fetch(`/payments/mpesa/status/${this.paymentId}/`);
                const data = await res.json().catch(() => ({}));
                if (data.status === 'SUCCESS') { window.location.href = `/sales/receipt/${saleId}/?new=1`; return; }
                if (data.status === 'FAILED') { this.fail('Payment failed or was cancelled' + (data.message ? ': ' + data.message : '') + '. You can try again.'); return; }
            }
            this.fail('No confirmation yet. Refresh this page before trying again.');
        },
        async simulate(outcome) {
            await post(`/payments/mpesa/simulate/${this.paymentId}/`, `outcome=${outcome}`);
        },
        fail(msg) { this.busy = false; this.error = true; this.message = msg; this.paymentId = null; },
    };
}
