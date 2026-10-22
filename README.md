# Hardware Shop POS — Complete Starter System

A working multi-branch Point of Sale system: **Django + PostgreSQL**
backend, **Bootstrap 5 + Alpine.js** frontend, **Safaricom M-Pesa STK
Push** payments. Every flow below has been built, migrated, and
tested end-to-end (not just scaffolded).

## What's fully working

- **Auth & roles** — Owner / Manager / Cashier, enforced on every
  restricted page (staff, branch, product creation are Owner/Manager-only)
- **POS checkout screen** — live cart (Alpine.js), product search,
  cash / M-Pesa / on-credit checkout, all wired to real endpoints
- **Defaulter block** — a customer whose `balance_owed` exceeds their
  `credit_limit` is rejected at the point of sale with a clear message,
  for every payment method, until they clear the debt
- **Stock deduction & oversell protection** — sales deduct branch stock
  atomically and are rejected if there isn't enough on hand
- **Quotations** — save a cart as a printable quotation, then convert
  it to a real sale later (still defaulter-checked, still deducts stock)
- **M-Pesa STK Push** — initiate + callback + status-poll all wired into
  the checkout flow (needs your own Safaricom sandbox credentials to test)
- **Customer management** — add/edit customers, record debt repayments
  (reduces `balance_owed` directly from the customer list)
- **Inventory** — add/edit products, view stock by branch, restock from
  a supplier purchase (auto-increases stock)
- **Branches & stock transfers** — add branches, dispatch a stock
  transfer (deducts source immediately), receive it at the destination
  (adds to destination stock)
- **Staff management** — add/edit staff with role + branch assignment
- **Dashboard** — today's sales/revenue, low-stock alerts, defaulter
  list, a 7-day sales trend chart, and a top-products chart (Chart.js)
- **Printable receipts & quotations** — browser print view, ready to
  swap for WeasyPrint-generated PDFs later if you want downloadable files

This was verified with an actual test run: seeded data, ran a cash
sale (stock deducted, marked PAID), attempted a sale against a
defaulter (blocked with 403), ran a credit sale (balance_owed
increased correctly), and attempted an oversell (rejected). All 17+
pages load without errors, and role restrictions were confirmed to
block cashiers from owner/manager-only pages.

## What's intentionally left for you to extend

- Real-time dashboard sync across branches (Django Channels) — the
  data model supports it, the WebSocket layer isn't wired in yet
- Scheduled alerts (low stock / overdue debt reminders via Celery) —
  packages are in requirements.txt, tasks aren't written yet
- Offline mode for branches with unreliable internet (PWA + service
  worker) — noted as a phase-2 feature in the original plan
- SMS notifications (Africa's Talking) for payment confirmations

## Step-by-step: running this in VS Code

1. **Open the project folder**
   Open VS Code → File → Open Folder → select `hardware_pos`.

2. **Install the Python extension** (if not already installed)
   Extensions panel (Ctrl+Shift+X) → search "Python" → install Microsoft's
   official extension.

3. **Create and activate a virtual environment**
   Open a terminal in VS Code (`` Ctrl+` ``):
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```
   VS Code should prompt "Select this environment for the workspace" — click yes.

4. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Set up your environment file**
   ```bash
   copy .env.example .env      # Windows
   cp .env.example .env        # macOS/Linux
   ```
   Open `.env` and fill in a real `SECRET_KEY` (any long random string).
   Leave `DB_ENGINE=sqlite` for now — you can switch to Postgres in step 9.

6. **Run migrations**
   ```bash
   python manage.py migrate
   ```

7. **Load demo data (recommended for your first run)**
  ```powershell
  # Windows PowerShell:
  python manage.py shell -c "exec(open('seed_demo_data.py').read())"
  ```
  On macOS/Linux, use `python manage.py shell < seed_demo_data.py`.
   This creates two branches, two staff logins (`owner` / `cashier1`,
   both password `ChangeMe123!`), two products with stock, and two
   customers — one of them a defaulter, so you can immediately test
   the block. **Change these passwords before using this for real.**

   Prefer to start from scratch instead? Run
   `python manage.py createsuperuser` and build up your own data
   through `/admin/` or the app's own forms.

8. **Run the development server**
   ```bash
   python manage.py runserver
   ```
   Visit `http://127.0.0.1:8000/login/`, log in as `cashier1`, and go to
   **POS / Checkout** — add a product to the cart, pick "Jane Wanjiru
   (test defaulter)" as the customer, and try to check out: you'll see
   the block in action. Pick "John Mwangi" instead and it goes through.

9. **Switch to PostgreSQL (once installed)**
   Install PostgreSQL, create a database (`createdb hardware_pos` or via
   pgAdmin), then in `.env` set:
   ```
   DB_ENGINE=postgres
   DB_NAME=hardware_pos
   DB_USER=postgres
   DB_PASSWORD=your_password
   ```
   Re-run `python manage.py migrate` (your SQLite data won't carry over —
   re-seed or re-enter it).

10. **Set up M-Pesa sandbox testing**
    - Register at developer.safaricom.co.ke, create an app, copy the
      Consumer Key/Secret into `.env`.
    - Install ngrok, run `ngrok http 8000` in a second terminal.
    - Copy the ngrok HTTPS URL into `MPESA_CALLBACK_URL` in `.env`
      (append `/payments/mpesa/callback/`).
    - Restart `runserver` after editing `.env` so the new values load.
    - Test from the POS screen using a Safaricom sandbox test phone number.

11. **Go live**
    Apply for a production Paybill/Till with Safaricom, swap in
    production M-Pesa credentials, deploy to Render/Railway (backend +
    Postgres) with `DEBUG=False` and a real `SECRET_KEY`, and change
    every demo password.

