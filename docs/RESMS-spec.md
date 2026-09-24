# Real Estate Service Management System (RESMS) — V1
## Codex Implementation Prompt

---

## 0. PROJECT CONTEXT

I am building a Real Estate Service Management System as a school/university assignment.

- Goal: a simple but complete working system demonstrating real-estate management concepts.
- This is NOT a commercial or production system.
- Keep the project small, understandable, and easy to demonstrate.
- Do not over-engineer the application.

---

## 1. IMPLEMENTATION CONVENTIONS (apply everywhere)

### 1.1 Stack
- Django 5.x, PostgreSQL, Python 3.12
- Bootstrap 5 via CDN for UI
- Chart.js via CDN for the one dashboard chart
- Server-rendered Django templates only
- No DRF, no REST API, no JS framework
- python-decouple (or django-environ) for settings; include `.env.example`

### 1.2 Project Structure
- One Django project: `resms`
- One Django app: `core` (school-project simplicity)
- Templates under `templates/core/`
- `base.html` with Bootstrap navbar + sidebar
- `requirements.txt`, `.env.example`, `README.md` with run instructions
- Migrations committed

### 1.3 Data Rules
- All monetary fields: `DecimalField(max_digits=12, decimal_places=2)` — never `FloatField`
- All models include `created_at` and `updated_at` (auto)
- FKs representing business history use `on_delete=PROTECT`
- Model validation in `clean()` where rules exist (e.g. rental `end_date > start_date`)
- No cascading deletes of historical records

### 1.4 Authentication
- Custom `User` extending `AbstractUser` with a `role` field (choices: `admin`, `agent`)
- `RoleRequiredMixin` for view-level enforcement
- Only Admin can access the Users section

### 1.5 Authorization Rules
- **Admin**: full access to all modules and Users
- **Agent**: CRUD only on their own assigned records (assigned inquiries, appointments, transactions)
- Agents cannot manage users

---

## 2. MODULES

### 2.1 Authentication

**Features:** Login, Logout, User account, Basic role

**Roles:** Admin, Agent

**Notes:** Authentication does not need to be highly advanced.

---

### 2.2 Property Management

**Features**
- Add / View / Edit / Delete property
- View property details
- Search properties
- Filter by status and type

**Fields**
- Property ID
- Property name
- Property type
- Location
- Description
- Price
- Size
- Number of bedrooms
- Number of bathrooms
- Status
- Owner (FK → Customer with type Seller or Landlord)
- Image (single ImageField, uploaded to `media/properties/`)

**Property Types:** House, Apartment, Condo, Land, Commercial

**Property Status:** Available, Reserved, Sold, Rented

---

### 2.3 Customer Management

**Features**
- Add / View / Edit / Delete customer
- View customer details
- Search customers

**Fields**
- Customer ID
- Full name
- Phone
- Email
- Address
- Customer type

**Customer Types:** Buyer, Seller, Tenant, Landlord

---

### 2.4 Property Inquiry

**Features**
- Create / View / Edit / Delete inquiry
- Assign an agent
- Update inquiry status

**Fields**
- Inquiry ID
- Customer (FK)
- Property (FK)
- Agent (FK → User)
- Inquiry date
- Message/notes
- Status

**Inquiry Status:** New, Contacted, Viewing, Negotiation, Completed, Cancelled

**Business Rule:** When a Transaction is created from an Inquiry, mark the Inquiry status as Completed. Optionally pre-fill customer/property/agent from the inquiry.

---

### 2.5 Appointment / Property Viewing

**Features**
- Create / View / Edit / Delete appointment
- Mark appointment as Completed or Cancelled

**Fields**
- Appointment ID
- Customer (FK)
- Property (FK)
- Agent (FK → User)
- Date
- Time
- Notes
- Status

**Appointment Status:** Scheduled, Completed, Cancelled

**Notes:** No complicated calendar system required.

---

### 2.6 Sales & Rental Transactions

This is the main business process of the system.

**Transaction Types:** Sale, Rental

**Fields**
- Transaction ID
- Customer (FK)
- Property (FK)
- Agent (FK → User)
- Transaction type
- Amount
- Transaction date
- Status

**Rental-only fields:** Start date, End date

**Transaction Status:** Pending, Completed, Cancelled

**Business Rules**
- For Sale: `amount` = sale price
- For Rental: `amount` = monthly rent; `start_date` and `end_date` required
- Completing a Sale: set `Property.status = Sold`
- Completing a Rental: set `Property.status = Rented`
- Cancelling a Transaction: revert `Property.status = Available` if it was Reserved
- A property with status Sold cannot be selected in a new transaction

---

### 2.7 Contract Management

**Features**
- Create / View / Edit / Delete contract
- View contract details

**Fields**
- Contract ID
- Contract number
- Customer (FK)
- Property (FK)
- Transaction (FK)
- Contract type
- Start date
- End date
- Contract amount
- Status
- Contract description

**Contract Types:** Sale Contract, Rental Contract

**Notes**
- No electronic signature system required
- No document-generation system required

---

### 2.8 Payment Records

> **IMPORTANT:** This system does NOT process real online payments.
> No payment gateway, credit card processing, banking integration, or real money transfer.
> Payments are manual records for demonstration only.

