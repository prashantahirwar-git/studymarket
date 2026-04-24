"""
Payment routes — Razorpay integration + wallet purchase.

Flow (Razorpay):
  1. POST /checkout/<pid>          → creates Razorpay order, renders checkout page
  2. Razorpay JS SDK handles card/UPI UI in browser
  3. POST /payment/verify          → backend HMAC signature check, credits wallets
  4. GET  /payment/success/<oid>   → success page
  5. POST /payment/fail            → marks pending order as failed (cancel/error)

Flow (Wallet):
  1. POST /checkout/<pid>          → user picks "Pay from Wallet"
  2. POST /wallet/confirm-purchase → confirmation step 1 (show amount)
  3. POST /wallet/execute-purchase → atomic debit + order in one DB transaction
"""
import hmac, hashlib, logging
import razorpay
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, abort, jsonify)
from config import (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET,
                    PLATFORM_FEE_PERCENT, PLATFORM_PROFIT_PERCENT)
from models import product_model, order_model
from models import wallet_model
from models.user_model import get_admin_user
from routes.utils import login_required

payment_bp = Blueprint("payment", __name__)
logger = logging.getLogger(__name__)

# ── Validate keys at startup — warn loudly rather than fail silently ──────────
if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    import warnings
    warnings.warn(
        "RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET is not set. "
        "Payment routes will fail at runtime. Set them in .env.",
        RuntimeWarning, stacklevel=2,
    )

