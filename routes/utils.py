"""
routes/utils.py — Shared decorators and helpers used across all blueprints.

Import from here instead of defining login_required / admin_required
in each route file.
"""
import re
import logging
from functools import wraps
from flask import session, redirect, url_for, flash, abort

logger = logging.getLogger(__name__)

# ── Auth decorators ───────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("user_role") != "admin":
            logger.warning(
                "Unauthorised admin access attempt by user_id=%s",
                session.get("user_id", "anon"),
            )
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── Input validation ──────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email)) and len(email) <= 255


def is_valid_ifsc(ifsc: str) -> bool:
    """IFSC: first 4 alpha, 5th always 0, last 6 alphanumeric."""
    return bool(re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc))