**Features**
- Add / View / Edit / Delete payment record
- View payment details

**Fields**
- Payment ID
- Transaction (FK)
- Customer (FK)
- Amount
- Payment date
- Payment method
- Payment status
- Note

**Payment Methods:** Cash, Bank Transfer, Other

**Payment Status:** Paid, Pending

**Business Rules**
- Payment status defaults to `Pending`; staff manually mark as `Paid`
- No automatic calculation, no balance enforcement
- Example: Customer pays $5,000 cash → staff records Amount: $5,000, Method: Cash, Status: Paid, Date: 20/09/2026

---

### 2.9 Dashboard

**Display (simple stat cards):**
- Total properties
- Available properties
- Sold properties
- Rented properties
- Total customers
- Total inquiries
- Upcoming appointments
- Total transactions
- Total recorded payments (count)
- Total sum of Paid payments

**Charts:** One Chart.js chart (e.g. properties by status)

**Notes:** Cards and basic chart only. No advanced analytics.

---

### 2.10 Basic Reports

**Property Report**
- Columns: Property name, Type, Price, Status, Owner

**Transaction Report**
- Columns: Transaction, Customer, Property, Agent, Type, Amount, Date, Status

**Payment Report**
- Columns: Customer, Transaction, Amount, Date, Payment method, Status

**Notes**
- Basic filtering and table display only
- No Excel/PDF export required for V1

---

## 3. DATABASE DESIGN

### 3.1 Tables
`users`, `properties`, `customers`, `inquiries`, `appointments`, `transactions`, `contracts`, `payments`

### 3.2 Relationships

```
User
├── manages → Properties
├── handles → Inquiries
├── handles → Appointments
└── handles → Transactions

Customer
├── creates → Inquiry
├── attends → Appointment
├── participates in → Transaction
├── signs → Contract
└── makes → Payment

Property
├── has → Inquiry
├── has → Appointment
├── involved in → Transaction
└── involved in → Contract

Transaction
├── has → Contract
└── has → Payment
```


Use foreign keys to maintain these relationships.

---

## 4. NAVIGATION

Sidebar items:
- Dashboard
- Properties
- Customers
- Inquiries
- Appointments
- Transactions
- Contracts
- Payments
- Reports
- Users

Only show menu items appropriate for the user's role.

---

## 5. UI REQUIREMENTS

### 5.1 Use
- Simple sidebar navigation
- Tables
- Forms
- Buttons
- Search boxes
- Basic filters
- Dashboard cards
- One basic Chart.js chart
- Confirmation before deleting records (Bootstrap modal)

### 5.2 Do NOT spend significant effort on
- Responsive/mobile design
- Animations
- Complex UI effects
- Advanced dashboards
- Design systems
- Dark mode
- Drag-and-drop interfaces
- Real-time updates

**Priority:** functionality and clear system structure, not visual complexity.

---

## 6. FEATURES NOT REQUIRED

Do not implement any of the following:

- Real online payments
- Payment gateway
- Credit card processing
- Banking integration
- SMS integration
- WhatsApp integration
- Email automation
- AI features
- Chatbot
- Recommendation system
- Google Maps integration
- GPS/location tracking
- Mobile application
- Advanced notifications
- Advanced analytics
- E-signatures
- Complex accounting
- Inventory management
- Maintenance management
- Multi-company support
- Multi-language support
- Advanced security systems
- Complex permission management
- API integrations
- Cloud deployment requirements
- Responsive/mobile UI optimization

---

## 7. MAIN DEMONSTRATION WORKFLOW

The completed system must support this end-to-end flow:

1. Admin logs in

2. Admin adds a property

3. Admin adds a customer

4. Customer makes an inquiry

5. Agent is assigned

6. Agent schedules a property viewing

7. Customer decides to rent/buy

8. Agent creates a transaction

9. Contract is created

10. Staff records the customer's payment

11. Transaction is completed

12. Property status changes to Sold/Rented

13. Dashboard and reports show updated information


This workflow must work correctly from beginning to end.

---

## 8. DEVELOPMENT PRIORITIES

| Priority | Focus |
|----------|-------|
| **1 — Core Functionality** | Working CRUD for Properties, Customers, Inquiries, Appointments, Transactions, Contracts, Payments |
| **2 — Relationships** | All entities connected via FKs; user can navigate between related records |
| **3 — Business Workflow** | Sale/rental workflow works from inquiry → transaction → payment |
| **4 — Dashboard** | Basic stats from actual database records |
| **5 — UI** | Clean and understandable; no excessive visual design effort |

---

## 9. BUILD ORDER

Stop and confirm after each step before continuing.

1. Project skeleton + custom User + auth + `base.html` + sidebar
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

---

## 10. DELIVERABLES

- `requirements.txt`
- `.env.example`
- `README.md` with run instructions
- Migrations committed
- One test file covering the 13-step demo workflow end-to-end
- Role permission tests (Agent cannot manage users; Admin can)
- All migrations applied successfully

---

## 11. IMPORTANT DEVELOPMENT RULE

This is a school assignment: **simplicity is more important than enterprise-level architecture.**

- Do not add features just because they might exist in a real commercial system.
- Build a small, complete, working system rather than a large system with unfinished features.
- Every feature must have a clear purpose in demonstrating the real-estate management process.