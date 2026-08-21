from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, make_response
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash

import helpers

# Configure application
app = Flask(__name__)

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///Budget.db")

@app.route("/")
def index():
    # if user is logged in
    if session:
        return render_template("index.html")
    return render_template("home.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html", errors={})

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    confirmation = request.form.get("confirmation") or ""

    errors = {}

    if not username:
        errors["username"] = "Please enter your email address."

    if not password:
        errors["password"] = "Please enter a password."
    elif len(password) < 8:
        errors["password"] = "Password must contain at least 8 characters."

    if not confirmation:
        errors["confirmation"] = "Please confirm your password."
    elif password != confirmation:
        errors["confirmation"] = "The passwords do not match."

    if errors:
        return render_template(
            "register.html",
            errors=errors,
            username=username
        ), 400

    hashed_password = generate_password_hash(
        password,
        method="pbkdf2:sha256"
    )

    try:
        db.execute(
            "INSERT INTO users (username, hash) VALUES (?, ?)",
            username,
            hashed_password
        )
    except ValueError:
        errors["username"] = "An account with this email already exists."

        return render_template(
            "register.html",
            errors=errors,
            username=username
        ), 409

    flash("Your account was created. You can now log in.", "success")
    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    login_error = "Invalid email or password."

    if not username or not password:
        return render_template(
            "login.html",
            login_error=login_error,
            username=username
        ), 400

    rows = db.execute(
        "SELECT * FROM users WHERE username = ?",
        username
    )

    if len(rows) != 1 or not check_password_hash(rows[0]["hash"], password):
        return render_template(
            "login.html",
            login_error=login_error,
            username=username
        ), 401

    session.clear()
    session["user_id"] = rows[0]["id"]
    session["username"] = rows[0]["username"]

    return redirect("/")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")
