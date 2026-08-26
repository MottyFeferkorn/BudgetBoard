from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urlencode

from flask import flash, redirect, render_template, request, session, url_for


def login_required(f):
    """
    Decorate routes to require login.

    https://flask.palletsprojects.com/en/latest/patterns/viewdecorators/
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


def usd(value):
    """Format value as USD."""
    return f"${value:,.2f}"


class ValidationError(Exception):
    """Represent invalid application input with a user-facing message."""


def validate_category_name(value):
    """Clean and validate a reusable category name."""
    category_name = (value or "").strip()

    if not category_name:
        raise ValidationError("Category name is required.")

    if len(category_name) > 50:
        raise ValidationError(
            "Category name must be 50 characters or fewer."
        )

    return category_name


def get_or_create_category(
    db,
    user_id,
    category_name,
    category_type
):
    """Return a matching category ID or create the category."""
    category_name = validate_category_name(category_name)
    category_type = (category_type or "").strip().lower()

    rows = db.execute(
        """
        SELECT id
        FROM categories
        WHERE user_id = ?
          AND type = ?
          AND name = ? COLLATE NOCASE
        LIMIT 1
        """,
        user_id,
        category_type,
        category_name
    )

    if rows:
        return rows[0]["id"]

    try:
        return db.execute(
            """
            INSERT INTO categories (user_id, name, type)
            VALUES (?, ?, ?)
            """,
            user_id,
            category_name,
            category_type
        )
    except ValueError as error:
        # A simultaneous request may have inserted the same category first.
        rows = db.execute(
            """
            SELECT id
            FROM categories
            WHERE user_id = ?
              AND type = ?
              AND name = ? COLLATE NOCASE
            LIMIT 1
            """,
            user_id,
            category_type,
            category_name
        )

        if rows:
            return rows[0]["id"]

        # The schema also rejects category types other than income or expense.
        raise ValidationError("Choose a valid category type.") from error


def rename_category(db, user_id, category_id, new_name):
    """Rename one of a user's categories everywhere it is used."""
    new_name = validate_category_name(new_name)

    owned_category = db.execute(
        """
        SELECT id
        FROM categories
        WHERE id = ?
          AND user_id = ?
        LIMIT 1
        """,
        category_id,
        user_id
    )

    if not owned_category:
        raise ValidationError("Category not found.")

    try:
        db.execute(
            """
            UPDATE categories
            SET name = ?
            WHERE id = ?
              AND user_id = ?
            """,
            new_name,
            category_id,
            user_id
        )
    except ValueError as error:
        raise ValidationError(
            "A category with that name already exists."
        ) from error


def parse_plan_month(value):
    """Convert an HTML YYYY-MM value to the first day of that month."""
    value = (value or "").strip()

    try:
        selected_month = datetime.strptime(value, "%Y-%m").date()
    except ValueError as error:
        raise ValidationError("Choose a valid month.") from error

    return selected_month.replace(day=1)


def shift_plan_month(selected_month, offset):
    """Move a first-of-month date backward or forward by whole months."""
    month_index = (
        selected_month.year * 12
        + selected_month.month
        - 1
        + offset
    )
    year, zero_based_month = divmod(month_index, 12)

    return date(year, zero_based_month + 1, 1)


def validate_plan_amount(value):
    """Return a non-negative planned amount with at most two decimals."""
    value = (value or "").strip()

    try:
        amount = Decimal(value)
        cents_amount = amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as error:
        raise ValidationError("Enter a valid planned amount.") from error

    if not amount.is_finite():
        raise ValidationError("Enter a valid planned amount.")

    if amount < 0:
        raise ValidationError("The planned amount cannot be negative.")

    if amount != cents_amount:
        raise ValidationError("Use no more than two decimal places.")

    return cents_amount


def parse_record_id(value, label):
    """Convert a submitted database ID to a positive integer."""
    try:
        record_id = int(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"Choose a valid {label}.") from error

    if record_id <= 0:
        raise ValidationError(f"Choose a valid {label}.")

    return record_id


def get_budget_plan(db, user_id, database_month):
    """Find one of the current user's saved monthly plans."""
    rows = db.execute(
        """
        SELECT id, user_id, month, created_at
        FROM budget_plans
        WHERE user_id = ?
          AND month = ?
        LIMIT 1
        """,
        user_id,
        database_month
    )

    return rows[0] if rows else None


def get_previous_budget_plan(db, user_id, database_month):
    """Find the user's latest saved plan before a target month."""
    rows = db.execute(
        """
        SELECT id, month
        FROM budget_plans
        WHERE user_id = ?
          AND month < ?
        ORDER BY month DESC
        LIMIT 1
        """,
        user_id,
        database_month
    )

    return rows[0] if rows else None


