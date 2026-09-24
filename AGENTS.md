# RESMS — Implementation Conventions (binding for every task)

## Stack
- Django 5.x, PostgreSQL, Python 3.12, Bootstrap 5 (CDN), Chart.js (CDN)
- Server-rendered Django templates only. No DRF, no REST API, no JS framework.
- python-decouple for settings; include `.env.example`
- Single `resms/settings.py` (no split settings)

## Project Structure
- One Django project: `resms`
- One Django app: `core`
- Templates under `templates/core/`, `base.html` with Bootstrap navbar + sidebar
- URL names: `core:<model>_<action>` (e.g. `core:property_list`, `core:property_create`)
- Media: `MEDIA_URL=/media/`, `MEDIA_ROOT=BASE_DIR/'media'`; served in dev via `static()`
- `.gitignore`: `media/`, `db.sqlite3`, `.env`, `__pycache__/`

## Data Rules
- All money: `DecimalField(max_digits=12, decimal_places=2)` — never `FloatField`
- All models: `created_at`, `updated_at` (auto)
- FKs representing business history: `on_delete=PROTECT`
- Model validation in `clean()` where rules exist (e.g. rental `end_date > start_date`)
- No cascading deletes of historical records

## Auth & Roles
- Custom `User` extending `AbstractUser` with `role` field (choices: `admin`, `agent`)
- `RoleRequiredMixin` enforced at view level
- Only Admin can access `/users/`; Agent gets HTTP 403 or redirect with error
- "Assigned agent" = `Property.assigned_agent`, `Inquiry.agent`, `Appointment.agent`, `Transaction.agent`
- Agent can list/view all records but can only create/edit/delete records where they are the assigned agent

## Business Rules
- Completing a Sale transaction → `Property.status = Sold`
- Completing a Rental transaction → `Property.status = Rented`
- Cancelling a transaction → revert `Property.status = Available` if it was Reserved
- Creating a Transaction from an Inquiry → mark `Inquiry.status = Completed`
- A `Sold` property cannot be selected in a new transaction
- Payments are manual records only. No gateway, no balance enforcement.

## UI Rules
- All list pages: Bootstrap `table table-striped table-hover`, search box top, filter dropdowns, "Add New" button top-right
- All forms: Bootstrap `form-control` / `form-select`, labels above inputs
- All delete actions: confirm via Bootstrap modal
- One Chart.js chart on the dashboard (e.g. properties by status)

## Deliverables
- `requirements.txt`, `.env.example`, `README.md` with run instructions
- Migrations committed
- Management command `python manage.py seed_demo` creating:
  - admin / admin123 (role: admin)
  - agent / agent123 (role: agent)
  - 3 sample properties, 2 sample customers
- One test file proving the 13-step demo workflow runs end-to-end
- Role permission tests (Agent blocked from `/users/`; Admin allowed)

## Build Order
At the end of each step: run `makemigrations`, `migrate`, `test`, start dev server.
Report errors. **Do not proceed to the next step until confirmed.**

1. Project skeleton + custom User + auth + `base.html` + sidebar + `seed_demo`
2. Properties (CRUD, search, filter, single image upload)
3. Customers (CRUD, search)
4. Inquiries (CRUD, status, assign agent)
5. Appointments (CRUD, status)
6. Transactions (sale + rental, status transitions, property status updates)
7. Contracts (CRUD linked to transaction)
8. Payments (CRUD linked to transaction)
9. Dashboard (stat cards + one Chart.js chart)
10. Reports (3 tables with filters)
11. Tests + README + final polish