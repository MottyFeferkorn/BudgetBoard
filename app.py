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
    # if user visits by post handle registration
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirm_password = request.form.get("confirmation")

        # validates that user filled out all 3 fields
        if username and password and confirm_password:

            # validate that password and confirmation matches
            if password == confirm_password:

                # hash password
                hashed_password = generate_password_hash(password, method="pbkdf2:sha256")

                # try adding user if value error username exists
                try:
                    # update data base
                    db.execute("INSERT INTO users (username, hash) VALUES (?, ?)",
                               username, hashed_password)

                except ValueError:
                    return ...
                else:
                    return redirect("/login")
            else:
                return ...
        else:
            return ...
    # if user visits by get show the registration page
    else:
        return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
          ...

        # Ensure password was submitted
        elif not request.form.get("password"):
            ...

        # Query database for username
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            ...

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")