def create_budget_plan(db, user_id, selected_month, start_mode):
    """Create a blank monthly plan or copy the latest earlier plan."""
    valid_start_modes = {"blank", "copy_previous"}

    if start_mode not in valid_start_modes:
        raise ValidationError("Choose how the new plan should begin.")

    database_month = selected_month.isoformat()

    if get_budget_plan(db, user_id, database_month):
        raise ValidationError(
            f"A plan for {selected_month.strftime('%B')} already exists."
        )

    try:
        new_plan_id = db.execute(
            """
            INSERT INTO budget_plans (user_id, month)
            VALUES (?, ?)
            """,
            user_id,
            database_month
        )
    except ValueError as error:
        raise ValidationError(
            f"A plan for {selected_month.strftime('%B')} already exists."
        ) from error

    copied_previous_plan = False

    if start_mode == "copy_previous":
        previous_plan = get_previous_budget_plan(
            db,
            user_id,
            database_month
        )

        if previous_plan:
            db.execute(
                """
                INSERT INTO budget_plan_items (
                    plan_id,
                    category_id,
                    amount
                )
                SELECT
                    ?,
                    category_id,
                    amount
                FROM budget_plan_items
                WHERE plan_id = ?
                """,
                new_plan_id,
                previous_plan["id"]
            )
            copied_previous_plan = True

    return new_plan_id, copied_previous_plan


def load_saved_plan_months(db, user_id):
    """Load the months that have saved plan headers."""
    rows = db.execute(
        """
        SELECT id, month
        FROM budget_plans
        WHERE user_id = ?
        ORDER BY month DESC
        """,
        user_id
    )

    saved_months = []

    for row in rows:
        month_date = datetime.strptime(row["month"], "%Y-%m-%d").date()
        saved_months.append({
            "id": row["id"],
            "value": month_date.strftime("%Y-%m"),
            "label": month_date.strftime("%B")
        })

    return saved_months


def load_user_categories(db, user_id):
    """Load category names for future Plan form suggestions."""
    return db.execute(
        """
        SELECT id, name, type
        FROM categories
        WHERE user_id = ?
        ORDER BY type, name
        """,
        user_id
    )


def load_budget_plan_items(db, user_id, plan_id):
    """Load the category allocations in one of the user's plans."""
    return db.execute(
        """
        SELECT
            budget_plan_items.id,
            budget_plan_items.category_id,
            budget_plan_items.amount,
            categories.name AS category_name,
            categories.type AS category_type
        FROM budget_plan_items

        JOIN budget_plans
            ON budget_plans.id = budget_plan_items.plan_id

        JOIN categories
            ON categories.id = budget_plan_items.category_id
            AND categories.user_id = budget_plans.user_id

        WHERE budget_plan_items.plan_id = ?
          AND budget_plans.user_id = ?

        ORDER BY
            CASE categories.type
                WHEN 'income' THEN 1
                ELSE 2
            END,
            categories.name
        """,
        plan_id,
        user_id
    )


def get_owned_plan_item(db, user_id, item_id):
    """Find a plan item only when its plan belongs to the current user."""
    rows = db.execute(
        """
        SELECT
            budget_plan_items.id,
            budget_plan_items.plan_id,
            budget_plan_items.category_id,
            budget_plan_items.amount,
            categories.type AS category_type
        FROM budget_plan_items

        JOIN budget_plans
            ON budget_plans.id = budget_plan_items.plan_id

        JOIN categories
            ON categories.id = budget_plan_items.category_id
            AND categories.user_id = budget_plans.user_id

        WHERE budget_plan_items.id = ?
          AND budget_plans.user_id = ?
        LIMIT 1
        """,
        item_id,
        user_id
    )

    return rows[0] if rows else None


def add_budget_plan_item(
    db,
    user_id,
    plan_id,
    category_id,
    amount
):
    """Add one category allocation to an owned monthly plan."""
    owned_plan = db.execute(
        """
        SELECT id
        FROM budget_plans
        WHERE id = ?
          AND user_id = ?
        LIMIT 1
        """,
        plan_id,
        user_id
    )

    if not owned_plan:
        raise ValidationError("Plan not found.")

    owned_category = db.execute(
        """
        SELECT id
        FROM categories
        WHERE id = ?
          AND user_id = ?
        LIMIT 1
        """,
        category_id,
        user_id
    )

    if not owned_category:
        raise ValidationError("Category not found.")

    existing_item = db.execute(
        """
        SELECT id
        FROM budget_plan_items
        WHERE plan_id = ?
          AND category_id = ?
        LIMIT 1
        """,
        plan_id,
        category_id
    )

    if existing_item:
        raise ValidationError(
            "That category is already included in this plan."
        )

    try:
        return db.execute(
            """
            INSERT INTO budget_plan_items (
                plan_id,
                category_id,
                amount
            )
            VALUES (?, ?, ?)
            """,
            plan_id,
            category_id,
            float(amount)
        )
    except ValueError as error:
        raise ValidationError(
            "That category is already included in this plan."
        ) from error


