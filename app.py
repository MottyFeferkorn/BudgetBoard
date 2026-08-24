import re

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import login_required, transaction_page, usd

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
