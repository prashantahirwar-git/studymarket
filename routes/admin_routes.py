"""
Admin panel routes — content, users, orders, wallets, withdrawal approvals.
"""
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, abort)
from models import product_model, user_model, order_model
from models import wallet_model
from services.storage import delete_file

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("user_role") != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/")
@admin_required
def dashboard():
    products    = product_model.get_all_products_admin()
    users       = user_model.get_all_users()
    orders      = order_model.get_all_orders_admin()
    pending     = [p for p in products if p["status"] == "pending"]
    withdrawals = wallet_model.get_all_withdrawals()
    wallets     = wallet_model.get_all_wallets_admin()

    total_revenue = sum(
        float(o.get("buyer_amount") or 0)
        for o in orders if o["payment_status"] == "completed"
    )
    pending_withdrawals = [w for w in withdrawals if w["status"] == "pending"]

    return render_template("admin.html",
                           products=products, users=users, orders=orders,
                           pending=pending, withdrawals=withdrawals,
                           wallets=wallets,
                           pending_withdrawals=pending_withdrawals,
                           total_revenue=total_revenue)


# ── Product management ────────────────────────────────────────────────────────
@admin_bp.route("/product/<int:pid>/approve", methods=["POST"])
@admin_required
def approve_product(pid):
    product_model.update_product_status(pid, "approved")
    flash("Product approved and now visible on the marketplace.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/product/<int:pid>/reject", methods=["POST"])
@admin_required
def reject_product(pid):
    product_model.update_product_status(pid, "rejected")
    flash("Product rejected.", "info")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/product/<int:pid>/delete", methods=["POST"])
@admin_required
def delete_product(pid):
    # Get file_url before deleting DB row
    file_url = product_model.delete_product(pid)
    # Delete from Supabase Storage or local disk
    if file_url:
        deleted = delete_file(file_url)
        if not deleted:
            flash("Product DB record deleted but file could not be removed from storage.", "info")
            return redirect(url_for("admin.dashboard"))
    flash("Product and its file deleted permanently.", "info")
    return redirect(url_for("admin.dashboard"))


# ── User management ───────────────────────────────────────────────────────────
@admin_bp.route("/user/<int:uid>/delete", methods=["POST"])
@admin_required
def delete_user(uid):
    if uid == session["user_id"]:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("admin.dashboard"))
    user_model.delete_user(uid)
    flash("User deleted.", "info")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/user/<int:uid>/role", methods=["POST"])
@admin_required
def change_role(uid):
    role = request.form.get("role", "buyer")
    if role not in ("buyer", "seller", "admin"):
        flash("Invalid role.", "error")
        return redirect(url_for("admin.dashboard"))
    user_model.update_user_role(uid, role)
    flash(f"Role updated to '{role}'.", "success")
    return redirect(url_for("admin.dashboard"))


# ── Withdrawal management ──────────────────────────────────────────────────────
@admin_bp.route("/withdrawal/<int:rid>/approve", methods=["POST"])
@admin_required
def approve_withdrawal(rid):
    note = request.form.get("admin_note", "Transfer processed.").strip()
    wallet_model.approve_withdrawal(rid, note)
    flash("Withdrawal approved. Please process the bank transfer manually.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/withdrawal/<int:rid>/reject", methods=["POST"])
@admin_required
def reject_withdrawal(rid):
    note = request.form.get("admin_note", "Unable to process at this time.").strip()
    wallet_model.reject_withdrawal(rid, note)
    flash("Withdrawal rejected and amount refunded to user wallet.", "info")
    return redirect(url_for("admin.dashboard"))


# ── Manual wallet credit ────────────────────────────────────────────────────
@admin_bp.route("/wallet/credit", methods=["POST"])
@admin_required
def manual_credit():
    uid    = int(request.form.get("user_id", 0))
    amount = float(request.form.get("amount", 0))
    reason = request.form.get("reason", "Admin manual credit").strip()
    if uid and amount > 0:
        wallet_model.credit(uid, amount, "credit", reason, ref_id="admin")
        flash(f"₹{amount:.2f} credited to user #{uid}.", "success")
    else:
        flash("Invalid user or amount.", "error")
    return redirect(url_for("admin.dashboard"))