def update_budget_plan_item(db, user_id, item_id, amount):
    """Update a directly editable amount on an owned plan item."""
    if not get_owned_plan_item(db, user_id, item_id):
        raise ValidationError("Plan category not found.")

    db.execute(
        """
        UPDATE budget_plan_items
        SET amount = ?
        WHERE id = ?
        """,
        float(amount),
        item_id
    )


def remove_budget_plan_item(db, user_id, item_id):
    """Remove an item from one plan without deleting its category."""
    if not get_owned_plan_item(db, user_id, item_id):
        raise ValidationError("Plan category not found.")

    db.execute(
        """
        DELETE FROM budget_plan_items
        WHERE id = ?
        """,
        item_id
    )


def change_plan_item_category(
    db,
    user_id,
    item_id,
    new_category_name
):
    """Change the category used by one month without a global rename."""
    item = get_owned_plan_item(db, user_id, item_id)

    if not item:
        raise ValidationError("Plan category not found.")

    new_category_id = get_or_create_category(
        db,
        user_id,
        new_category_name,
        item["category_type"]
    )

    existing_item = db.execute(
        """
        SELECT id
        FROM budget_plan_items
        WHERE plan_id = ?
          AND category_id = ?
          AND id != ?
        LIMIT 1
        """,
        item["plan_id"],
        new_category_id,
        item_id
    )

    if existing_item:
        raise ValidationError(
            "That category is already included in this month's plan."
        )

    try:
        db.execute(
            """
            UPDATE budget_plan_items
            SET category_id = ?
            WHERE id = ?
            """,
            new_category_id,
            item_id
        )
    except ValueError as error:
        raise ValidationError(
            "That category is already included in this month's plan."
        ) from error


def organize_plan_items(plan_items):
    """Split items by type and calculate the three Plan summaries."""
    income_items = []
    expense_items = []
    planned_income = Decimal("0.00")
    planned_expenses = Decimal("0.00")

    for item in plan_items:
        item_amount = Decimal(str(item["amount"])).quantize(
            Decimal("0.01")
        )

        if item["category_type"] == "income":
            income_items.append(item)
            planned_income += item_amount
        else:
            expense_items.append(item)
            planned_expenses += item_amount

    return {
        "income_items": income_items,
        "expense_items": expense_items,
        "planned_income": planned_income,
        "planned_expenses": planned_expenses,
        "planned_remaining": planned_income - planned_expenses
    }


def validate_account_details(account_name, bank):
    """Clean and validate the editable account fields."""
    account_name = (account_name or "").strip()
    bank = (bank or "").strip() or None

    if not account_name:
        raise ValidationError("Account name is required.")

    if len(account_name) > 50:
        raise ValidationError(
            "Account name must be 50 characters or fewer."
        )

    if bank and len(bank) > 100:
        raise ValidationError("Bank name must be 100 characters or fewer.")

    return account_name, bank


def get_owned_account(db, user_id, account_id):
    """Find an account only when it belongs to the current user."""
    account_id = parse_record_id(account_id, "account")
    accounts = db.execute(
        """
        SELECT id, user_id, name, type, bank, active, created_at
        FROM accounts
        WHERE id = ?
          AND user_id = ?
        LIMIT 1
        """,
        account_id,
        user_id
    )

    if not accounts:
        raise ValidationError("Account not found.")

    return accounts[0]


def create_account(db, user_id, account_name, account_type, bank):
    """Create an active account for the current user."""
    account_name, bank = validate_account_details(account_name, bank)
    account_type = (account_type or "").strip().lower()

    try:
        return db.execute(
            """
            INSERT INTO accounts (user_id, name, type, bank, active)
            VALUES (?, ?, ?, ?, 1)
            """,
            user_id,
            account_name,
            account_type,
            bank
        )
    except ValueError as error:
        # The accounts table CHECK constraint validates the account type.
        raise ValidationError(
            "Please select a valid account type."
        ) from error


