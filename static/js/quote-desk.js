/* Quotation Desk (Alpine.js). The server re-checks every price and quantity on save. */
(function () {
    const ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven',
        'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen'];
    const TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety'];

    function belowThousand(n) {
        const words = [];
        if (n >= 100) { words.push(ONES[Math.floor(n / 100)], 'Hundred'); n %= 100; if (n) words.push('and'); }
        if (n >= 20) words.push(TENS[Math.floor(n / 10)] + (n % 10 ? '-' + ONES[n % 10] : ''));
        else if (n) words.push(ONES[n]);
        return words.join(' ');
    }

    // Mirrors core/words.py so the draft prints the same wording as the saved quotation.
    function numberToWords(n) {
        if (n === 0) return 'Zero';
        const parts = [];
        for (const [value, name] of [[1e9, 'Billion'], [1e6, 'Million'], [1e3, 'Thousand']]) {
            if (n >= value) { parts.push(belowThousand(Math.floor(n / value)) + ' ' + name); n %= value; }
        }
        if (n) { if (parts.length && n < 100) parts.push('and'); parts.push(belowThousand(n)); }
        return parts.join(' ');
    }

    function getCookie(name) {
        const match = document.cookie.match('(^|;)\\s*' + name + '=([^;]*)');
        return match ? decodeURIComponent(match[2]) : '';
    }

    let rowKey = 0;
    function blankRow() {
        return { key: ++rowKey, product_id: null, query: '', results: [], active: 0, open: false,
                 qty: 1, unit_price: '', priceEdited: false, unit: '', list_price: null,
                 wholesale_price: null, wholesale_min_qty: 0, controller: null };
    }

    window.quoteDesk = function () {
        const config = JSON.parse(document.getElementById('desk-config').textContent);
        return {
            config,
            rows: [blankRow()],
            initialId: null,
            reference: config.nextReference + ' (on save)',
            saved: false,
            mode: 'walkin',
            customer: null, customerQuery: '', customerResults: [], customerLoading: false,
            customerName: '', customerPhone: '',
            notes: '',
            payMethod: 'CASH', dueDays: config.dueDays ?? 30, tendered: '', mpesaPhone: '',
            saving: false,
            error: '',

            init() {
                const initial = config.initial;
                if (initial) {
                    this.initialId = initial.id;
                    this.reference = initial.reference;
                    this.notes = initial.notes || '';
                    if (initial.customer) { this.mode = 'registered'; this.customer = initial.customer; }
                    else if (initial.customer_name) {
                        this.mode = 'named'; this.customerName = initial.customer_name; this.customerPhone = initial.customer_phone;
                    }
                    this.rows = initial.items.map(i => Object.assign(blankRow(), {
                        product_id: i.product_id, query: i.name, qty: i.qty, unit: i.unit, unit_price: i.unit_price,
                        list_price: i.list_price, wholesale_price: i.wholesale_price,
                        wholesale_min_qty: i.wholesale_min_qty, priceEdited: true,
                    }));
                    this.rows.push(blankRow());
                }
                this.$nextTick(() => {
                    const first = this.$root.querySelector(`[data-row="${this.firstEmpty()}"]`);
                    if (first) first.focus();
                });
                window.addEventListener('beforeunload', (e) => {
                    if (!this.saved && this.itemCount() && !this.saving) { e.preventDefault(); e.returnValue = ''; }
                });
            },

            // ---------- formatting ----------
            money(v) {
                return 'KES ' + Number(v || 0).toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            },
            dueDate(days) {
                const d = new Date();
                d.setDate(d.getDate() + days);
                return d.toLocaleDateString('en-GB');
            },
            words(total) {
                const shillings = Math.floor(total + 1e-9);
                const cents = Math.round((total - shillings) * 100);
                let text = 'Kenya Shillings ' + numberToWords(shillings);
                if (cents) text += ' and ' + numberToWords(cents) + ' Cents';
                return text + ' Only';
            },

            // ---------- customer ----------
            setMode(mode) { this.mode = mode; this.error = ''; },
            async searchCustomers() {
                const q = this.customerQuery.trim();
                if (q.length < 2) { this.customerResults = []; return; }
                this.customerLoading = true;
                const res = await fetch(`${config.urls.customers}?q=${encodeURIComponent(q)}`);
                this.customerResults = res.ok ? (await res.json()).results : [];
                this.customerLoading = false;
            },
            pickCustomer(c) { this.customer = c; this.customerResults = []; },

            // ---------- item lines ----------
            firstEmpty() { return this.rows.findIndex(r => !r.product_id); },
            focusNextEmpty() {
                const el = this.$root.querySelector(`[data-row="${this.firstEmpty()}"]`);
                if (el) el.focus();
            },
            itemCount() { return this.rows.filter(r => r.product_id).length; },
            fillerRows() { return Math.max(0, 10 - this.rows.length); },
            async searchProducts(row) {
                const q = row.query.trim();
                if (row.product_id && q !== row.pickedName) { row.product_id = null; }
                if (!q) { row.results = []; return; }
                if (row.controller) row.controller.abort();
                row.controller = new AbortController();
                try {
                    const res = await fetch(`${config.urls.products}?q=${encodeURIComponent(q)}`, { signal: row.controller.signal });
                    row.results = res.ok ? (await res.json()).results : [];
                    row.active = 0;
                    row.open = true;
                } catch (e) { /* superseded by a newer keystroke */ }
            },
            moveActive(row, step) {
                if (!row.results.length) return;
                row.active = (row.active + step + row.results.length) % row.results.length;
            },
            pickActive(row, index) {
                if (row.open && row.results[row.active]) this.pick(row, row.results[row.active], index);
            },
            pick(row, p, index) {
                const existing = this.rows.find(r => r !== row && r.product_id === p.id);
                if (existing) {
                    existing.qty += 1;
                    this.qtyChanged(existing);
                    Object.assign(row, blankRow(), { key: row.key });
                    return;
                }
                Object.assign(row, {
                    product_id: p.id, query: p.name, pickedName: p.name, unit: p.unit, list_price: p.price,
                    wholesale_price: p.wholesale_price, wholesale_min_qty: p.wholesale_min_qty,
                    qty: 1, priceEdited: false, open: false, results: [],
                });
                row.unit_price = this.tierPrice(row);
                if (index === this.rows.length - 1) this.rows.push(blankRow());
                // The units box is rendered by x-if after Alpine's next update, so focus it just after.
                setTimeout(() => {
                    const qty = this.$root.querySelector(`[data-qty="${row.key}"]`);
                    if (qty) { qty.focus(); qty.select(); }
                }, 30);
            },
            closeRow(row) {
                row.open = false;
                if (!row.product_id) row.query = '';
                else row.query = row.pickedName || row.query;
            },
            removeRow(index) {
                this.rows.splice(index, 1);
                if (!this.rows.some(r => !r.product_id)) this.rows.push(blankRow());
            },
            tierPrice(row) {
                const bulk = row.wholesale_price && row.wholesale_min_qty && row.qty >= row.wholesale_min_qty;
                return String(bulk ? row.wholesale_price : row.list_price);
            },
            qtyChanged(row) {
                if (!row.priceEdited) row.unit_price = this.tierPrice(row);
            },
            isNegotiated(row) { return Number(row.unit_price) < Number(this.tierPrice(row)); },
            priceHint(row) {
                if (this.config.role !== 'CASHIER') return 'List price ' + this.money(this.tierPrice(row));
                const floor = Number(this.tierPrice(row)) * (100 - this.config.maxDiscount) / 100;
                return `List ${this.money(this.tierPrice(row))} · lowest you can give ${this.money(floor)}`;
            },
            amount(row) { return (Number(row.qty) || 0) * (Number(row.unit_price) || 0); },
            total() { return this.rows.reduce((sum, r) => sum + (r.product_id ? this.amount(r) : 0), 0); },
            vat() { const rate = this.config.vatRate; return this.total() * rate / (100 + rate); },

            // ---------- save ----------
            clientPayload() {
                return {
                    customer_id: this.mode === 'registered' && this.customer ? this.customer.id : null,
                    customer_name: this.mode === 'named' ? this.customerName : '',
                    customer_phone: this.mode === 'named' ? this.customerPhone : '',
                    notes: this.notes,
                    items: this.rows.filter(r => r.product_id).map(r => ({
                        product_id: r.product_id, qty: parseInt(r.qty, 10), unit_price: r.unit_price,
                    })),
                };
            },
            checkClient() {
                if (this.mode === 'registered' && !this.customer) return 'Pick the registered customer, or switch to Walk-in.';
                if (this.mode === 'named' && !this.customerName.trim()) return "Enter the customer's name, or switch to Walk-in.";
                return '';
            },
            async issueInvoice() {
                this.error = this.checkClient();
                if (this.error) return;
                if (this.payMethod === 'CREDIT' && !(this.mode === 'registered' && this.customer)) {
                    this.error = 'On account needs a registered customer.'; return;
                }
                if (this.payMethod === 'MPESA' && !this.mpesaPhone.trim()) { this.error = 'Enter the M-Pesa number.'; return; }
                if (!confirm('Issue this invoice? Stock will be deducted.')) return;
                this.saving = true;
                const res = await fetch(config.urls.invoice, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
                    body: JSON.stringify({
                        ...this.clientPayload(), payment_method: this.payMethod, due_days: this.dueDays,
                        cash_tendered: this.payMethod === 'CASH' ? this.tendered : null,
                        mpesa_phone: this.payMethod === 'MPESA' ? this.mpesaPhone : '',
                    }),
                });
                const data = await res.json().catch(() => ({ error: 'Unexpected server response.' }));
                if (!res.ok) { this.error = data.error || 'Could not issue the invoice.'; this.saving = false; return; }
                this.saved = true;
                window.location.href = data.redirect;
            },
            async save(thenPay) {
                this.error = this.checkClient();
                if (this.error) return;
                this.saving = true;
                const res = await fetch(config.urls.save, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
                    body: JSON.stringify({ quotation_id: this.initialId, ...this.clientPayload() }),
                });
                const data = await res.json().catch(() => ({ error: 'Unexpected server response.' }));
                if (!res.ok) { this.error = data.error || 'Could not save the quotation.'; this.saving = false; return; }
                this.saved = true;
                window.location.href = `/sales/quotation/${data.quotation_id}/` + (thenPay ? '?pay=1#pay' : '');
            },
        };
    };
})();
