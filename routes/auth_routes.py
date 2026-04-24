"""
Authentication routes — register, login, logout.

Rate limiting on /login is applied via Flask-Limiter using a lazy
reference to the limiter instance created in app.py.
"""
import logging
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from models import user_model
from routes.utils import is_valid_email

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role     = request.form.get("role", "buyer")

        if not name or not email or not password:
            flash("All fields are required.", "error")
            return render_template("register.html")

        if len(name) > 120:
            flash("Name is too long (max 120 characters).", "error")
            return render_template("register.html")

        if not is_valid_email(email):
            flash("Please enter a valid email address.", "error")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("register.html")

        # Never allow self-registering as admin
        if role not in ("buyer", "seller"):
            role = "buyer"

        uid = user_model.create_user(name, email, password, role)
        if uid is None:
            # Generic message — do NOT reveal whether the email already exists
            flash(
                "Could not create account. "
                "If you already have an account, please log in.",
                "error",
            )
            return render_template("register.html")

        logger.info("New user registered: id=%s role=%s", uid, role)
        flash("Account created! Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = user_model.get_user_by_email(email)

        # Always run bcrypt even when user not found — prevents timing-based
        # email enumeration. Attacker cannot tell "no such user" from
        # "wrong password" by measuring response time.
        if user:
            password_ok = user_model.verify_password(password, user["password"])
        else:
            user_model.dummy_verify()
            password_ok = False

        if not user or not password_ok:
            logger.warning(
                "Failed login attempt for email=%s ip=%s",
                email, request.remote_addr,
            )
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        session["user_id"]   = user["id"]
        session["user_name"] = user["name"]
        session["user_role"] = user["role"]
        logger.info("User logged in: id=%s role=%s", user["id"], user["role"])
        flash(f"Welcome back, {user['name']}!", "success")

        if user["role"] == "admin":
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("product.index"))

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    uid = session.get("user_id")
    session.clear()
    logger.info("User logged out: id=%s", uid)
    flash("You have been logged out.", "info")
    return redirect(url_for("product.index"))