def update_account(db, user_id, account_id, account_name, bank):
    """Update an active account's name and optional bank."""
    account = get_owned_account(db, user_id, account_id)
    account_name, bank = validate_account_details(account_name, bank)

    if account["active"] != 1:
        raise ValidationError("Activate this account before editing it.")

    db.execute(
        """
        UPDATE accounts
        SET name = ?,
            bank = ?
        WHERE id = ?
          AND user_id = ?
          AND active = 1
        """,
        account_name,
        bank,
        account["id"],
        user_id
    )


def set_account_active(db, user_id, account_id, active_value):
    """Set one of the user's accounts to active (1) or inactive (0)."""
    account = get_owned_account(db, user_id, account_id)

    if active_value not in (0, 1):
        raise ValidationError("Choose a valid account status.")

    if account["active"] == active_value:
        status = "active" if active_value == 1 else "inactive"
        raise ValidationError(f"This account is already {status}.")

    db.execute(
        """
        UPDATE accounts
        SET active = ?
        WHERE id = ?
          AND user_id = ?
        """,
        active_value,
        account["id"],
        user_id
    )


def load_accounts(db, user_id, active_value):
    """Load active or inactive accounts and calculate page totals."""
    if active_value not in (0, 1):
        raise ValidationError("Choose a valid account status.")

    account_rows = db.execute(
        """
        SELECT
            accounts.id,
            accounts.name,
            accounts.type,
            accounts.bank,
            accounts.active,
            COALESCE(income_totals.total_income, 0) AS total_income,
            COALESCE(expense_totals.total_expenses, 0) AS total_expenses
        FROM accounts

        LEFT JOIN (
            SELECT account_id, SUM(amount) AS total_income
            FROM income
            WHERE user_id = ?
            GROUP BY account_id
        ) AS income_totals
            ON income_totals.account_id = accounts.id

        LEFT JOIN (
            SELECT account_id, SUM(amount) AS total_expenses
            FROM expenses
            WHERE user_id = ?
            GROUP BY account_id
        ) AS expense_totals
            ON expense_totals.account_id = accounts.id

        WHERE accounts.user_id = ?
          AND accounts.active = ?
        ORDER BY accounts.name COLLATE NOCASE
        """,
        user_id,
        user_id,
        user_id,
        active_value
    )

    total_income = 0
    total_expenses = 0
    total_balance = 0

    for account in account_rows:
        account["balance"] = (
            account["total_income"] - account["total_expenses"]
        )
        total_income += account["total_income"]
        total_expenses += account["total_expenses"]
        total_balance += account["balance"]

    return account_rows, total_income, total_expenses, total_balance


def get_transaction_settings(transaction_table):
    """Return trusted display and SQL settings for a transaction page."""
    transaction_settings = {
        "income": {
            "table": "income",
            "category_type": "income",
            "endpoint": "income",
            "label": "Income",
            "template": "income.html",
            "amount_class": "text-success",
            "empty_message": "No income has been recorded yet."
        },
        "expenses": {
            "table": "expenses",
            "category_type": "expense",
            "endpoint": "expenses",
            "label": "Expense",
            "template": "expenses.html",
            "amount_class": "text-danger",
            "empty_message": "No expenses have been recorded yet."
        }
    }

    try:
        return transaction_settings[transaction_table]
    except KeyError as error:
        raise ValueError("Unsupported transaction table.") from error


def parse_transaction_limit(value):
    """Return one of the supported transaction preview sizes."""
    if value == "all":
        return None

    try:
        page_limit = int(value)
    except (TypeError, ValueError):
        return 10

    return page_limit if page_limit in (10, 25, 50) else 10


def validate_transaction_amount(value):
    """Return a positive transaction amount with at most two decimals."""
    try:
        amount = validate_plan_amount(value)
    except ValidationError as error:
        raise ValidationError(
            "Enter an amount greater than zero with no more than "
            "two decimal places."
        ) from error

    if amount == 0:
        raise ValidationError(
            "Enter an amount greater than zero with no more than "
            "two decimal places."
        )

    return amount


def validate_transaction_description(value):
    """Clean an optional transaction description."""
    description = (value or "").strip()

    if len(description) > 150:
        raise ValidationError(
            "Description must be 150 characters or fewer."
        )

    return description or None


def validate_transaction_date(value):
    """Validate an HTML date and return SQLite's date representation."""
    try:
        return datetime.strptime(
            (value or "").strip(),
            "%Y-%m-%d"
        ).date().isoformat()
    except ValueError as error:
        raise ValidationError("Select a valid date.") from error


