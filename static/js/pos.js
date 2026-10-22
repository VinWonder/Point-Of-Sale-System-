/* Point-of-sale cart (Alpine.js component).
 * Prices shown here are a preview — the server recalculates everything
 * (wholesale tiers, discount limits, stock, credit) when the sale is posted.
 */
function readJSON(id) {
    const el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
}

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
}

const HELD_KEY = 'pos.heldSales';

function posCart() {
    return {
        products: readJSON('products-data') || [],
        customers: readJSON('customers-data') || [],
        categories: readJSON('categories-data') || [],
        config: readJSON('pos-config') || {},

        search: '',
        category: null,
        cart: [],
        customer: null,
        customerSearch: '',
        showCustomers: false,
        discount: 0,
        method: 'CASH',
        tendered: null,
        phone: '',
        held: [],
        loading: false,
        statusMessage: '',
        errorMessage: '',
        pendingPaymentId: null,
        pendingSaleId: null,

        init() {
            try { this.held = JSON.parse(localStorage.getItem(HELD_KEY) || '[]'); } catch (e) { this.held = []; }
            this.$nextTick(() => this.$refs.search.focus());
            window.addEventListener('keydown', (e) => {
                if (e.key === 'F3') { e.preventDefault(); this.$refs.search.focus(); this.$refs.search.select(); }
                if (e.key === 'F4') { e.preventDefault(); this.checkout(); }
            });
        },

        // ---------- formatting ----------
        money(n) {
            const v = Number(n || 0);
            return 'KES ' + v.toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        },

        // ---------- product search ----------
        filteredProducts() {
            const q = this.search.trim().toLowerCase();
            return this.products.filter(p => {
                if (this.category !== null && p.category !== this.category) return false;
                if (!q) return true;
                return p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q)
                    || (p.barcode && p.barcode.toLowerCase() === q)
                    || (p.brand && p.brand.toLowerCase().includes(q));
            }).slice(0, 200);
        },
        scanOrAddFirst() {
            // Barcode scanners type the code then press Enter: exact SKU/barcode wins.
            const q = this.search.trim().toLowerCase();
            if (!q) return;
            const exact = this.products.find(p => p.sku.toLowerCase() === q || (p.barcode && p.barcode.toLowerCase() === q));
            const matches = this.filteredProducts();
            const target = exact || (matches.length === 1 ? matches[0] : null);
            if (target) {
                this.addItem(target);
                this.search = '';
            } else if (!matches.length) {
                this.flashError(`No product with code "${this.search}".`);
            }
        },

        // ---------- cart ----------
        addItem(p) {
            this.errorMessage = '';
            if (p.stock <= 0) { this.flashError(`${p.name} is out of stock at this branch.`); return; }
            const existing = this.cart.find(i => i.id === p.id);
            if (existing) {
                if (existing.qty >= p.stock) { this.flashError(`Only ${p.stock} ${p.unit} of ${p.name} in stock.`); return; }
                existing.qty += 1;
            } else {
                this.cart.push({ ...p, qty: 1 });
            }
        },
        changeQty(item, delta) {
            item.qty = Math.max(1, (parseInt(item.qty, 10) || 1) + delta);
            this.clampQty(item);
        },
        clampQty(item) {
            let q = parseInt(item.qty, 10);
            if (!q || q < 1) q = 1;
            if (q > item.stock) { q = item.stock; this.flashError(`Only ${item.stock} ${item.unit} of ${item.name} in stock.`); }
            item.qty = q;
        },
        removeItem(id) { this.cart = this.cart.filter(i => i.id !== id); },
        clearCart() {
            if (this.cart.length && !confirm('Clear the cart?')) return;
            this.resetSale();
        },
        resetSale() {
            this.cart = []; this.customer = null; this.customerSearch = ''; this.discount = 0;
            this.tendered = null; this.phone = ''; this.method = 'CASH';
            this.errorMessage = ''; this.statusMessage = ''; this.pendingPaymentId = null;
        },
        isWholesale(item) {
            return item.wholesale_price && item.wholesale_min_qty && item.qty >= item.wholesale_min_qty;
        },
        unitPrice(item) { return this.isWholesale(item) ? item.wholesale_price : item.price; },
        lineTotal(item) { return this.unitPrice(item) * item.qty; },
        itemCount() { return this.cart.reduce((n, i) => n + (parseInt(i.qty, 10) || 0), 0); },
        subtotal() { return this.cart.reduce((s, i) => s + this.lineTotal(i), 0); },
        total() { return Math.max(this.subtotal() - (Number(this.discount) || 0), 0); },
        quickCash() {
            const t = Math.ceil(this.total());
            if (!t) return [];
            const options = new Set([t]);
            [100, 500, 1000].forEach(step => options.add(Math.ceil(t / step) * step));
            return [...options].sort((a, b) => a - b).slice(0, 4);
        },

        // ---------- customers ----------
        filteredCustomers() {
            const q = this.customerSearch.trim().toLowerCase();
            if (!q) return [];
            return this.customers.filter(c => c.name.toLowerCase().includes(q) || c.phone.includes(q)).slice(0, 8);
        },
        selectCustomer(c) {
            this.customer = c;
            this.showCustomers = false;
            if (c.blocked) this.flashError(`${c.name} is over their credit limit and cannot buy until they pay.`);
        },
        prefillPhone() { if (!this.phone && this.customer) this.phone = this.customer.phone; },

        // ---------- held sales ----------
        holdSale() {
            const label = this.customer ? this.customer.name : `Walk-in ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
            this.held.push({ at: Date.now(), label, total: this.total(), cart: this.cart, customer: this.customer, discount: this.discount });
            this.persistHeld();
            this.resetSale();
            this.statusMessage = `Sale held as "${label}".`;
        },
        recallSale(idx) {
            if (this.cart.length && !confirm('Replace the current cart with the held sale?')) return;
            const h = this.held.splice(idx, 1)[0];
            this.persistHeld();
            // Refresh stock numbers from the latest product list
            this.cart = h.cart.map(i => ({ ...i, stock: (this.products.find(p => p.id === i.id) || i).stock }));
            this.customer = h.customer;
            this.discount = h.discount || 0;
            this.statusMessage = '';
        },
        persistHeld() {
            try { localStorage.setItem(HELD_KEY, JSON.stringify(this.held)); } catch (e) { /* storage full or blocked */ }
        },

        // ---------- server calls ----------
        flashError(msg) { this.errorMessage = msg; this.statusMessage = ''; },
        payload() {
            return {
                customer_id: this.customer ? this.customer.id : null,
                items: this.cart.map(i => ({ product_id: i.id, qty: parseInt(i.qty, 10) })),
                discount: Number(this.discount) || 0,
            };
        },
        async postJSON(url, body) {
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
                body: JSON.stringify(body),
            });
            let data = {};
            try { data = await res.json(); } catch (e) { data = { error: 'Unexpected server response.' }; }
            return { ok: res.ok, data };
        },
        async saveQuotation() {
            this.errorMessage = ''; this.statusMessage = '';
            if (!this.cart.length) { this.flashError('Cart is empty.'); return; }
            this.loading = true;
            const { data } = await this.postJSON(window.POS_URLS.createQuotation, this.payload());
            this.loading = false;
            if (data.quotation_id) window.location.href = `/sales/quotation/${data.quotation_id}/`;
            else this.flashError(data.error || 'Could not save quotation.');
        },
        async checkout() {
            if (this.loading) return;
            this.errorMessage = ''; this.statusMessage = '';
            if (!this.cart.length) { this.flashError('Cart is empty.'); return; }
            if (this.method === 'CREDIT' && !this.customer) { this.flashError('Attach a customer for a credit/account sale.'); return; }
            if (this.method === 'MPESA' && !this.phone) { this.flashError('Enter the phone number to send the M-Pesa prompt to.'); return; }
            if (this.method === 'CASH' && this.tendered && this.tendered < this.total()) {
                this.flashError('Cash tendered is less than the total.'); return;
            }

            this.loading = true;
            const body = { ...this.payload(), payment_method: this.method };
            if (this.method === 'CASH' && this.tendered) body.cash_tendered = this.tendered;
            const { ok, data } = await this.postJSON(window.POS_URLS.createSale, body);
            if (!ok) { this.flashError(data.error || 'Sale could not be completed.'); this.loading = false; return; }

            if (this.method === 'MPESA') {
                await this.startMpesa(data.sale_id);
            } else {
                window.location.href = `/sales/receipt/${data.sale_id}/?new=1`;
            }
        },
        async startMpesa(saleId) {
            this.pendingSaleId = saleId;
            this.statusMessage = 'Sending M-Pesa prompt… ask the customer to check their phone.';
            const res = await fetch(`/payments/mpesa/initiate/${saleId}/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': getCookie('csrftoken') },
                body: `phone_number=${encodeURIComponent(this.phone)}`,
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                this.flashError((data.error || 'Could not send the M-Pesa prompt.') + ` Sale #${saleId} is saved as awaiting payment.`);
                this.loading = false;
                return;
            }
            this.pendingPaymentId = data.payment_id;
            if (data.simulated) this.statusMessage = 'Demo mode: choose the payment outcome below.';
            await this.pollPaymentStatus(data.payment_id, saleId);
        },
        async simulate(outcome) {
            if (!this.pendingPaymentId) return;
            await fetch(`/payments/mpesa/simulate/${this.pendingPaymentId}/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': getCookie('csrftoken') },
                body: `outcome=${outcome}`,
            });
        },
        async pollPaymentStatus(paymentId, saleId) {
            for (let i = 0; i < 40; i++) {
                await new Promise(r => setTimeout(r, 3000));
                const res = await fetch(`/payments/mpesa/status/${paymentId}/`);
                const data = await res.json().catch(() => ({}));
                if (data.status === 'SUCCESS') {
                    window.location.href = `/sales/receipt/${saleId}/?new=1`;
                    return;
                } else if (data.status === 'FAILED') {
                    this.pendingPaymentId = null;
                    this.flashError(`M-Pesa payment failed${data.message ? ': ' + data.message : ''}. Sale #${saleId} is awaiting payment — retry from the receipt or take cash.`);
                    this.loading = false;
                    return;
                }
            }
            this.pendingPaymentId = null;
            this.flashError(`No confirmation from M-Pesa yet. Check sale #${saleId} in Sales History before retrying.`);
            this.loading = false;
        },
    };
}
