/* Ctrl+K quick search: pages (read from the sidebar), products, customers and document numbers. */
function commandPalette(productUrl, customerUrl) {
    const pages = () => Array.from(document.querySelectorAll('.sidebar-nav a.nav-link')).map(a => ({
        title: a.textContent.trim(), url: a.getAttribute('href'), icon: (a.querySelector('i') || {}).className || 'bi-link',
        hint: 'Go to page', kind: 'Page',
    }));
    const docLink = (q) => {
        const t = q.trim().toUpperCase().replace(/\s+/g, '');
        if (/^QT-?\d+$/.test(t)) return { title: `Find quotation ${t}`, url: `/sales/quotations/?status=all&q=${t}`, icon: 'bi-file-earmark-text', hint: 'Quotations', kind: 'Document' };
        if (/^INV-?\d+$/.test(t)) return { title: `Find invoice ${t}`, url: `/sales/invoices/?q=${t}`, icon: 'bi-journal-check', hint: 'Invoices', kind: 'Document' };
        if (/^R\d+-?\d+$/.test(t)) return { title: `Find receipt ${t}`, url: `/sales/history/?range=all&q=${t}`, icon: 'bi-receipt', hint: 'Sales history', kind: 'Document' };
        return null;
    };
    return {
        open: false, q: '', results: [], active: 0, controller: null,

        init() {
            window.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); this.show(); }
            });
        },
        show() {
            this.open = true; this.q = ''; this.results = pages().slice(0, 8); this.active = 0;
            this.$nextTick(() => this.$refs.input.focus());
        },
        close() { this.open = false; },
        move(step) { if (this.results.length) this.active = (this.active + step + this.results.length) % this.results.length; },
        go() { const r = this.results[this.active]; if (r) window.location.href = r.url; },

        async search() {
            const q = this.q.trim();
            const lower = q.toLowerCase();
            const found = [];
            const doc = docLink(q);
            if (doc) found.push(doc);
            found.push(...pages().filter(p => p.title.toLowerCase().includes(lower)).slice(0, 4));
            this.results = found;
            this.active = 0;
            if (q.length < 2) return;

            if (this.controller) this.controller.abort();
            this.controller = new AbortController();
            const signal = this.controller.signal;
            try {
                const [products, customers] = await Promise.all([
                    fetch(`${productUrl}?q=${encodeURIComponent(q)}`, { signal }).then(r => r.ok ? r.json() : { results: [] }),
                    fetch(`${customerUrl}?q=${encodeURIComponent(q)}`, { signal }).then(r => r.ok ? r.json() : { results: [] }),
                ]);
                this.results = found.concat(
                    products.results.slice(0, 6).map(p => ({
                        title: p.name, url: `/inventory/${p.id}/`, icon: 'bi-box-seam', kind: 'Product',
                        hint: `${p.sku} · KES ${Number(p.price).toLocaleString('en-KE')} / ${p.unit} · ${p.stock} in stock`,
                    })),
                    customers.results.slice(0, 5).map(c => ({
                        title: c.name, url: `/customers/${c.id}/`, icon: 'bi-person', kind: 'Customer',
                        hint: `${c.phone}${Number(c.balance) > 0 ? ' · owes KES ' + Number(c.balance).toLocaleString('en-KE') : ''}`,
                    })),
                );
            } catch (e) { /* a newer keystroke took over */ }
        },
    };
}
