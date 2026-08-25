from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urlencode

from flask import redirect, render_template, request, session, url_for


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


def transaction_page(db, transaction_table, limit):
    """Handle the shared Income and Expenses page behavior."""

    # Only these trusted settings may become SQL identifiers or template names.
    transaction_settings = {
        "income": {
            "category_type": "income",
            "endpoint": "income",
            "label": "Income",
            "template": "income.html"
        },
        "expenses": {
            "category_type": "expense",
            "endpoint": "expenses",
            "label": "Expense",
            "template": "expenses.html"
        }
    }

    if transaction_table not in transaction_settings:
        raise ValueError("Unsupported transaction table.")

    settings = transaction_settings[transaction_table]
    category_type = settings["category_type"]
    endpoint = settings["endpoint"]
    label = settings["label"]
    user_id = session["user_id"]

    # Support three preview sizes followed by an unpaginated final view.
    show_all = limit == "all"

    if show_all:
        page_limit = None
    else:
        try:
            page_limit = int(limit)
            if page_limit not in (10, 25, 50):
                raise ValueError
        except (TypeError, ValueError):
            page_limit = 10

    # Both normal requests and invalid submissions need these form choices.
    accounts = db.execute(
        "SELECT id, name FROM accounts WHERE user_id = ? ORDER BY name",
        user_id
    )
    categories = db.execute(
        """
        SELECT id, name
        FROM categories
        WHERE user_id = ? AND type = ?
        ORDER BY name
        """,
        user_id,
        category_type
    )

    account_ids = {account["id"] for account in accounts}
    errors = {}

    if request.method == "POST":
        # Read and clean the submitted transaction values.
        amount_text = (request.form.get("amount") or "").strip()
        category_name = (request.form.get("category") or "").strip()
        description = (
            (request.form.get("description") or "").strip() or None
        )
        account_id_text = (request.form.get("account_id") or "").strip()
        transaction_date = (request.form.get("date") or "").strip()

        cents_amount = None
        account_id = None

        # Decimal rejects malformed money and limits stored values to two decimals.
        try:
            amount = Decimal(amount_text)
            cents_amount = amount.quantize(Decimal("0.01"))

            if not amount.is_finite() or amount <= 0 or amount != cents_amount:
                errors["amount"] = (
                    "Enter an amount greater than zero with no more "
                    "than two decimal places."
                )
        except (InvalidOperation, ValueError):
            errors["amount"] = (
                "Enter an amount greater than zero with no more "
                "than two decimal places."
            )

        # Validate text before it reaches SQLite.
        if not category_name:
            errors["category"] = f"{label} category is required."
        elif len(category_name) > 50:
            errors["category"] = (
                f"{label} category must be 50 characters or fewer."
            )

        if description and len(description) > 150:
            errors["description"] = (
                "Description must be 150 characters or fewer."
            )

        # The selected account must belong to the current user.
        try:
            account_id = int(account_id_text)
        except ValueError:
            errors["account_id"] = "Select a valid account."
        else:
            if account_id not in account_ids:
                errors["account_id"] = "Select a valid account."

        # HTML date inputs submit values in YYYY-MM-DD format.
        try:
            datetime.strptime(transaction_date, "%Y-%m-%d")
        except ValueError:
            errors["date"] = "Select a valid date."

        if errors:
            # Preserve safe values while the user corrects the invalid fields.
            form_data = {
                "amount": amount_text,
                "category": category_name,
                "description": description or "",
                "account_id": account_id_text,
                "date": transaction_date
            }
        else:
            # Reuse a category already loaded for this user and transaction type.
            category_id = next(
                (
                    category["id"]
                    for category in categories
                    if category["name"].casefold() == category_name.casefold()
                ),
                None
            )

            if category_id is None:
                # A new category will appear as a suggestion after the redirect.
                category_id = db.execute(
                    """
                    INSERT INTO categories (user_id, name, type)
                    VALUES (?, ?, ?)
                    """,
                    user_id,
                    category_name,
                    category_type
                )

            # SQLite cannot bind Decimal directly, so store its validated float.
            db.execute(
                f"""
                INSERT INTO {transaction_table} (
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
                float(cents_amount),
                category_id,
                description,
                account_id,
                transaction_date
            )

            # Redirect after insertion so refreshing cannot duplicate the entry.
            return redirect(
                url_for(
                    endpoint,
                    limit="all" if show_all else page_limit,
                    added=1,
                    _external=True
                )
            )
    else:
        # Supply clean form defaults for a normal page request.
        form_data = {
            "amount": "",
            "category": "",
            "description": "",
            "account_id": "",
            "date": datetime.now().strftime("%Y-%m-%d")
        }

    # Read the active search, filter, and sorting values from the URL.
    search = (request.args.get("q") or "").strip()
    start_date = (request.args.get("start") or "").strip()
    end_date = (request.args.get("end") or "").strip()
    minimum_text = (request.args.get("min") or "").strip()
    maximum_text = (request.args.get("max") or "").strip()
    selected_sort = request.args.get("sort") or "newest"

    # Repeated query parameters allow multiple categories and accounts.
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

    # Validate both ends of the optional date range.
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

    # Validate both ends of the optional amount range.
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

    # Every query begins by restricting results to the current user.
    conditions = [f"{transaction_table}.user_id = ?"]
    parameters = [user_id]

    # Search descriptions, categories, and accounts together.
    if search:
        search_pattern = f"%{search}%"
        conditions.append(
            f"""
            (
                COALESCE({transaction_table}.description, '')
                    LIKE ? COLLATE NOCASE
                OR categories.name LIKE ? COLLATE NOCASE
                OR accounts.name LIKE ? COLLATE NOCASE
            )
            """
        )
        parameters.extend([search_pattern, search_pattern, search_pattern])

    if parsed_start_date and "date" not in filter_errors:
        conditions.append(f"date({transaction_table}.date) >= date(?)")
        parameters.append(start_date)

    if parsed_end_date and "date" not in filter_errors:
        conditions.append(f"date({transaction_table}.date) <= date(?)")
        parameters.append(end_date)

    if selected_categories:
        placeholders = ", ".join("?" for _ in selected_categories)
        conditions.append(
            f"{transaction_table}.category_id IN ({placeholders})"
        )
        parameters.extend(selected_categories)

    if selected_accounts:
        placeholders = ", ".join("?" for _ in selected_accounts)
        conditions.append(
            f"{transaction_table}.account_id IN ({placeholders})"
        )
        parameters.extend(selected_accounts)

    if minimum_amount is not None and "amount" not in filter_errors:
        conditions.append(f"{transaction_table}.amount >= ?")
        parameters.append(float(minimum_amount))

    if maximum_amount is not None and "amount" not in filter_errors:
        conditions.append(f"{transaction_table}.amount <= ?")
        parameters.append(float(maximum_amount))

    # Map public sort names to trusted SQL instead of using raw URL text.
    sort_options = {
        "newest": (
            f"{transaction_table}.date DESC, {transaction_table}.id DESC"
        ),
        "oldest": (
            f"{transaction_table}.date ASC, {transaction_table}.id ASC"
        ),
        "amount_desc": (
            f"{transaction_table}.amount DESC, {transaction_table}.date DESC"
        ),
        "amount_asc": (
            f"{transaction_table}.amount ASC, {transaction_table}.date DESC"
        ),
        "description": (
            f"COALESCE({transaction_table}.description, '') "
            f"COLLATE NOCASE ASC, {transaction_table}.date DESC"
        )
    }

    if selected_sort not in sort_options:
        selected_sort = "newest"

    where_sql = " AND ".join(conditions)
    order_sql = sort_options[selected_sort]

    entries_sql = f"""
        SELECT
            {transaction_table}.id,
            {transaction_table}.amount,
            {transaction_table}.description,
            strftime('%m/%d/%Y', {transaction_table}.date) AS display_date,
            categories.name AS category,
            accounts.name AS account
        FROM {transaction_table}
        JOIN categories
            ON categories.id = {transaction_table}.category_id
        JOIN accounts
            ON accounts.id = {transaction_table}.account_id
        WHERE {where_sql}
        ORDER BY {order_sql}
    """

    if show_all:
        # The final view intentionally omits LIMIT.
        entries = db.execute(entries_sql, *parameters)
        has_more = False
    else:
        # One extra row tells the page whether Load More is needed.
        entries = db.execute(
            entries_sql + " LIMIT ?",
            *parameters,
            page_limit + 1
        )
        has_more = len(entries) > page_limit
        entries = entries[:page_limit]

    # The summary remains the unfiltered total for the current local month.
    summary = db.execute(
        f"""
        SELECT
            COALESCE(SUM(amount), 0) AS total,
            COUNT(*) AS count
        FROM {transaction_table}
        WHERE user_id = ?
          AND date(date, 'start of month') =
              date('now', 'localtime', 'start of month')
        """,
        user_id
    )[0]

    # Advance from 10 to 25, then 50, and finally all remaining rows.
    next_limit = None
    if has_more:
        if page_limit == 10:
            next_limit = 25
        elif page_limit == 25:
            next_limit = 50
        elif page_limit == 50:
            next_limit = "all"

    # Keep active filters ready whether or not another page is available.
    next_arguments = request.args.to_dict(flat=False)
    next_arguments.pop("added", None)
    next_query = urlencode(next_arguments, doseq=True)

    next_page_url = None
    if next_limit is not None:
        next_path = url_for(endpoint, limit=next_limit)
        next_page_url = f"{next_path}?{next_query}" if next_query else next_path

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
        current_limit="all" if show_all else page_limit,
        next_page_url=next_page_url,
        showing_all=show_all
    ), 400 if errors else 200
