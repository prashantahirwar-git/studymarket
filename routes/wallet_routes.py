"""
Wallet routes — balance, transactions, bank withdrawal requests.
"""
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, abort)
from models import wallet_model
from config import MIN_WITHDRAWAL_AMOUNT

wallet_bp = Blueprint("wallet", __name__, url_prefix="/wallet")


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
# Wallet Dashboard
# ─────────────────────────────────────────────────────────────────────────────
@wallet_bp.route("/")
@login_required
def dashboard():
    wallet       = wallet_model.get_wallet(session["user_id"])
    transactions = wallet_model.get_transactions(session["user_id"], limit=50)
    withdrawals  = wallet_model.get_user_withdrawals(session["user_id"])
    return render_template("wallet.html",
                           wallet=wallet,
                           transactions=transactions,
                           withdrawals=withdrawals,
                           min_withdrawal=MIN_WITHDRAWAL_AMOUNT)


# ─────────────────────────────────────────────────────────────────────────────
# Request Bank Withdrawal
# ─────────────────────────────────────────────────────────────────────────────
@wallet_bp.route("/withdraw", methods=["POST"])
@login_required
def withdraw():
    amount         = request.form.get("amount", "0")
    bank_name      = request.form.get("bank_name", "").strip()
    account_number = request.form.get("account_number", "").strip()
    ifsc_code      = request.form.get("ifsc_code", "").strip().upper()
    account_name   = request.form.get("account_name", "").strip()

    try:
        amount_val = round(float(amount), 2)
    except ValueError:
        flash("Invalid amount.", "error")
        return redirect(url_for("wallet.dashboard"))

    if amount_val < MIN_WITHDRAWAL_AMOUNT:
        flash(f"Minimum withdrawal is ₹{MIN_WITHDRAWAL_AMOUNT:.0f}.", "error")
        return redirect(url_for("wallet.dashboard"))

    if not all([bank_name, account_number, ifsc_code, account_name]):
        flash("All bank details are required.", "error")
        return redirect(url_for("wallet.dashboard"))

    # Basic IFSC validation (alphanumeric, length 11)
    if len(ifsc_code) != 11:
        flash("IFSC code must be 11 characters.", "error")
        return redirect(url_for("wallet.dashboard"))

    try:
        rid = wallet_model.request_withdrawal(
            user_id        = session["user_id"],
            amount         = amount_val,
            bank_name      = bank_name,
            account_number = account_number,
            ifsc_code      = ifsc_code,
            account_name   = account_name,
        )
        flash(f"Withdrawal request of ₹{amount_val:.2f} submitted. "
              f"Admin will process it within 2-3 business days.", "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("wallet.dashboard"))
