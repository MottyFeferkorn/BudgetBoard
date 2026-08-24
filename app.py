import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, make_response, url_for
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import login_required, usd

# Configure application
app = Flask(__name__)

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///Budget.db")

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

@app.route("/income", defaults={"limit": 10}, methods=["GET", "POST"])
@app.route("/income/<int:limit>", methods=["GET", "POST"])
def income(limit):
    # Authentication will be handled by a reusable decorator later.
    user_id = session["user_id"]

    # Keep the URL-controlled page size within the options offered by the page.
    allowed_limits = (10, 25, 50)
    if limit not in allowed_limits:
        limit = 10

    # Field-specific errors are passed back to the modal instead of being flashed.
    errors = {}

    if request.method == "POST":
        # Read and clean the submitted values before validating them.
        amount_text = (request.form.get("amount") or "").strip()
        category_name = (request.form.get("category") or "").strip()

        submitted_description = request.form.get("description")
        description = submitted_description.strip() if submitted_description else None

        account_id_text = (request.form.get("account_id") or "").strip()
        income_date = (request.form.get("date") or "").strip()

        cents_amount = None
        account_id = None

        # Decimal validates money precisely before it is converted for SQLite.
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

        # Categories are required and limited to a practical display length.
        if not category_name:
            errors["category"] = "Income category is required."
        elif len(category_name) > 50:
            errors["category"] = "Income category must be 50 characters or fewer."

        # An empty description is stored as SQL NULL.
        if description and len(description) > 150:
            errors["description"] = "Description must be 150 characters or fewer."

        # Verify the account ID and make sure it belongs to the current user.
        try:
            account_id = int(account_id_text)
        except ValueError:
            errors["account_id"] = "Select a valid account."
        else:
            account_rows = db.execute(
                "SELECT id FROM accounts WHERE id = ? AND user_id = ?",
                account_id,
                user_id
            )
            if len(account_rows) != 1:
                errors["account_id"] = "Select a valid account."

        # Require the exact date format submitted by an HTML date input.
        try:
            datetime.strptime(income_date, "%Y-%m-%d")
        except ValueError:
            errors["date"] = "Select a valid income date."

        if errors:
            # Preserve safe values so the user can correct the invalid fields.
            form_data = {
                "amount": amount_text,
                "category": category_name,
                "description": description if description is not None else "",
                "account_id": account_id_text,
                "date": income_date
            }
        else:
            # Reuse an existing income category, ignoring differences in case.
            category_rows = db.execute(
                """
                SELECT id
                FROM categories
                WHERE user_id = ?
                  AND type = 'income'
                  AND name = ? COLLATE NOCASE
                """,
                user_id,
                category_name
            )

            if category_rows:
                category_id = category_rows[0]["id"]
            else:
                # Save a new category so it becomes a future form suggestion.
                category_id = db.execute(
                    """
                    INSERT INTO categories (user_id, name, type)
                    VALUES (?, ?, 'income')
                    """,
                    user_id,
                    category_name
                )

            # SQLite cannot bind Decimal directly, so pass the validated value as a float.
            db.execute(
                """
                INSERT INTO income (
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
                income_date
            )

            # Redirect after insertion to prevent a refresh from resubmitting the form.
            return redirect(url_for("income", limit=limit, added=1))
    else:
        # Supply clean defaults when the page is opened normally.
        form_data = {
            "amount": "",
            "category": "",
            "description": "",
            "account_id": "",
            "date": datetime.now().strftime("%Y-%m-%d")
        }

    # GET requests and invalid POST requests both need form choices.
    accounts = db.execute(
        "SELECT id, name FROM accounts WHERE user_id = ? ORDER BY name",
        user_id
    )
    categories = db.execute(
        """
        SELECT id, name
        FROM categories
        WHERE user_id = ? AND type = 'income'
        ORDER BY name
        """,
        user_id
    )

    # Fetch one extra row to decide whether the Load More link is necessary.
    entries = db.execute(
        """
        SELECT
            income.id,
            income.amount,
            income.description,
            strftime('%m/%d/%Y', income.date) AS display_date,
            categories.name AS category,
            accounts.name AS account
        FROM income
        JOIN categories ON categories.id = income.category_id
        JOIN accounts ON accounts.id = income.account_id
        WHERE income.user_id = ?
        ORDER BY income.date DESC, income.id DESC
        LIMIT ?
        """,
        user_id,
        limit + 1
    )

    has_more = len(entries) > limit
    entries = entries[:limit]

    # Calculate the total and count for the user's current local month.
    summary = db.execute(
        """
        SELECT
            COALESCE(SUM(amount), 0) AS total,
            COUNT(*) AS count
        FROM income
        WHERE user_id = ?
          AND date(date, 'start of month') =
              date('now', 'localtime', 'start of month')
        """,
        user_id
    )[0]

    # Move through the supported limits only while another entry exists.
    next_limit = {10: 25, 25: 50, 50: None}[limit] if has_more else None

    return render_template(
        "income.html",
        accounts=accounts,
        categories=categories,
        entries=entries,
        summary=summary,
        errors=errors,
        form_data=form_data,
        current_limit=limit,
        next_limit=next_limit
    ), 400 if errors else 200

@app.route("/accounts", methods=["GET", "POST"])
def accounts():
    # Display the Accounts page when it is opened normally.
    if request.method == "GET":
        return render_template("accounts.html")

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
