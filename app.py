import re
from datetime import date, datetime

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import (
    ValidationError,
    add_budget_plan_item,
    change_plan_item_category,
    create_account,
    create_budget_plan,
    delete_category,
    delete_recurrent_event,
    get_budget_plan,
    get_or_create_category,
    load_budget_plan_items,
    load_accounts,
    load_saved_plan_months,
    load_recurrent_events,
    load_user_categories,
    login_required,
    organize_plan_items,
    parse_plan_month,
    parse_record_id,
    remove_budget_plan_item,
    shift_plan_month,
    set_account_active,
    set_recurrent,
    process_recurrent_events,
    rename_category,
    transaction_page,
    update_account,
    update_budget_plan_item,
    update_recurrent_event,
    usd,
    validate_plan_amount
)

# Configure application
app = Flask(__name__)

# Trust the public hostname and HTTPS scheme supplied by one Dev Tunnel proxy.
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_proto=1,
    x_host=1
)

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///budget.db")

@app.route("/")
def index():
    """Show the dashboard to signed-in users and the landing page to visitors."""
    user_id = session.get("user_id")

    if not user_id:
        return render_template("home.html")

    # Reuse the account and category loaders for the Dashboard add forms.
    accounts, _, _, _ = load_accounts(db, user_id, 1)
    categories = load_user_categories(db, user_id)
    income_categories = [
        category
        for category in categories
        if category["type"] == "income"
    ]
    expense_categories = [
        category
        for category in categories
        if category["type"] == "expense"
    ]
    add_form_data = {
        "amount": "",
        "category": "",
        "description": "",
        "account_id": "",
        "date": date.today().isoformat()
    }

    return render_template(
        "index.html",
        accounts=accounts,
        income_categories=income_categories,
        expense_categories=expense_categories,
        add_form_data=add_form_data
    )