def validate_transaction_account(db, user_id, value):
    """Return an account ID only when the account belongs to the user."""
    account_id = parse_record_id(value, "account")
    account = db.execute(
        """
        SELECT id
        FROM accounts
        WHERE id = ?
          AND user_id = ?
          AND active = 1
        LIMIT 1
        """,
        account_id,
        user_id
    )

    if not account:
        raise ValidationError("Select a valid account.")

    return account_id


def validate_transaction_fields(db, user_id, submitted_form):
    """Validate shared add/edit fields and retain safe form values."""
    form_data = {
        "amount": (submitted_form.get("amount") or "").strip(),
        "category": (submitted_form.get("category") or "").strip(),
        "description": (
            submitted_form.get("description") or ""
        ).strip(),
        "account_id": (
            submitted_form.get("account_id") or ""
        ).strip(),
        "date": (submitted_form.get("date") or "").strip()
    }
    errors = {}
    transaction_data = {}

    validators = {
        "amount": lambda: validate_transaction_amount(
            form_data["amount"]
        ),
        "category": lambda: validate_category_name(
            form_data["category"]
        ),
        "description": lambda: validate_transaction_description(
            form_data["description"]
        ),
        "account_id": lambda: validate_transaction_account(
            db,
            user_id,
            form_data["account_id"]
        ),
        "date": lambda: validate_transaction_date(form_data["date"])
    }

    for field, validator in validators.items():
        try:
            transaction_data[field] = validator()
        except ValidationError as error:
            errors[field] = str(error)

    return transaction_data, form_data, errors


def get_owned_transaction(db, transaction_table, user_id, transaction_id):
    """Find a transaction only in the requested user's transaction table."""
    table = get_transaction_settings(transaction_table)["table"]
    rows = db.execute(
        f"""
        SELECT id, user_id, amount, category_id, description, account_id, date
        FROM {table}
        WHERE id = ?
          AND user_id = ?
        LIMIT 1
        """,
        transaction_id,
        user_id
    )

    if not rows:
        raise ValidationError("Transaction not found.")

    return rows[0]


