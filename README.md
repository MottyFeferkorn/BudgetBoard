# BudgetBoard

> A responsive personal-finance workspace for planning monthly budgets, recording income and expenses, and understanding where money goes.

**Project status:** Functional CS50x final-project implementation; proposed next steps are listed in [Future work](#future-work).

## Proposal

Budgeting often means switching between a spreadsheet, a banking app, and handwritten notes. Those tools can record what happened, but they do not always make it easy to compare a plan with real spending. BudgetBoard brings those jobs together in one focused web application.

The product is designed for individuals who want a clear monthly view of their finances without connecting a bank account or learning a complex accounting system. Each user can organize financial accounts, create custom categories, record transactions, prepare a budget for each month, and review the result through a dashboard and detailed reports.

BudgetBoard’s main goal is to answer four practical questions:

1. How much money do I have across my active accounts?
2. How much came in and went out this month?
3. Am I following the plan I made for each category?
4. What patterns are visible across recent months?

## Current features

### Secure user accounts

- Register and sign in with an email address and password.
- Store passwords as PBKDF2-SHA256 hashes rather than plaintext.
- Keep authenticated state in server-side filesystem sessions.
- Change the account email or password from Settings.
- Scope accounts, categories, plans, transactions, and recurring events to the signed-in user.

### Dashboard

- See total balance, current-month income, current-month expenses, and remaining cash flow.
- Add income or an expense without leaving the dashboard.
- Compare actual spending with important expense-plan categories.
- Review spending by category, recent transactions, and active accounts.

### Income and expense tracking

- Add, edit, and delete dated transactions.
- Assign every transaction to an account and a custom category.
- Add an optional description.
- Search descriptions and category names.
- Filter by date range, category, account, and amount range.
- Sort by date, amount, or description.
- Progressively load 10, 25, 50, or all matching results.

### Recurring transactions

- Schedule recurring income and expenses weekly, every two weeks, monthly, yearly, or at a custom interval.
- Set optional end dates.
- Review, edit, and delete schedules from Settings.
- Generate due entries when the relevant transaction page is opened, including missed occurrences since the previous visit.

### Monthly budget plans

- Create a separate income-and-expense plan for each month.
- Start with a blank plan or copy the most recent previous plan.
- Add, rename, reassign, update, or remove planned categories and amounts.
- Move between adjacent months or jump to a saved month.
- See planned income, planned expenses, and the expected remaining amount.

### Accounts and categories

- Track checking, savings, cash, credit card, investment, and other accounts.
- Calculate each balance from recorded income minus recorded expenses.
- Edit account details and deactivate old accounts without losing their transaction history.
- Create and maintain separate income and expense category lists.
- Prevent deletion of categories that are still used by transactions, plans, or recurring schedules.

### Reports

- Select any reporting month.
- Review income, expenses, net cash flow, and savings rate.
- Compare income and expense totals with the previous month.
- View a six-month income-versus-expense chart.
- Break down income and expenses by category.
- Compare planned and actual amounts by category.
- Review activity and net change for each account.

## Typical workflow

1. Create an account and sign in.
2. Add one or more financial accounts.
3. Record income and expenses, creating categories as needed.
4. Build a plan for the current month or copy the previous month’s plan.
5. Set up recurring entries for predictable items such as paychecks, rent, or subscriptions.
6. Use the dashboard for a quick overview and Reports for a deeper monthly review.

## Technology

| Layer       | Technology                      | Purpose                                                                          |
| ----------- | ------------------------------- | -------------------------------------------------------------------------------- |
| Backend     | Python and Flask                | Routing, authentication, validation, and server-rendered pages                   |
| Data access | CS50 SQL                        | Parameterized access to SQLite                                                   |
| Database    | SQLite                          | User, account, transaction, plan, category, and schedule storage                 |
| Sessions    | Flask-Session                   | Server-side login sessions stored on the filesystem                              |
| Security    | Werkzeug                        | Password hashing and verification                                                |
| Frontend    | Jinja, HTML, and CSS            | Responsive server-rendered interface                                             |
| UI system   | Bootstrap 5 and Bootstrap Icons | Layout, controls, modals, navigation, and icons                                  |
| Enhancement | Vanilla JavaScript              | Registration feedback, password visibility, and asynchronous transaction filters |

Bootstrap and Bootstrap Icons are loaded from a CDN, so the interface currently needs an internet connection for complete styling and icons during local use.

## Architecture

BudgetBoard follows a server-rendered Flask architecture:

- `app.py` configures Flask and defines page-level routes.
- `helpers.py` contains validation, ownership checks, database operations, transaction workflows, recurring-event processing, and report calculations.
- `templates/` contains reusable Jinja views.
- `static/` contains the shared design system, page-specific styles, and progressive enhancements.
- `budget.db` is the SQLite database expected by the current application.

Browser forms submit to Flask routes. The backend validates important values, confirms that referenced records belong to the signed-in user, and runs parameterized SQL queries.

After a successful write, Flask redirects the browser to prevent accidental duplicate submissions. Read requests render Jinja templates using data calculated by the backend.

Transaction filtering works through ordinary query parameters when JavaScript is unavailable. When JavaScript is enabled, the page progressively enhances those filters by updating the results without a complete page reload.

## Data model

The database is organized around user-owned records:

| Table               | Responsibility                                                         |
| ------------------- | ---------------------------------------------------------------------- |
| `users`             | Login identity, password hash, and account creation time               |
| `accounts`          | Named financial accounts and active or inactive state                  |
| `categories`        | Per-user income and expense categories                                 |
| `income`            | Money received, including its category, account, date, and description |
| `expenses`          | Money spent, including its category, account, date, and description    |
| `budget_plans`      | One plan per user and month                                            |
| `budget_plan_items` | Category-level planned amounts within a monthly plan                   |
| `recurring_events`  | Reusable transaction details and the next scheduled date               |

Database constraints enforce valid account and category types, unique categories per user and type, one plan per user and month, and one entry per category within a plan.

## Project structure

```text
BudgetBoard/
├── app.py                    # Flask routes and application configuration
├── helpers.py                # Business rules, validation, queries, and calculations
├── budget.db                 # SQLite database used by the current build
├── requirements.txt          # Python dependencies
├── templates/
│   ├── layout.html           # Shared navigation, messages, and page shell
│   ├── home.html             # Public landing page
│   ├── login.html            # Sign-in flow
│   ├── register.html         # Registration flow
│   ├── index.html            # Authenticated dashboard
│   ├── plan.html             # Monthly plans
│   ├── income.html           # Income history and recurring setup
│   ├── expenses.html         # Expense history and recurring setup
│   ├── accounts.html         # Account management and balances
│   ├── reports.html          # Monthly insights and comparisons
│   ├── settings.html         # Profile, categories, and recurring schedules
│   └── _transaction_rows.html
└── static/
    ├── style.css             # Shared styles
    ├── dashboard.css         # Dashboard styles
    ├── plan.css              # Plan styles
    ├── reports.css           # Report styles
    ├── settings.css          # Settings styles
    ├── register.js           # Registration form feedback
    ├── password-toggle.js    # Password visibility controls
    ├── transactions.js       # Transaction filtering and pagination
    └── icon.svg              # Application icon
```

## Run locally

### Requirements

- Python 3
- `pip`
- A web browser
- Internet access for the current Bootstrap CDN assets

### Installation

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
flask --app app run --debug
```

Open `http://127.0.0.1:5000` in a browser.

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

The current repository expects `budget.db` to exist in the project root with the application schema already applied. A migration or database-initialization command is not yet included.

## Validation and security

The current implementation includes:

- hashed passwords and generic invalid-login messages;
- parameterized database queries;
- login protection for private routes;
- per-user ownership checks before records are read or changed;
- validation for email addresses, dates, monetary amounts, descriptions, account types, categories, schedules, and record identifiers;
- database constraints that reinforce application rules.

Before a public deployment, the project should also:

- move environment-specific settings out of source code;
- configure a production session store and secret key;
- add CSRF protection;
- serve the application through HTTPS;
- initialize databases through migrations;
- disable Flask debug mode.

## Design decisions

### Separate income and expense tables

The schema uses separate `income` and `expenses` tables. This makes type-specific queries and category validation straightforward.

A future version could use a single transaction table with a type column to reduce duplicated query logic.

### Derived balances

Account balances are calculated from transaction history rather than stored separately. This prevents a cached balance from drifting away from its source entries.

In the current model, the starting balance for every account is zero.

### Preserved historical records

Accounts can be deactivated instead of deleted. Categories cannot be removed while another record depends on them.

These choices protect the meaning of historical transactions and reports.

### Server-rendered reporting

Charts and comparisons are calculated on the server and rendered with HTML and CSS. This keeps the reporting layer lightweight and avoids requiring a separate charting library.

### Progressive enhancement

Core forms and filters remain usable as ordinary browser requests. Small JavaScript files improve responsiveness, but Flask remains the source of truth for validation and data changes.

## Future work

The next phase would focus on reliability, portability, and richer financial planning:

- Add automated tests for authentication, ownership, transactions, plans, recurring dates, and reports.
- Add a schema file or migrations and a safe first-run database command.
- Pin dependency versions and document supported Python versions.
- Move production configuration to environment variables.
- Add CSRF protection and a durable production session backend.
- Support opening balances and transfers between accounts.
- Import and export transactions using CSV files.
- Add savings goals, debt payoff views, and configurable currencies.
- Process recurring entries with a scheduled background job.
- Add deployment documentation, accessibility testing, and responsive browser tests.

## CS50x context

BudgetBoard was developed as a CS50x final project. The application uses the CS50 SQL library while extending the course’s Flask patterns into a complete multi-page budgeting product with planning, account management, recurring schedules, and reporting.
