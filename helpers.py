from datetime import datetime
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
