# Hardware Shop POS

A multi-branch point-of-sale and back-office system built for hardware
shops: cement and steel by the bag and bar, contractors buying on credit,
wholesale prices for bulk orders, M-Pesa at the counter, and owners who
need to know what every branch sold, earned and owes.

**Stack:** Django 5.2 LTS · PostgreSQL or SQLite · Bootstrap 5 + Alpine.js ·
Chart.js · Safaricom M-Pesa (Daraja STK Push)

---

## Features

### Selling
- **Fast POS screen** – scan a barcode (or type a SKU) and press Enter; product
  tiles show live stock at your branch; out-of-stock items are locked.
- **Wholesale pricing** – each product can have a bulk price that applies
  automatically from a set quantity (e.g. cement at 750 from 20 bags).
- **Payments** – cash (tendered amount, quick-cash buttons, change due),
  M-Pesa STK Push, card, or **on account** for credit customers.
- **Discounts** – cashiers are capped at a configurable percentage;
  managers can approve more.
- **Hold & recall** – park a sale while a customer fetches more items.
- **Quotation Desk** – write a quotation on screen exactly like the paper
  duplicate book: your logo and company details, **QUOTATION** title,
  automatic number (QT-0001, QT-0002…), today's date and validity, a
  Client Details box (walk-in, walk-in with a name, or a registered
  customer found as you type), and a numbered item grid where typing in
  *Item description* searches the catalogue (arrow keys + Enter) and fills
  units, price and amount. Prices can be negotiated within your role's
  limits, and the total is written in words.
- **Print before payment** – print the draft for the customer to check, save
  it, then **convert it to an invoice** paid by cash (change shown), M-Pesa,
  card or on account. Walk-ins can be registered from the quotation for
  credit. Quotations can be edited, re-quoted at today's prices, and sent
  on **WhatsApp**.
- **Invoices** – a separate, standard invoice (INV-0001, INV-0002…) with due
  date, Bill To, amount before VAT, VAT, total, paid and balance due, amount
  in words, your Paybill / Till / bank details, and Prepared by / Received
  by signatures. Issue one from the **Invoice Desk**, from a quotation, or
  for any till sale. The Invoices list shows what is outstanding and overdue.
- **Receipts** – 80 mm thermal layout with KRA PIN, VAT breakdown, payments,
  change and balance due; prints automatically after each sale.
- **Returns & refunds** – restock (or write off damaged goods), refund in cash,
  M-Pesa, or against what the customer still owes; discounts are shared
  proportionally so they aren't refunded twice.
- **Voids** – managers cancel mistaken sales; stock goes back and credit
  charges are reversed.
- Keyboard shortcuts: **F2** new quotation, **Ctrl+K** search; on the POS **F3** search, **F4** complete sale.

### Customers & credit
- Retail, contractor (fundi) and company customers with KRA PIN.
- Credit limits enforced at checkout: a sale that would take a customer over
  their limit is refused, and customers already over the limit are blocked.
- Debt repayments (cash / M-Pesa / bank / cheque) are applied to the oldest
  unpaid invoices first; overpayment is rejected.
- **Customer statement** with running balance, printable.

### Stock
- Per-branch stock with an **immutable movement ledger**: every sale, return,
  void, delivery, transfer and adjustment is recorded with who, when and why.
  Stock can never go negative.
- Receive deliveries from suppliers (invoice number, paid/unpaid tracking,
  cost price kept up to date).
- **Branch transfers** – dispatch, receive or cancel, with stock in transit.
- **Stock adjustments** – stock-take mode (set counted quantity) or add/remove
  for damage, theft, expiry.
- CSV **import/export** of the catalogue (upsert by SKU, opening stock), and
  printable **shelf labels** with barcodes.

### Till & cash control
- **Shifts** – open with a float, cash up at close; the system computes
  expected cash (float + cash sales + cash debt repayments − cash refunds −
  petty cash) and records the over/short variance. Printable Z-report.
- **Expenses** – petty cash and other spending by category.
- Optional rule: cashiers must open a shift before selling.

### Insight
- **Dashboard** – quick-action tiles (New Quotation is **F2**), today's
  revenue, money collected by method, gross profit, money owed, a
  **Needs attention** list (overdue invoices, expiring quotes, low stock,
  blocked customers, open tills), quote-to-invoice conversion, a 7/14/30-day
  revenue chart and recent activity. Profit figures are hidden from cashiers.
- **Ctrl+K quick search** – jump to any page, product, customer or
  QT/INV/receipt number from anywhere.