@app.route("/register", methods=["GET", "POST"])
def register():
    # Display an empty registration form when the page is first opened.
    # Send empty errors dict to be able to refer to it unconditionally
    if request.method == "GET":
        return render_template("register.html", errors={})

    # Read the submitted values. Empty strings make the validation below simpler.
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    confirmation = request.form.get("confirmation") or ""

    # Store field-specific messages so Jinja can show each error beside its input.
    errors = {}

    # Validate the email address stored in the username column.
    if not username:
        errors["username"] = "Please enter your email address."
    elif not re.fullmatch(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$", username):
        errors["username"] = "Please enter a valid email address."

    # Require a password with a minimum length of eight characters.
    if not password:
        errors["password"] = "Please enter a password."
    elif len(password) < 8:
        errors["password"] = "Password must contain at least 8 characters."

    # Make sure the user confirms the exact same password.
    if not confirmation:
        errors["confirmation"] = "Please confirm your password."
    elif password != confirmation:
        errors["confirmation"] = "The passwords do not match."

    # Redisplay the form if any validation failed. Never send passwords back.
    if errors:
        return render_template(
            "register.html",
            errors=errors,
            username=username
        ), 400

    # Hash the password before storing it; plaintext passwords never enter the database.
    hashed_password = generate_password_hash(
        password,
        method="pbkdf2:sha256"
    )

    # Insert the account. The database's UNIQUE constraint rejects duplicate usernames.
    try:
        db.execute(
            "INSERT INTO users (username, hash) VALUES (?, ?)",
            username,
            hashed_password
        )
    except ValueError:
        # CS50 SQL raises ValueError when the UNIQUE username constraint is violated.
        errors["username"] = "An account with this email already exists."

        return render_template(
            "register.html",
            errors=errors,
            username=username
        ), 409

    # Confirm registration after redirecting to the login page.
    flash("Your account was created. You can now log in.", "success")
    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    # Display the login form when the page is first opened.
    if request.method == "GET":
        return render_template("login.html")

    # Read and clean the submitted credentials.
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    # Use one generic message so the response does not reveal registered accounts.
    login_error = "Invalid email or password."

    # Both credentials are required before querying the database.
    if not username or not password:
        return render_template(
            "login.html",
            login_error=login_error,
            username=username
        ), 400

    # Look up the account by its case-insensitive, indexed username.
    rows = db.execute(
        "SELECT * FROM users WHERE username = ?",
        username
    )

    # Reject an unknown username or a password that does not match the stored hash.
    if len(rows) != 1 or not check_password_hash(rows[0]["hash"], password):
        return render_template(
            "login.html",
            login_error=login_error,
            username=username
        ), 401

    # Start a clean authenticated session and keep the username for the profile menu.
    session.clear()
    session["user_id"] = rows[0]["id"]
    session["username"] = rows[0]["username"]

    # Send the authenticated user to the dashboard.
    return redirect("/")

@app.route("/logout")
def logout():
    # Remove all authentication data and return to the public landing page.
    session.clear()
    return redirect("/")


@app.route("/plan", methods=["GET", "POST"])
@login_required
def plan():
    """Display and update the signed-in user's monthly budget plan."""
    user_id = session["user_id"]

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        try:
            submitted_month = parse_plan_month(
                request.form.get("month")
            )
        except ValidationError as error:
            flash(str(error), "danger")
            return redirect(url_for("plan"))

        database_month = submitted_month.isoformat()
        redirect_month = submitted_month.strftime("%Y-%m")

        try:
            if action == "create_plan":
                start_mode = (
                    request.form.get("start_mode") or ""
                ).strip()

                _, copied_previous = create_budget_plan(
                    db,
                    user_id,
                    submitted_month,
                    start_mode
                )

                if start_mode == "copy_previous" and copied_previous:
                    flash(
                        "Plan created from the previous month's plan.",
                        "success"
                    )
                elif start_mode == "copy_previous":
                    flash(
                        "Plan created. No previous plan was available, "
                        "so it was started blank.",
                        "success"
                    )
                else:
                    flash("Blank plan created.", "success")

            elif action == "add_category":
                selected_plan = get_budget_plan(
                    db,
                    user_id,
                    database_month
                )

                if not selected_plan:
                    raise ValidationError(
                        "Create this month's plan before adding categories."
                    )

                amount = validate_plan_amount(
                    request.form.get("amount")
                )
                category_id = get_or_create_category(
                    db,
                    user_id,
                    request.form.get("category_name"),
                    request.form.get("category_type")
                )

                add_budget_plan_item(
                    db,
                    user_id,
                    selected_plan["id"],
                    category_id,
                    amount
                )

                flash("Category added to this plan.", "success")

            elif action == "update_item":
                item_id = parse_record_id(
                    request.form.get("item_id"),
                    "plan category"
                )
                amount = validate_plan_amount(
                    request.form.get("amount")
                )

                change_plan_item_category(
                    db,
                    user_id,
                    item_id,
                    request.form.get("category_name")
                )
                update_budget_plan_item(
                    db,
                    user_id,
                    item_id,
                    amount
                )

                flash("Plan item updated.", "success")

            elif action == "update_amount":
                item_id = parse_record_id(
                    request.form.get("item_id"),
                    "plan category"
                )
                amount = validate_plan_amount(
                    request.form.get("amount")
                )

                update_budget_plan_item(
                    db,
                    user_id,
                    item_id,
                    amount
                )

                flash("Planned amount updated.", "success")

            elif action == "remove_item":
                item_id = parse_record_id(
                    request.form.get("item_id"),
                    "plan category"
                )

                remove_budget_plan_item(db, user_id, item_id)

                flash(
                    "Category removed from this month's plan. "
                    "It is still available elsewhere.",
                    "success"
                )

            elif action == "change_item_category":
                item_id = parse_record_id(
                    request.form.get("item_id"),
                    "plan category"
                )

                change_plan_item_category(
                    db,
                    user_id,
                    item_id,
                    request.form.get("category_name")
                )

                flash(
                    "Category changed for this month's plan.",
                    "success"
                )

            else:
                raise ValidationError("Choose a valid plan action.")

        except ValidationError as error:
            flash(str(error), "danger")

        return redirect(
            url_for("plan", month=redirect_month)
        )

    requested_month = request.args.get("month")

    if requested_month is None:
        selected_month = date.today().replace(day=1)
    else:
        try:
            selected_month = parse_plan_month(requested_month)
        except ValidationError as error:
            flash(str(error), "danger")
            return redirect(url_for("plan"))

    database_month = selected_month.isoformat()
    selected_plan = get_budget_plan(db, user_id, database_month)

    if selected_plan:
        plan_items = load_budget_plan_items(
            db,
            user_id,
            selected_plan["id"]
        )
    else:
        plan_items = []

    plan_data = organize_plan_items(plan_items)
    previous_month = shift_plan_month(selected_month, -1)
    next_month = shift_plan_month(selected_month, 1)
    new_plan_months = []

    # The modal shows month names while each option carries its full year-month.
    for offset in range(12):
        month_option = shift_plan_month(selected_month, offset)
        new_plan_months.append({
            "label": month_option.strftime("%B"),
            "value": month_option.strftime("%Y-%m")
        })

    return render_template(
        "plan.html",
        selected_month=selected_month,
        selected_month_label=selected_month.strftime("%B"),
        selected_month_value=selected_month.strftime("%Y-%m"),
        previous_month_label=previous_month.strftime("%B"),
        previous_month_value=previous_month.strftime("%Y-%m"),
        next_month_label=next_month.strftime("%B"),
        next_month_value=next_month.strftime("%Y-%m"),
        new_plan_months=new_plan_months,
        new_plan_default_value=(
            next_month.strftime("%Y-%m")
            if selected_plan
            else selected_month.strftime("%Y-%m")
        ),
        plan=selected_plan,
        plan_exists=selected_plan is not None,
        saved_months=load_saved_plan_months(db, user_id),
        income_plan=plan_data["income_items"],
        expense_plan=plan_data["expense_items"],
        planned_income=plan_data["planned_income"],
        planned_expenses=plan_data["planned_expenses"],
        planned_remaining=plan_data["planned_remaining"],
        categories=load_user_categories(db, user_id)
    )

@app.route("/income", defaults={"limit": "10"}, methods=["GET", "POST"])
@app.route("/income/<limit>", methods=["GET", "POST"])
@login_required
def income(limit):
    action = (request.form.get("action") or "").strip()

    if request.method == "POST" and action == "recurrent":
        try:
            set_recurrent(
                db,
                "income",
                session["user_id"],
                request.form
            )
        except ValidationError as error:
            flash(str(error), "danger")

        return redirect(
            url_for("income", limit=limit, _external=True)
        )

    if request.method == "GET":
        process_recurrent_events(db, session["user_id"])

    # Plug the Income route into the shared transaction-page backend.
    return transaction_page(db, "income", limit)


@app.route("/expenses", defaults={"limit": "10"}, methods=["GET", "POST"])
@app.route("/expenses/<limit>", methods=["GET", "POST"])
@login_required
def expenses(limit):
    action = (request.form.get("action") or "").strip()

    if request.method == "POST" and action == "recurrent":
        try:
            set_recurrent(
                db,
                "expenses",
                session["user_id"],
                request.form
            )
        except ValidationError as error:
            flash(str(error), "danger")

        return redirect(
            url_for("expenses", limit=limit, _external=True)
        )

    if request.method == "GET":
        process_recurrent_events(db, session["user_id"])

    # Plug the Expenses route into the same backend with its own table and UI.
    return transaction_page(db, "expenses", limit)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Display and update the signed-in user's settings."""
    user_id = session["user_id"]

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        active_section = "account"
        category_type = (
            request.form.get("category_type") or "income"
        ).strip()
        recurring_type = (
            request.form.get("recurring_type") or "income"
        ).strip()
        redirect_arguments = {}

        try:
            if action == "update_email":
                email = (request.form.get("email") or "").strip()

                if not email:
                    raise ValidationError("Email address is required.")

                if not re.fullmatch(
                    r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$",
                    email
                ):
                    raise ValidationError(
                        "Please enter a valid email address."
                    )

                try:
                    db.execute(
                        """
                        UPDATE users
                        SET username = ?
                        WHERE id = ?
                        """,
                        email,
                        user_id
                    )
                except ValueError as error:
                    raise ValidationError(
                        "An account with this email already exists."
                    ) from error

                session["username"] = email

            elif action == "change_password":
                current_password = (
                    request.form.get("current_password") or ""
                )
                new_password = request.form.get("new_password") or ""
                confirmation = request.form.get("confirmation") or ""
                users = db.execute(
                    "SELECT hash FROM users WHERE id = ?",
                    user_id
                )

                if (
                    not users
                    or not check_password_hash(
                        users[0]["hash"],
                        current_password
                    )
                ):
                    raise ValidationError(
                        "Current password is incorrect."
                    )

                if len(new_password) < 8:
                    raise ValidationError(
                        "New password must contain at least 8 characters."
                    )

                if new_password != confirmation:
                    raise ValidationError(
                        "The new passwords do not match."
                    )

                password_hash = generate_password_hash(
                    new_password,
                    method="pbkdf2:sha256"
                )
                db.execute(
                    "UPDATE users SET hash = ? WHERE id = ?",
                    password_hash,
                    user_id
                )

            elif action == "add_category":
                active_section = "categories"

                if category_type not in {"income", "expense"}:
                    raise ValidationError(
                        "Choose a valid category type."
                    )

                get_or_create_category(
                    db,
                    user_id,
                    request.form.get("category_name"),
                    category_type
                )

            elif action == "rename_category":
                active_section = "categories"
                rename_category(
                    db,
                    user_id,
                    request.form.get("category_id"),
                    request.form.get("category_name")
                )

            elif action == "delete_category":
                active_section = "categories"
                category_type = delete_category(
                    db,
                    user_id,
                    request.form.get("category_id")
                )

            elif action == "update_recurrent":
                active_section = "recurring"
                recurring_type = update_recurrent_event(
                    db,
                    user_id,
                    request.form.get("recurring_event_id"),
                    request.form
                )

            elif action == "delete_recurrent":
                active_section = "recurring"
                recurring_type = delete_recurrent_event(
                    db,
                    user_id,
                    request.form.get("recurring_event_id")
                )

            else:
                raise ValidationError("Choose a valid settings action.")

        except ValidationError as error:
            flash(str(error), "danger")

            if action == "update_email":
                redirect_arguments["edit"] = "account"
            elif action in {"rename_category", "delete_category"}:
                redirect_arguments["edit_category"] = (
                    request.form.get("category_id")
                )
            elif action == "add_category":
                redirect_arguments["add_category"] = category_type
            elif action in {"update_recurrent", "delete_recurrent"}:
                redirect_arguments["edit_recurrent"] = (
                    request.form.get("recurring_event_id")
                )

        redirect_arguments["section"] = active_section

        if active_section == "categories":
            redirect_arguments["category_type"] = category_type

        if active_section == "recurring":
            redirect_arguments["recurring_type"] = recurring_type

        return redirect(
            url_for(
                "settings",
                **redirect_arguments,
                _external=True
            )
        )

    users = db.execute(
        """
        SELECT id, username, time_added
        FROM users
        WHERE id = ?
        LIMIT 1
        """,
        user_id
    )

    if not users:
        session.clear()
        return redirect(url_for("login", _external=True))

    user = users[0]

    try:
        member_since = datetime.fromisoformat(
            user["time_added"]
        ).strftime("%B %Y")
    except (TypeError, ValueError):
        member_since = ""

    categories = load_user_categories(db, user_id)
    income_categories = [
        category
        for category in categories
        if category["type"] == "income"
    ]
    expense_categories = [
        category
        for category in categories
        if category["type"] == "expense"
    ]
    accounts = db.execute(
        """
        SELECT id, name, active
        FROM accounts
        WHERE user_id = ?
        ORDER BY active DESC, name COLLATE NOCASE
        """,
        user_id
    )
    recurrent_events = load_recurrent_events(db, user_id)
    recurrent_income = [
        event
        for event in recurrent_events
        if event["category_type"] == "income"
    ]
    recurrent_expenses = [
        event
        for event in recurrent_events
        if event["category_type"] == "expense"
    ]
    active_section = request.args.get("section", "account")

    if active_section not in {"account", "categories", "recurring"}:
        active_section = "account"

    active_category_type = request.args.get(
        "category_type",
        "income"
    )

    if active_category_type not in {"income", "expense"}:
        active_category_type = "income"

    active_recurring_type = request.args.get(
        "recurring_type",
        "income"
    )

    if active_recurring_type not in {"income", "expense"}:
        active_recurring_type = "income"

    return render_template(
        "settings.html",
        user=user,
        member_since=member_since,
        accounts=accounts,
        income_categories=income_categories,
        expense_categories=expense_categories,
        recurrent_income=recurrent_income,
        recurrent_expenses=recurrent_expenses,
        active_section=active_section,
        active_category_type=active_category_type,
        active_recurring_type=active_recurring_type,
        edit_account=request.args.get("edit") == "account",
        edit_category_id=request.args.get("edit_category", type=int),
        adding_category_type=request.args.get("add_category"),
        edit_recurrent_id=request.args.get("edit_recurrent", type=int)
    )


@app.route("/accounts", methods=["GET", "POST"])
@login_required
def accounts():
    user_id = session["user_id"]
    show_inactive = request.args.get("status") == "inactive"
    active_value = 0 if show_inactive else 1
    accounts_url = url_for(
        "accounts",
        status="inactive" if show_inactive else None,
        _external=True
    )
    account_filter_url = url_for(
        "accounts",
        status=None if show_inactive else "inactive",
        _external=True
    )

    if request.method == "POST":
        action = (
            request.form.get("action") or "add_account"
        ).strip()

        try:
            if action == "add_account":
                create_account(
                    db,
                    user_id,
                    request.form.get("account_name"),
                    request.form.get("account_type"),
                    request.form.get("bank")
                )
                flash("Account added successfully.", "success")

            elif action == "update_account":
                update_account(
                    db,
                    user_id,
                    request.form.get("account_id"),
                    request.form.get("account_name"),
                    request.form.get("bank")
                )
                flash("Account updated successfully.", "success")

            elif action == "set_account_active":
                try:
                    new_active_value = int(request.form.get("active"))
                except (TypeError, ValueError) as error:
                    raise ValidationError(
                        "Choose a valid account status."
                    ) from error

                set_account_active(
                    db,
                    user_id,
                    request.form.get("account_id"),
                    new_active_value
                )
                status_label = (
                    "activated" if new_active_value == 1 else "deactivated"
                )
                flash(f"Account {status_label}.", "success")

            else:
                raise ValidationError("Choose a valid account action.")

        except ValidationError as error:
            flash(str(error), "danger")

        return redirect(accounts_url)

    (
        account_rows,
        total_income,
        total_expenses,
        total_balance
    ) = load_accounts(db, user_id, active_value)

    return render_template(
        "accounts.html",
        accounts=account_rows,
        total_income=total_income,
        total_expenses=total_expenses,
        total_balance=total_balance,
        account_count=len(account_rows),
        show_inactive=show_inactive,
        accounts_url=accounts_url,
        account_filter_url=account_filter_url
    )
