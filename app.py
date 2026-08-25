import re
from datetime import date

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import (
    ValidationError,
    add_budget_plan_item,
    change_plan_item_category,
    create_budget_plan,
    get_budget_plan,
    get_or_create_category,
    load_budget_plan_items,
    load_saved_plan_months,
    load_user_categories,
    login_required,
    organize_plan_items,
    parse_plan_month,
    parse_record_id,
    remove_budget_plan_item,
    shift_plan_month,
    transaction_page,
    update_budget_plan_item,
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
    # Show the dashboard to signed-in users and the landing page to visitors.
    if session:
        return render_template("index.html")
    return render_template("home.html")

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
    # Plug the Income route into the shared transaction-page backend.
    return transaction_page(db, "income", limit)


@app.route("/expenses", defaults={"limit": "10"}, methods=["GET", "POST"])
@app.route("/expenses/<limit>", methods=["GET", "POST"])
@login_required
def expenses(limit):
    # Plug the Expenses route into the same backend with its own table and UI.
    return transaction_page(db, "expenses", limit)


@app.route("/accounts", methods=["GET", "POST"])
def accounts():
    # Load each account with separately aggregated income and expense totals.
    if request.method == "GET":
        user_id = session["user_id"]

        account_rows = db.execute(
            """
            SELECT
                accounts.id,
                accounts.name,
                accounts.type,
                accounts.bank,
                COALESCE(income_totals.total_income, 0) AS total_income,
                COALESCE(expense_totals.total_expenses, 0) AS total_expenses
            FROM accounts

            LEFT JOIN (
                SELECT
                    account_id,
                    SUM(amount) AS total_income
                FROM income
                WHERE user_id = ?
                GROUP BY account_id
            ) AS income_totals
                ON income_totals.account_id = accounts.id

            LEFT JOIN (
                SELECT
                    account_id,
                    SUM(amount) AS total_expenses
                FROM expenses
                WHERE user_id = ?
                GROUP BY account_id
            ) AS expense_totals
                ON expense_totals.account_id = accounts.id

            WHERE accounts.user_id = ?
            ORDER BY accounts.name
            """,
            user_id,
            user_id,
            user_id
        )

        # Calculate each account balance and the combined balance in Python.
        total_balance = 0

        for account in account_rows:
            account["balance"] = (
                account["total_income"] - account["total_expenses"]
            )
            total_balance += account["balance"]

        return render_template(
            "accounts.html",
            accounts=account_rows,
            total_balance=total_balance,
            account_count=len(account_rows)
        )

    # Read and clean the submitted account details.
    name = (request.form.get("account_name") or "").strip()
    account_type = (request.form.get("account_type") or "").strip()
    bank = (request.form.get("bank") or "").strip() or None

    # Require the name field as the type will be inforced later and the bank is optional
    if not name:
        flash("Account name is required.", "danger")
        return redirect("/accounts")

    # Store the account under the currently signed-in user.
    try:
        db.execute(
            "INSERT INTO accounts (user_id, name, type, bank) VALUES (?, ?, ?, ?)",
            session["user_id"],
            name,
            account_type,
            bank
        )
    except ValueError:
        # Handle a database type-constraint failure without showing a server error.
        flash("Please select a valid account type.", "danger")
        return redirect("/accounts")

    # Confirm the insert after redirecting back to the Accounts page.
    flash("Account added successfully.", "success")
    return redirect("/accounts")

@app.route("/settings")
def settings():
    return render_template("settings.html")
