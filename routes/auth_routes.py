"""
Authentication routes — register, login, logout.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from models import user_model

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
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("register.html")
        if role not in ("buyer", "seller"):
            role = "buyer"

        uid = user_model.create_user(name, email, password, role)
        if uid is None:
            flash("Email already registered. Please log in.", "error")
            return render_template("register.html")

        flash("Account created! Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        print(f"DEBUG: Trying login for email: {email}")

        user = user_model.get_user_by_email(email)
        print(f"DEBUG: User found: {user}")

        if not user:
            print("DEBUG: No user found with that email")
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        password_check = user_model.verify_password(password, user["password"])
        print(f"DEBUG: Password check result: {password_check}")

        if not password_check:
            print("DEBUG: Password did not match")
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        session["user_id"]   = user["id"]
        session["user_name"] = user["name"]
        session["user_role"] = user["role"]
        print(f"DEBUG: Session set: {dict(session)}")
        flash(f"Welcome back, {user['name']}!", "success")

        if user["role"] == "admin":
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("product.index"))

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("product.index"))