def create_transaction(db, transaction_table, user_id, transaction_data):
    """Insert a validated income or expense transaction."""
    table = get_transaction_settings(transaction_table)["table"]
    return db.execute(
        f"""
        INSERT INTO {table} (
            user_id,
            amount,
            category_id,
            description,
            account_id,
            date
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        user_id,
        float(transaction_data["amount"]),
        transaction_data["category_id"],
        transaction_data["description"],
        transaction_data["account_id"],
        transaction_data["date"]
    )


def set_recurrent(db, transaction_table, user_id, submitted_form):
    """Validate and save a recurring income or expense schedule."""
    settings = get_transaction_settings(transaction_table)
    category_type = settings["category_type"]

    recurring_form = {
        "amount": submitted_form.get("amount"),
        "category": submitted_form.get("category"),
        "description": submitted_form.get("description"),
        "account_id": submitted_form.get("account_id"),
        "date": submitted_form.get("start_date")
    }
    transaction_data, _, errors = validate_transaction_fields(
        db,
        user_id,
        recurring_form
    )

    if errors:
        raise ValidationError(" ".join(errors.values()))

    start_date = date.fromisoformat(transaction_data["date"])
    end_date_text = (submitted_form.get("end_date") or "").strip()
    end_date = None

    if end_date_text:
        end_date = date.fromisoformat(
            validate_transaction_date(end_date_text)
        )

        if end_date < start_date:
            raise ValidationError(
                "The end date cannot be before the start date."
            )

    frequency = (submitted_form.get("frequency") or "").strip()
    interval_days = None
    day_of_month = None

    if frequency == "weekly":
        interval_days = 7
    elif frequency == "biweekly":
        interval_days = 14
    elif frequency == "monthly":
        day_of_month = start_date.day
    elif frequency == "yearly":
        # This schema represents yearly schedules as 365-day intervals.
        interval_days = 365
    elif frequency == "custom":
        try:
            interval_days = int(submitted_form.get("interval_days"))
        except (TypeError, ValueError) as error:
            raise ValidationError(
                "Enter a valid number of days between occurrences."
            ) from error

        if not 1 <= interval_days <= 365:
            raise ValidationError(
                "The custom interval must be between 1 and 365 days."
            )
    else:
        raise ValidationError("Choose a recurring frequency.")

    category_id = get_or_create_category(
        db,
        user_id,
        transaction_data["category"],
        category_type
    )

    return db.execute(
        """
        INSERT INTO recurring_events (
            user_id,
            category_id,
            amount,
            description,
            account_id,
            start_date,
            end_date,
            next_date,
            interval_days,
            day_of_month
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        user_id,
        category_id,
        float(transaction_data["amount"]),
        transaction_data["description"],
        transaction_data["account_id"],
        start_date.isoformat(),
        end_date.isoformat() if end_date else None,
        start_date.isoformat(),
        interval_days,
        day_of_month
    )


def advance_recurrent_date(current_date, interval_days, day_of_month):
    """Return the occurrence after the supplied recurring date."""
    if interval_days is not None:
        return current_date + timedelta(days=int(interval_days))

    next_month = current_date.month + 1
    next_year = current_date.year

    if next_month == 13:
        next_month = 1
        next_year += 1

    next_day = min(
        int(day_of_month),
        monthrange(next_year, next_month)[1]
    )

    return date(next_year, next_month, next_day)


def process_recurrent_events(db, user_id, today=None):
    """Create one user's due transactions and advance them past today."""
    processing_date = today or date.today()

    due_events = db.execute(
        """
        SELECT
            recurring_events.id,
            recurring_events.user_id,
            recurring_events.category_id,
            recurring_events.amount,
            recurring_events.description,
            recurring_events.account_id,
            date(recurring_events.end_date) AS end_date,
            date(recurring_events.next_date) AS next_date,
            recurring_events.interval_days,
            recurring_events.day_of_month,
            categories.type AS category_type
        FROM recurring_events
        JOIN categories
          ON categories.id = recurring_events.category_id
         AND categories.user_id = recurring_events.user_id
        WHERE recurring_events.user_id = ?
          AND date(recurring_events.next_date) <= date(?)
          AND (
                recurring_events.end_date IS NULL
                OR date(recurring_events.next_date) <=
                   date(recurring_events.end_date)
          )
        ORDER BY recurring_events.next_date, recurring_events.id
        """,
        user_id,
        processing_date.isoformat()
    )

    created_count = 0

    for event in due_events:
        next_date = date.fromisoformat(event["next_date"])
        end_date = (
            date.fromisoformat(event["end_date"])
            if event["end_date"]
            else None
        )

        while (
            next_date <= processing_date
            and (end_date is None or next_date <= end_date)
        ):
            transaction_table = (
                "income"
                if event["category_type"] == "income"
                else "expenses"
            )

            create_transaction(
                db,
                transaction_table,
                event["user_id"],
                {
                    "amount": event["amount"],
                    "category_id": event["category_id"],
                    "description": event["description"],
                    "account_id": event["account_id"],
                    "date": next_date.isoformat()
                }
            )
            created_count += 1

            next_date = advance_recurrent_date(
                next_date,
                event["interval_days"],
                event["day_of_month"]
            )

        db.execute(
            """
            UPDATE recurring_events
            SET next_date = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND user_id = ?
            """,
            next_date.isoformat(),
            event["id"],
            user_id
        )

    return created_count


def update_transaction(
    db,
    transaction_table,
    user_id,
    transaction_id,
    transaction_data
):
    """Update one owned transaction without changing a category record."""
    table = get_transaction_settings(transaction_table)["table"]
    get_owned_transaction(
        db,
        transaction_table,
        user_id,
        transaction_id
    )
    db.execute(
        f"""
        UPDATE {table}
        SET amount = ?,
            category_id = ?,
            description = ?,
            account_id = ?,
            date = ?
        WHERE id = ?
          AND user_id = ?
        """,
        float(transaction_data["amount"]),
        transaction_data["category_id"],
        transaction_data["description"],
        transaction_data["account_id"],
        transaction_data["date"],
        transaction_id,
        user_id
    )


def delete_transaction(db, transaction_table, user_id, transaction_id):
    """Delete one owned transaction while leaving its category intact."""
    table = get_transaction_settings(transaction_table)["table"]
    get_owned_transaction(
        db,
        transaction_table,
        user_id,
        transaction_id
    )
    db.execute(
        f"""
        DELETE FROM {table}
        WHERE id = ?
          AND user_id = ?
        """,
        transaction_id,
        user_id
    )


def build_transaction_page_url(endpoint, current_limit, query_arguments):
    """Build an absolute page URL while retaining active filters."""
    arguments = query_arguments.to_dict(flat=False)
    arguments.pop("added", None)
    query = urlencode(arguments, doseq=True)
    path = url_for(
        endpoint,
        limit=current_limit,
        _external=True
    )

    return f"{path}?{query}" if query else path


def transaction_page(db, transaction_table, limit):
    """Handle the shared Income and Expenses page behavior."""
    settings = get_transaction_settings(transaction_table)
    table = settings["table"]
    category_type = settings["category_type"]
    endpoint = settings["endpoint"]
    label = settings["label"]
    user_id = session["user_id"]
    page_limit = parse_transaction_limit(limit)
    show_all = page_limit is None
    current_limit = "all" if show_all else page_limit
    transaction_page_url = build_transaction_page_url(
        endpoint,
        current_limit,
        request.args
    )

    accounts = db.execute(
        """
        SELECT id, name
        FROM accounts
        WHERE user_id = ?
          AND active = 1
        ORDER BY name
        """,
        user_id
    )
    categories = db.execute(
        """
        SELECT id, name
        FROM categories
        WHERE user_id = ?
          AND type = ?
        ORDER BY name
        """,
        user_id,
        category_type
    )
    errors = {}
    form_data = {
        "amount": "",
        "category": "",
        "description": "",
        "account_id": "",
        "date": datetime.now().strftime("%Y-%m-%d")
    }

    if request.method == "POST":
        action = (
            request.form.get("action") or "add_transaction"
        ).strip()

        if action == "delete_transaction":
            try:
                transaction_id = parse_record_id(
                    request.form.get("transaction_id"),
                    "transaction"
                )
                delete_transaction(
                    db,
                    transaction_table,
                    user_id,
                    transaction_id
                )
                flash(f"{label} deleted.", "success")
            except ValidationError as error:
                flash(str(error), "danger")

            return redirect(transaction_page_url)

        if action not in ("add_transaction", "update_transaction"):
            flash("Choose a valid transaction action.", "danger")
            return redirect(transaction_page_url)

        transaction_id = None
        if action == "update_transaction":
            try:
                transaction_id = parse_record_id(
                    request.form.get("transaction_id"),
                    "transaction"
                )
                get_owned_transaction(
                    db,
                    transaction_table,
                    user_id,
                    transaction_id
                )
            except ValidationError as error:
                flash(str(error), "danger")
                return redirect(transaction_page_url)

        transaction_data, form_data, errors = validate_transaction_fields(
            db,
            user_id,
            request.form
        )

        if not errors:
            try:
                transaction_data["category_id"] = get_or_create_category(
                    db,
                    user_id,
                    transaction_data["category"],
                    category_type
                )
            except ValidationError as error:
                errors["category"] = str(error)

        if errors and action == "update_transaction":
            flash(" ".join(errors.values()), "danger")
            return redirect(transaction_page_url)

        if not errors:
            if action == "add_transaction":
                create_transaction(
                    db,
                    transaction_table,
                    user_id,
                    transaction_data
                )
                flash(f"{label} added.", "success")
            else:
                update_transaction(
                    db,
                    transaction_table,
                    user_id,
                    transaction_id,
                    transaction_data
                )
                flash(f"{label} updated.", "success")

            return redirect(transaction_page_url)

    search = (request.args.get("q") or "").strip()
    start_date = (request.args.get("start") or "").strip()
    end_date = (request.args.get("end") or "").strip()
    minimum_text = (request.args.get("min") or "").strip()
    maximum_text = (request.args.get("max") or "").strip()
    selected_sort = request.args.get("sort") or "newest"

    selected_categories = []
    for value in request.args.getlist("category"):
        try:
            selected_categories.append(int(value))
        except ValueError:
            continue

    selected_accounts = []
    for value in request.args.getlist("account"):
        try:
            selected_accounts.append(int(value))
        except ValueError:
            continue

    filter_errors = {}
    minimum_amount = None
    maximum_amount = None
    parsed_start_date = None
    parsed_end_date = None

    if start_date:
        try:
            parsed_start_date = datetime.strptime(
                start_date,
                "%Y-%m-%d"
            ).date()
        except ValueError:
            filter_errors["date"] = "Select a valid date range."

    if end_date:
        try:
            parsed_end_date = datetime.strptime(
                end_date,
                "%Y-%m-%d"
            ).date()
        except ValueError:
            filter_errors["date"] = "Select a valid date range."

    if (
        parsed_start_date
        and parsed_end_date
        and parsed_start_date > parsed_end_date
    ):
        filter_errors["date"] = "The start date must be before the end date."

    if minimum_text:
        try:
            minimum_amount = Decimal(minimum_text)
            if not minimum_amount.is_finite() or minimum_amount < 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            minimum_amount = None
            filter_errors["amount"] = "Enter a valid minimum amount."

    if maximum_text:
        try:
            maximum_amount = Decimal(maximum_text)
            if not maximum_amount.is_finite() or maximum_amount < 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            maximum_amount = None
            filter_errors["amount"] = "Enter a valid maximum amount."

    if (
        minimum_amount is not None
        and maximum_amount is not None
        and minimum_amount > maximum_amount
    ):
        filter_errors["amount"] = (
            "The minimum amount cannot exceed the maximum amount."
        )

    conditions = [f"{table}.user_id = ?"]
    parameters = [user_id]

    if search:
        search_pattern = f"%{search}%"
        conditions.append(
            f"""
            (
                COALESCE({table}.description, '') LIKE ? COLLATE NOCASE
                OR categories.name LIKE ? COLLATE NOCASE
                OR accounts.name LIKE ? COLLATE NOCASE
            )
            """
        )
        parameters.extend([search_pattern, search_pattern, search_pattern])

    if parsed_start_date and "date" not in filter_errors:
        conditions.append(f"date({table}.date) >= date(?)")
        parameters.append(start_date)

    if parsed_end_date and "date" not in filter_errors:
        conditions.append(f"date({table}.date) <= date(?)")
        parameters.append(end_date)

    if selected_categories:
        placeholders = ", ".join("?" for _ in selected_categories)
        conditions.append(f"{table}.category_id IN ({placeholders})")
        parameters.extend(selected_categories)

    if selected_accounts:
        placeholders = ", ".join("?" for _ in selected_accounts)
        conditions.append(f"{table}.account_id IN ({placeholders})")
        parameters.extend(selected_accounts)

    if minimum_amount is not None and "amount" not in filter_errors:
        conditions.append(f"{table}.amount >= ?")
        parameters.append(float(minimum_amount))

    if maximum_amount is not None and "amount" not in filter_errors:
        conditions.append(f"{table}.amount <= ?")
        parameters.append(float(maximum_amount))

    sort_options = {
        "newest": f"{table}.date DESC, {table}.id DESC",
        "oldest": f"{table}.date ASC, {table}.id ASC",
        "amount_desc": f"{table}.amount DESC, {table}.date DESC",
        "amount_asc": f"{table}.amount ASC, {table}.date DESC",
        "description": (
            f"COALESCE({table}.description, '') COLLATE NOCASE ASC, "
            f"{table}.date DESC"
        )
    }

    if selected_sort not in sort_options:
        selected_sort = "newest"

    where_sql = " AND ".join(conditions)
    order_sql = sort_options[selected_sort]
    entries_sql = f"""
        SELECT
            {table}.id,
            {table}.amount,
            {table}.description,
            {table}.account_id,
            date({table}.date) AS raw_date,
            strftime('%m/%d/%Y', {table}.date) AS display_date,
            categories.name AS category,
            accounts.name AS account,
            accounts.active AS account_active
        FROM {table}
        JOIN categories
            ON categories.id = {table}.category_id
        JOIN accounts
            ON accounts.id = {table}.account_id
        WHERE {where_sql}
        ORDER BY {order_sql}
    """

    if show_all:
        entries = db.execute(entries_sql, *parameters)
        has_more = False
    else:
        entries = db.execute(
            entries_sql + " LIMIT ?",
            *parameters,
            page_limit + 1
        )
        has_more = len(entries) > page_limit
        entries = entries[:page_limit]

    summary = db.execute(
        f"""
        SELECT
            COALESCE(SUM(amount), 0) AS total,
            COUNT(*) AS count
        FROM {table}
        WHERE user_id = ?
          AND date(date, 'start of month') =
              date('now', 'localtime', 'start of month')
        """,
        user_id
    )[0]

    next_limit = None
    if has_more:
        if page_limit == 10:
            next_limit = 25
        elif page_limit == 25:
            next_limit = 50
        elif page_limit == 50:
            next_limit = "all"

    next_page_url = None
    if next_limit is not None:
        next_page_url = build_transaction_page_url(
            endpoint,
            next_limit,
            request.args
        )

    filters = {
        "q": search,
        "start": start_date,
        "end": end_date,
        "categories": selected_categories,
        "accounts": selected_accounts,
        "min": minimum_text,
        "max": maximum_text,
        "sort": selected_sort
    }

    return render_template(
        settings["template"],
        accounts=accounts,
        categories=categories,
        entries=entries,
        summary=summary,
        errors=errors,
        filter_errors=filter_errors,
        form_data=form_data,
        filters=filters,
        current_limit=current_limit,
        next_page_url=next_page_url,
        showing_all=show_all,
        transaction_page_url=transaction_page_url,
        transaction_amount_class=settings["amount_class"],
        transaction_empty_message=settings["empty_message"]
    ), 400 if errors else 200