rz_client = (
    razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    if (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)
    else None
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def compute_buyer_amount(seller_price: float) -> tuple:
    """Returns (seller_price, platform_fee, buyer_amount, profit)."""
    fee       = round(seller_price * PLATFORM_FEE_PERCENT / 100, 2)
    buyer_amt = round(seller_price + fee, 2)
    profit    = round(seller_price * PLATFORM_PROFIT_PERCENT / 100, 2)
    return seller_price, fee, buyer_amt, profit


def verify_razorpay_signature(order_id, payment_id, signature):
    """HMAC-SHA256 backend verification — the ONLY authoritative check."""
    msg      = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ─────────────────────────────────────────────────────────────────────────────
# Checkout
# ─────────────────────────────────────────────────────────────────────────────
@payment_bp.route("/checkout/<int:pid>", methods=["GET", "POST"])
@login_required
def checkout(pid):
    product = product_model.get_product_by_id(pid)
    if not product or product["status"] != "approved":
        abort(404)

    if product["seller_id"] == session["user_id"]:
        flash("You cannot buy your own material.", "error")
        return redirect(url_for("product.detail", pid=pid))

    if order_model.has_purchased(session["user_id"], pid):
        flash("You already own this material.", "info")
        return redirect(url_for("product.detail", pid=pid))

    seller_price, fee, buyer_amt, profit = compute_buyer_amount(float(product["price"]))
    wallet_balance = wallet_model.get_balance(session["user_id"])

    return render_template("checkout.html",
                           product=product,
                           seller_price=seller_price,
                           platform_fee=fee,
                           buyer_amount=buyer_amt,
                           wallet_balance=wallet_balance,
                           razorpay_key=RAZORPAY_KEY_ID)


# ─────────────────────────────────────────────────────────────────────────────
# Create Razorpay Order (AJAX)
# ─────────────────────────────────────────────────────────────────────────────
@payment_bp.route("/payment/create-order", methods=["POST"])
@login_required
def create_razorpay_order():
    if not rz_client:
        return jsonify({"error": "Payment gateway not configured. Contact support."}), 503

    pid = request.json.get("product_id")
    product = product_model.get_product_by_id(pid)
    if not product or product["status"] != "approved":
        return jsonify({"error": "Product not found"}), 404

    if order_model.has_purchased(session["user_id"], pid):
        return jsonify({"error": "Already purchased"}), 400

    seller_price, fee, buyer_amt, profit = compute_buyer_amount(float(product["price"]))
    amount_paise = int(buyer_amt * 100)

    rz_order = rz_client.order.create({
        "amount":   amount_paise,
        "currency": "INR",
        "receipt":  f"sm_pid_{pid}_uid_{session['user_id']}",
        "notes": {
            "product_id":   str(pid),
            "buyer_id":     str(session["user_id"]),
            "seller_id":    str(product["seller_id"]),
            "seller_price": str(seller_price),
            "platform_fee": str(fee),
        }
    })

    oid = order_model.create_order(
        user_id=session["user_id"],
        product_id=pid,
        seller_price=seller_price,
        platform_fee=fee,
        buyer_amount=buyer_amt,
        payment_method="razorpay",
        razorpay_order_id=rz_order["id"],
    )

    return jsonify({
        "razorpay_order_id": rz_order["id"],
        "amount":            amount_paise,
        "currency":          "INR",
        "order_id":          oid,
        "key":               RAZORPAY_KEY_ID,
        "name":              session["user_name"],
        "product_name":      product["title"],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Verify Razorpay Payment — fully atomic
# ─────────────────────────────────────────────────────────────────────────────
@payment_bp.route("/payment/verify", methods=["POST"])
@login_required
def verify_payment():
    """
    Verifies HMAC signature, then completes order + credits wallets
    inside a SINGLE DB transaction (complete_order_with_credits).
    If any step fails the order stays 'pending' and no money moves.
    """
    data          = request.json or {}
    rz_order_id   = data.get("razorpay_order_id", "")
    rz_payment_id = data.get("razorpay_payment_id", "")
    rz_signature  = data.get("razorpay_signature", "")

    # Step 1: HMAC verification
    if not verify_razorpay_signature(rz_order_id, rz_payment_id, rz_signature):
        logger.warning(
            "Invalid Razorpay signature — possible tampering. "
            "order_id=%s user_id=%s ip=%s",
            rz_order_id, session.get("user_id"), request.remote_addr,
        )
        return jsonify({"success": False,
                        "error": "Payment verification failed — invalid signature"}), 400

    # Step 2: Load order
    order = order_model.get_order_by_razorpay_id(rz_order_id)
    if not order:
        return jsonify({"success": False, "error": "Order not found"}), 404

    if order["payment_status"] == "completed":
        return jsonify({"success": True, "already": True,
                        "redirect": url_for("payment.success", oid=order["id"])})

    if order["user_id"] != session["user_id"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    # Step 3: Get product + admin (hard fail if no admin — no silent money loss)
    product = product_model.get_product_by_id(order["product_id"])
    try:
        admin_id = get_admin_user()["id"]
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500

    seller_price = float(order["seller_price"])
    profit       = round(seller_price * PLATFORM_PROFIT_PERCENT / 100, 2)
    seller_earn  = round(seller_price - profit, 2)

    # Step 4: Atomic complete + wallet credits
    try:
        order_model.complete_order_with_credits(
            order_id        = order["id"],
            rz_payment_id   = rz_payment_id,
            rz_signature    = rz_signature,
            seller_id       = product["seller_id"],
            admin_id        = admin_id,
            seller_earn     = seller_earn,
            platform_profit = profit,
            product_title   = product["title"],
        )
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to record payment: {e}"}), 500

    return jsonify({
        "success":  True,
        "redirect": url_for("payment.success", oid=order["id"])
    })


# ─────────────────────────────────────────────────────────────────────────────
# Payment Failure — called by JS on cancel / error
# ─────────────────────────────────────────────────────────────────────────────
@payment_bp.route("/payment/fail", methods=["POST"])
@login_required
def fail_payment():
    """
    Called by Razorpay JS when user cancels or payment errors out.
    Marks the dangling pending order as 'failed' so it doesn't accumulate.
    """
    data        = request.json or {}
    rz_order_id = data.get("razorpay_order_id", "")
    if rz_order_id:
        order = order_model.get_order_by_razorpay_id(rz_order_id)
        if (order and order["user_id"] == session["user_id"]
                  and order["payment_status"] == "pending"):
            order_model.fail_order(order["id"])
    return jsonify({"success": True})


# ─────────────────────────────────────────────────────────────────────────────
# Payment Success Page
# ─────────────────────────────────────────────────────────────────────────────
@payment_bp.route("/payment/success/<int:oid>")
@login_required
def success(oid):
    order = order_model.get_order_by_id(oid)
    if not order or order["user_id"] != session["user_id"]:
        abort(404)
    product = product_model.get_product_by_id(order["product_id"])
    return render_template("payment_success.html", order=order, product=product)


# ─────────────────────────────────────────────────────────────────────────────
# Wallet Purchase — Step 1: Confirm
# ─────────────────────────────────────────────────────────────────────────────
@payment_bp.route("/wallet/confirm-purchase/<int:pid>", methods=["POST"])
@login_required
def wallet_confirm(pid):
    product = product_model.get_product_by_id(pid)
    if not product or product["status"] != "approved":
        abort(404)

    if product["seller_id"] == session["user_id"]:
        flash("You cannot buy your own material.", "error")
        return redirect(url_for("product.detail", pid=pid))

    if order_model.has_purchased(session["user_id"], pid):
        flash("You already own this material.", "info")
        return redirect(url_for("product.detail", pid=pid))

    seller_price = float(product["price"])
    wallet_bal   = wallet_model.get_balance(session["user_id"])

    if wallet_bal < seller_price:
        flash(f"Insufficient wallet balance. You have ₹{wallet_bal:.2f}, need ₹{seller_price:.2f}.", "error")
        return redirect(url_for("payment.checkout", pid=pid))

    profit = round(seller_price * PLATFORM_PROFIT_PERCENT / 100, 2)

    return render_template("wallet_confirm.html",
                           product=product,
                           seller_price=seller_price,
                           platform_profit=profit,
                           wallet_balance=wallet_bal)


# ─────────────────────────────────────────────────────────────────────────────
# Wallet Purchase — Step 2: Atomic Execute
# ─────────────────────────────────────────────────────────────────────────────
@payment_bp.route("/wallet/execute-purchase/<int:pid>", methods=["POST"])
@login_required
def wallet_execute(pid):
    """
    Atomically debits wallet AND creates+completes the order in one DB
    transaction via wallet_purchase_atomic(). If anything fails after the
    debit, the whole transaction rolls back — buyer never loses money without
    getting access.
    """
    product = product_model.get_product_by_id(pid)
    if not product or product["status"] != "approved":
        abort(404)

    if order_model.has_purchased(session["user_id"], pid):
        flash("You already own this material.", "info")
        return redirect(url_for("product.detail", pid=pid))

    seller_price = float(product["price"])
    profit       = round(seller_price * PLATFORM_PROFIT_PERCENT / 100, 2)

    try:
        admin_id = get_admin_user()["id"]
    except RuntimeError as e:
        flash(str(e), "error")
        return redirect(url_for("payment.checkout", pid=pid))

    try:
        oid = order_model.wallet_purchase_atomic(
            buyer_id        = session["user_id"],
            seller_id       = product["seller_id"],
            admin_id        = admin_id,
            product_id      = pid,
            seller_price    = seller_price,
            platform_profit = profit,
            product_title   = product["title"],
        )
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("payment.checkout", pid=pid))
    except Exception as e:
        flash(f"Purchase failed: {e}", "error")
        return redirect(url_for("payment.checkout", pid=pid))

    flash("Purchase successful! Your material is now unlocked.", "success")
    return redirect(url_for("payment.success", oid=oid))
