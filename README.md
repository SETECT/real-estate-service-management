# Real Estate Service Management System (RESMS)

Complete school-project implementation: Django 5.2, PostgreSQL, Python 3.12,
server-rendered templates, Bootstrap 5 and one Chart.js dashboard chart.
All eleven build steps are implemented.

## Run locally (PowerShell)

Start PostgreSQL first. If your database runs in a VM, start that VM and confirm
its IP address matches `DB_HOST` in `.env`. The database must already exist.

```powershell
py -3.12 -m venv .venv312
.\.venv312\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Set SECRET_KEY and PostgreSQL connection details in .env.
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 127.0.0.1:8000
```

Do not overwrite an existing `.env` when repeating setup. This workspace already
has `.venv312` and a project-local Python 3.12 runtime. The old `.venv` uses Python
3.14 and should not be used for the app. Without activating the environment, use
`.venv312/Scripts/python.exe manage.py <command>`.

Open http://127.0.0.1:8000/ (Dashboard), or
http://127.0.0.1:8000/accounts/login/ to log in.
The default timezone is `Asia/Phnom_Penh`; override `TIME_ZONE` in `.env` if needed.
Bootstrap and Chart.js load from a CDN and require internet access. Dashboard
counts remain visible as text if the chart library cannot load.

## Demo accounts and data

On a fresh database:

| Username | Password | Role |
| --- | --- | --- |
| admin | admin123 | Admin |
| agent | agent123 | Agent |

`seed_demo` creates these accounts, three properties, and two customers (Sok Dara,
Seller; Chan Sreyneang, Buyer). Rerunning it preserves existing accounts,
passwords, properties, customers, owners and statuses.

In this workspace, the pre-existing `admin` account retains its original
password. Use that password, or intentionally change it with
`python manage.py changepassword admin`. The demo Agent uses `agent / agent123`.
Admin user management is available at `/admin/` for staff Admin accounts;
`/users/` provides the Admin-only searchable user list.

## Modules and access

| Module | URL | Features |
| --- | --- | --- |
| Dashboard | `/dashboard/` | Ten statistics, Paid-payment sum, property-status chart |
| Properties | `/properties/` | CRUD, name/location search, type/status filters, single image |
| Customers | `/customers/` | CRUD, name/phone/email search, type filter, owner links |
| Inquiries | `/inquiries/` | CRUD, status, agent assignment, search and filters |
| Appointments | `/appointments/` | CRUD, date/time scheduling, status, search and filters |
| Transactions | `/transactions/` | Sale/rental CRUD, inquiry conversion, property status effects |
| Contracts | `/contracts/` | CRUD, unique contract number, transaction links, search/status filter |
| Payments | `/payments/` | Manual CRUD, Paid/Pending, methods, search/status filter |
| Reports | `/reports/` | Property, transaction and payment tables with filters |
| Users | `/users/` | Admin-only user listing |

Admin has full access. Agents can list/view all business records, and create,
edit or delete properties, inquiries, appointments and transactions assigned to
themselves. Assignment changes are Admin-only. Contracts and payments inherit
write permission from `Transaction.agent`, including after reassignment.
Customer writes are Admin-only because customers have no assigned-agent field.
Unknown roles are denied. Django admin also enforces the Admin role.

Lists show 20 records per page and retain search/filter parameters. Delete
operations use Bootstrap confirmation modals and CSRF-protected POST requests.
Related historical records use protected foreign keys; parents cannot be deleted
while referenced. Images are stored under `media/properties/` and served in
DEBUG mode. Replacing or clearing an image does not remove its old file from disk.

## Business behavior

- Monetary values use decimal fields with two decimal places, never floats.
- Property owners must be Seller/Landlord customers. Existing ownerless properties
  remain valid. Prices cannot be negative; property size must be positive.
- Rental transactions require both dates, with end strictly after start. Their
  amount is monthly rent; a Sale amount is the negotiated sale price.
- Completing Sale sets the property to Sold; completing Rental sets it to Rented.
  Cancelling only releases a Reserved property to Available. It does not reverse
  Sold/Rented. Pending transactions do not reserve a property automatically.
