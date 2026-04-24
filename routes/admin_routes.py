"""
Admin panel routes — content, users, orders, wallets, withdrawal approvals.
"""
import logging
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash)
from models import product_model, user_model, order_model
from models import wallet_model
from services.storage import delete_file
from routes.utils import admin_required

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

_MAX_MANUAL_CREDIT = 10_000.0   # ₹10,000 cap on single manual credit


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
    logger.info("Admin %s approved product %s", session["user_id"], pid)
    flash("Product approved and now visible on the marketplace.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/product/<int:pid>/reject", methods=["POST"])
@admin_required
def reject_product(pid):
    product_model.update_product_status(pid, "rejected")
    logger.info("Admin %s rejected product %s", session["user_id"], pid)
    flash("Product rejected.", "info")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/product/<int:pid>/delete", methods=["POST"])
@admin_required
def delete_product(pid):
    file_url, preview_url = product_model.delete_product(pid)

    # Delete main document from storage
    if file_url:
        if not delete_file(file_url):
            logger.warning("Could not delete file from storage: %s", file_url)

    # Delete preview image from storage
    if preview_url:
        if not delete_file(preview_url):
            logger.warning("Could not delete preview from storage: %s", preview_url)

    logger.info("Admin %s deleted product %s", session["user_id"], pid)
    flash("Product and its files deleted permanently.", "info")
    return redirect(url_for("admin.dashboard"))


# ── User management ───────────────────────────────────────────────────────────

@admin_bp.route("/user/<int:uid>/delete", methods=["POST"])
@admin_required
def delete_user(uid):
    if uid == session["user_id"]:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("admin.dashboard"))

    # Prevent deleting the only admin
    target = user_model.get_user_by_id(uid)
    if target and target["role"] == "admin":
        flash("Cannot delete an admin account.", "error")
        return redirect(url_for("admin.dashboard"))

    user_model.delete_user(uid)
    logger.info("Admin %s deleted user %s", session["user_id"], uid)
    flash("User deleted.", "info")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/user/<int:uid>/role", methods=["POST"])
@admin_required
def change_role(uid):
    role = request.form.get("role", "buyer")

    # Only buyer/seller allowed through this UI — admin role is seeded only
    if role not in ("buyer", "seller"):
        flash("Invalid role. Only 'buyer' or 'seller' can be assigned here.", "error")
        return redirect(url_for("admin.dashboard"))

    # Prevent demoting the only admin
    target = user_model.get_user_by_id(uid)
    if target and target["role"] == "admin":
        flash("Cannot change the admin account's role.", "error")
        return redirect(url_for("admin.dashboard"))

    user_model.update_user_role(uid, role)
    logger.info("Admin %s changed user %s role to %s", session["user_id"], uid, role)
    flash(f"Role updated to '{role}'.", "success")
    return redirect(url_for("admin.dashboard"))


# ── Withdrawal management ──────────────────────────────────────────────────────

@admin_bp.route("/withdrawal/<int:rid>/approve", methods=["POST"])
@admin_required
def approve_withdrawal(rid):
    note = request.form.get("admin_note", "Transfer processed.").strip()
    wallet_model.approve_withdrawal(rid, note)
    logger.info("Admin %s approved withdrawal %s", session["user_id"], rid)
    flash("Withdrawal approved. Please process the bank transfer manually.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/withdrawal/<int:rid>/reject", methods=["POST"])
@admin_required
def reject_withdrawal(rid):
    note = request.form.get("admin_note", "Unable to process at this time.").strip()
    wallet_model.reject_withdrawal(rid, note)
    logger.info("Admin %s rejected withdrawal %s", session["user_id"], rid)
    flash("Withdrawal rejected and amount refunded to user wallet.", "info")
    return redirect(url_for("admin.dashboard"))


# ── Manual wallet credit ──────────────────────────────────────────────────────

@admin_bp.route("/wallet/credit", methods=["POST"])
@admin_required
def manual_credit():
    try:
        uid    = int(request.form.get("user_id", 0))
        amount = round(float(request.form.get("amount", 0)), 2)
    except (ValueError, TypeError):
        flash("Invalid user or amount.", "error")
        return redirect(url_for("admin.dashboard"))

    reason = request.form.get("reason", "Admin manual credit").strip()[:200]

    if not uid or amount <= 0:
        flash("Invalid user or amount.", "error")
        return redirect(url_for("admin.dashboard"))

    if amount > _MAX_MANUAL_CREDIT:
        flash(f"Single credit cannot exceed ₹{_MAX_MANUAL_CREDIT:,.0f}. "
              f"Make multiple smaller credits if needed.", "error")
        return redirect(url_for("admin.dashboard"))

    # Verify user exists
    target = user_model.get_user_by_id(uid)
    if not target:
        flash(f"User #{uid} not found.", "error")
        return redirect(url_for("admin.dashboard"))

    wallet_model.credit(uid, amount, "credit", reason, ref_id="admin")
    logger.info("Admin %s manually credited ₹%.2f to user %s reason=%s",
                session["user_id"], amount, uid, reason)
    flash(f"₹{amount:.2f} credited to {target['name']} (#{uid}).", "success")
    return redirect(url_for("admin.dashboard"))