- **Reports** – Profit & Loss, product sales (with category breakdown), staff
  performance (voids, discounts, cash-up variances), debt aging
  (0–30/31–60/61–90/90+ days), reorder list with suggested quantities from
  recent demand, and monthly VAT summary. Most export to CSV.

### Security & accountability
- Roles: **Owner** (everything), **Branch Manager** (their branch, cashiers
  only), **Cashier** (sell, customers, own shift).
- Audit log of logins, failed logins, sales, voids, refunds, stock
  adjustments, price/credit changes and settings changes.
- Production hardening (HTTPS, secure cookies, HSTS) when `DEBUG=False`.

---

## Quick start (Windows, macOS, Linux)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env        # macOS/Linux: cp .env.example .env
# edit .env and set SECRET_KEY to a long random string

python manage.py migrate
python manage.py seed_demo    # optional: demo shop with a month of sales
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and log in.

| Demo login | Role | Branch |
|---|---|---|
| `owner` | Owner | Main Branch |
| `manager` | Branch Manager | Main Branch |
| `cashier1` | Cashier | Main Branch |
| `cashier2` | Cashier | Westlands Branch |

All demo passwords are `ChangeMe123!` — **change them before real use.**
To start from scratch instead, skip `seed_demo` and run
`python manage.py createsuperuser`, then set the user's role to Owner in
`/admin/`. Company name, **logo** (optional), KRA PIN, address, VAT rate and receipt
footer are under **Shop Settings** and appear on quotations, invoices and
receipts.

## M-Pesa

Without Daraja credentials and with `DEBUG=True`, M-Pesa runs in **demo
mode**: the POS shows "customer paid / cancelled" buttons so you can try the
full flow offline.

For the real sandbox:
1. Create an app at <https://developer.safaricom.co.ke> and put the consumer
   key, secret and passkey in `.env`.
2. Expose your server with `ngrok http 8000` and set
   `MPESA_CALLBACK_URL=https://<your-ngrok-domain>/payments/mpesa/callback/`.
3. Restart `runserver`.

Phone numbers can be typed as `0712 345 678`, `+254712345678` or
`712345678`. Callbacks are idempotent (Safaricom retries are ignored).

## Daily jobs

Schedule these with cron or Windows Task Scheduler:

```bash
python manage.py expire_quotations   # mark out-of-date quotations as expired
python manage.py stock_alerts        # print low / out-of-stock items per branch
```

## Running the tests

```bash
python manage.py test
```

150+ tests cover checkout rules, credit limits, returns, voids, M-Pesa
callbacks, cash-up maths, stock ledger, transfers, CSV import, report
figures, role permissions, and a smoke test that opens every page as every
role. GitHub Actions runs them on SQLite and PostgreSQL for every push.

## PostgreSQL

Create a database, then in `.env`:

```
DB_ENGINE=postgres
DB_NAME=hardware_pos
DB_USER=postgres
DB_PASSWORD=your_password
```

and run `python manage.py migrate`.

## Deploying

1. Set `DEBUG=False`, a real `SECRET_KEY`, `ALLOWED_HOSTS` and
   `CSRF_TRUSTED_ORIGINS=https://your-domain`.
2. Use PostgreSQL.
3. `python manage.py collectstatic` (WhiteNoise serves static files).
4. Run with `gunicorn config.wsgi` behind HTTPS (Render, Railway, a VPS…).
5. Switch M-Pesa to production credentials and change every demo password.

## Project layout

| App | Responsibility |
|---|---|
| `accounts` | Users and roles, staff management, audit log |
| `branches` | Branches and inter-branch stock transfers |
| `inventory` | Products, categories, suppliers, deliveries, stock ledger, import/export, labels |
| `customers` | Customers, credit limits, debt repayments, statements |
| `sales` | POS, checkout service, receipts, quotations, returns, voids |
| `payments` | Payments and the M-Pesa STK Push flow |
| `registers` | Till shifts, cash-up and expenses |
| `dashboard` | Dashboard, business metrics and reports |
| `core` | Shop settings, shared helpers, management commands |

Business rules live in service modules (`sales/services.py`,
`inventory/services.py`, `customers/services.py`, `registers/services.py`)
so the screens, API endpoints and tests all go through the same checks.

## Roadmap ideas

- SMS receipts and debt reminders (Africa's Talking)
- Offline mode for branches with unreliable internet (PWA)
- Purchase orders sent to suppliers from the reorder list
- KRA eTIMS invoice integration