- Sold properties cannot be selected in new transactions. Completed transactions
  can be cancelled but cannot return to Pending; cancelled transactions cannot
  reopen. Property/type cannot change after completion or cancellation.
- Creating a transaction from an inquiry copies its customer/property and marks
  the inquiry Completed after successful save. The source inquiry cannot change.
  Transaction, property and inquiry changes are atomic and use database row locks.
- Transaction details provide Create Contract and Record Payment buttons that
  prefill linked data. Contracts/payments link back to their transaction/customer.
- Contract customer, property and type must match its transaction. Contract
  numbers are unique. Start date is required; rentals also require a later end
  date. Statuses are Draft (default), Active, Completed and Cancelled. Contract
  status does not automatically change a transaction or property.
- A transaction's customer/property/type cannot change while contracts reference
  it; customer cannot change while payments reference it. Amount, dates, status
  and agent may still be edited under the other business rules.
- Payments default to Pending and staff manually mark them Paid. Methods are
  Cash, Bank Transfer and Other. Amount must be nonnegative and customer must
  match the transaction. There is no gateway, money transfer, balance enforcement
  or automatic transaction completion; overpayments can be recorded.
- Dashboard payment totals sum Paid records only. Upcoming appointments include
  only Scheduled appointments at or after the current local date/time.
- Reports share a search box. Named status/type/method filters affect their own
  table; inclusive date limits apply to transaction date and payment date.
  Invalid filters show validation errors. Each report has independent pagination.

## 13-step demonstration

1. Log in as Admin.
2. Add a property and assign it to the demo Agent.
3. Add a Buyer or Tenant customer.
4. Create an inquiry linked to the customer/property.
5. Assign the inquiry to Agent.
6. Log in as Agent and schedule a viewing under Appointments.
7. Complete the viewing and move the inquiry to Negotiation.
8. On inquiry details, choose Create Transaction; select Sale/Rental, enter
   amount and rental dates where required, and save as Pending.
9. On transaction details, choose Create Contract, enter a unique contract number,
   confirm the prefilled details, and save.
10. Choose Record Payment, enter the amount/method/date, and mark Paid.
11. Edit the transaction and change its status to Completed.
12. Open its property and verify Sold/Rented.
13. Open Dashboard and Reports to see the updated status and recorded payment.

## Verification

Verified on 24 September 2026 with Python 3.12, Django 5.2.17 and PostgreSQL:

- All 100 tests pass, including both complete demo workflows.
- Migrations through `0010_payment` are applied; no pending model changes.
- Django system checks report no issues; demo seeding completes successfully.
- Live HTTP checks passed for Agent login, all module lists, contract/payment
  create forms, dashboard, reports, invalid report filters, and Agent denial at
  `/users/`. Development server started at `http://127.0.0.1:8000/`.

The PostgreSQL account must be able to create/drop test databases.

```powershell
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py check
python manage.py test --noinput
```

`core/tests.py` includes `DemoWorkflowTests`, which executes all thirteen steps
through HTTP forms for both Sale and Rental, including real login, role checks,
contract/payment creation, completion, and dashboard/report assertions. Other
tests cover CRUD, assignment tampering, CSRF, protected deletion, validation,
filters/pagination, image handling, transaction rollback and repeatable seeding.

Migrations through `0010_payment` are included. This supplied workspace has no
Git repository, so source migrations are present but have not been committed.

## Troubleshooting and existing database repair

- Database connection timeout: start PostgreSQL/the database VM, check `DB_HOST`
  and `DB_PORT`, and allow the PostgreSQL connection on the VM network.
- Missing relation/table: run `python manage.py migrate` using `.venv312`.
- Existing demo password differs: seeding deliberately preserves it; use the
  existing password or `changepassword`.
- Fresh test database permission error: give the configured development database
  account permission to create test databases.

The original workspace had `core.0001_initial` applied but lacked its custom User
model and `AUTH_USER_MODEL`. Migration `0002` adds user timestamps; `0003` copies
legacy auth accounts and memberships, preserving IDs/passwords, and repairs the
admin-log foreign key. Legacy tables are retained. It does nothing on a fresh
database and refuses to overwrite conflicting accounts. This migration is
intentionally irreversible; restoring the pre-repair state requires a backup.
