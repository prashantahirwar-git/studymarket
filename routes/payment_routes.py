"""
Payment routes — Razorpay integration + wallet purchase.

Flow (Razorpay):
  1. POST /checkout/<pid>          → creates Razorpay order, renders checkout page
  2. Razorpay JS SDK handles card/UPI UI in browser
  3. POST /payment/verify          → backend HMAC signature check, credits wallets
  4. GET  /payment/success/<oid>   → success page

Flow (Wallet):
  1. POST /checkout/<pid>          → user picks "Pay from Wallet"
  2. POST /wallet/confirm-purchase → confirmation step 1 (show amount)
  3. POST /wallet/execute-purchase → confirmation step 2 (final debit)
"""
import hmac, hashlib, razorpay
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, abort, jsonify)
from config import (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET,
                    PLATFORM_FEE_PERCENT, PLATFORM_PROFIT_PERCE)
from models import product_model, order_model
from models import wallet_model
from models.user_model import get_all_users

payment_bp = Blueprint("payment", __name__)

# Razorpay client (production-ready)
rz_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def compute_buyer_amount(seller_price: float) -> tuple:
    """
    Returns (seller_price, platform_fee, buyer_amount) all as floats rounded to 2dp.
    buyer_amount = seller_price * (1 + PLATFORM_FEE_PERCENT/100)
    platform_profit (goes to admin wallet) = seller_price * PLATFORM_PROFIT_PERCE/100
    """
    fee        = round(seller_price * PLATFORM_FEE_PERCENT / 100, 2)
    buyer_amt  = round(seller_price + fee, 2)
    profit     = round(seller_price * PLATFORM_PROFIT_PERCE / 100, 2)
    return seller_price, fee, buyer_amt, profit


def get_admin_id():
    """Return the first admin user's ID for platform fee credit."""
    users = get_all_users()
    admins = [u for u in users if u["role"] == "admin"]
    return admins[0]["id"] if admins else None


def verify_razorpay_signature(order_id, payment_id, signature):
    """HMAC-SHA256 backend verification — the ONLY authoritative check."""
    msg      = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ─────────────────────────────────────────────────────────────────────────────
# Checkout — create Razorpay order
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
# Initiate Razorpay Order (AJAX call from checkout page)
# ─────────────────────────────────────────────────────────────────────────────
@payment_bp.route("/payment/create-order", methods=["POST"])
@login_required
def create_razorpay_order():
    """Creates a Razorpay order server-side and returns order_id to frontend."""
    pid = request.json.get("product_id")
    product = product_model.get_product_by_id(pid)
    if not product or product["status"] != "approved":
        return jsonify({"error": "Product not found"}), 404

    if order_model.has_purchased(session["user_id"], pid):
        return jsonify({"error": "Already purchased"}), 400

    seller_price, fee, buyer_amt, profit = compute_buyer_amount(float(product["price"]))

    # Razorpay amount is in paise (1 Rs = 100 paise)
    amount_paise = int(buyer_amt * 100)

    rz_order = rz_client.order.create({
        "amount":   amount_paise,
        "currency": "INR",
        "receipt":  f"sm_pid_{pid}_uid_{session['user_id']}",
        "notes": {
            "product_id":    str(pid),
            "buyer_id":      str(session["user_id"]),
            "seller_id":     str(product["seller_id"]),
            "seller_price":  str(seller_price),
            "platform_fee":  str(fee),
        }
    })

    # Persist pending order in our DB
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
# Verify Razorpay Payment — BACKEND ONLY, no frontend trust
# ─────────────────────────────────────────────────────────────────────────────
@payment_bp.route("/payment/verify", methods=["POST"])
@login_required
def verify_payment():
    """
    Called by Razorpay JS handler after user completes payment.
    We verify the signature on the BACKEND before crediting any wallet.
    """
    data = request.json or {}
    rz_order_id   = data.get("razorpay_order_id", "")
    rz_payment_id = data.get("razorpay_payment_id", "")
    rz_signature  = data.get("razorpay_signature", "")

    # ── Step 1: Signature verification (backend HMAC) ────────────────────────
    if not verify_razorpay_signature(rz_order_id, rz_payment_id, rz_signature):
        return jsonify({"success": False, "error": "Payment verification failed — invalid signature"}), 400

    # ── Step 2: Load our order record ────────────────────────────────────────
    order = order_model.get_order_by_razorpay_id(rz_order_id)
    if not order:
        return jsonify({"success": False, "error": "Order not found"}), 404

    if order["payment_status"] == "completed":
        return jsonify({"success": True, "already": True,
                        "redirect": url_for("payment.success", oid=order["id"])})

    if order["user_id"] != session["user_id"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    # ── Step 3: Fetch product + seller ───────────────────────────────────────
    product    = product_model.get_product_by_id(order["product_id"])
    seller_id  = product["seller_id"]
    admin_id   = get_admin_id()

    seller_price = float(order["seller_price"])
    platform_fee = float(order["platform_fee"])
    profit       = round(seller_price * PLATFORM_PROFIT_PERCE / 100, 2)
    seller_earn  = round(seller_price - profit, 2)

    # ── Step 4: Complete DB order + credit wallets ────────────────────────────
    order_model.complete_order(order["id"], rz_payment_id, rz_signature)

    # Credit seller wallet
    wallet_model.credit(seller_id, seller_earn, "sale_credit",
                        f"Sale: {product['title']}", str(order["id"]))
    # Credit admin wallet (platform profit)
    if admin_id:
        wallet_model.credit(admin_id, profit, "platform_fee",
                            f"Platform fee: {product['title']}", str(order["id"]))

    return jsonify({
        "success":  True,
        "redirect": url_for("payment.success", oid=order["id"])
    })


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
# Wallet Purchase — Step 1: Confirm (show summary)
# ─────────────────────────────────────────────────────────────────────────────
@payment_bp.route("/wallet/confirm-purchase/<int:pid>", methods=["POST"])
@login_required
def wallet_confirm(pid):
    """Step 1 of 2: Show buyer exactly what will be deducted."""
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

    # Wallet purchases are fee-free (platform profit comes from Razorpay top-ups)
    profit = round(seller_price * PLATFORM_PROFIT_PERCE / 100, 2)

    return render_template("wallet_confirm.html",
                           product=product,
                           seller_price=seller_price,
                           platform_profit=profit,
                           wallet_balance=wallet_bal)


# ─────────────────────────────────────────────────────────────────────────────
# Wallet Purchase — Step 2: Execute (final debit)
# ─────────────────────────────────────────────────────────────────────────────
@payment_bp.route("/wallet/execute-purchase/<int:pid>", methods=["POST"])
@login_required
def wallet_execute(pid):
    """Step 2 of 2: Actually debit wallet and complete order."""
    product = product_model.get_product_by_id(pid)
    if not product or product["status"] != "approved":
        abort(404)

    if order_model.has_purchased(session["user_id"], pid):
        flash("You already own this material.", "info")
        return redirect(url_for("product.detail", pid=pid))

    seller_price = float(product["price"])
    profit       = round(seller_price * PLATFORM_PROFIT_PERCE / 100, 2)
    seller_earn  = round(seller_price - profit, 2)
    admin_id     = get_admin_id()

    try:
        wallet_model.wallet_purchase(
            buyer_id     = session["user_id"],
            seller_id    = product["seller_id"],
            admin_id     = admin_id,
            product_id   = pid,
            seller_price = seller_price,
            platform_profit = profit,
            product_title   = product["title"],
        )
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("payment.checkout", pid=pid))

    # Record order as completed (wallet payment)
    oid = order_model.create_order(
        user_id=session["user_id"],
        product_id=pid,
        seller_price=seller_price,
        platform_fee=profit,
        buyer_amount=seller_price,     # no surcharge on wallet purchases
        payment_method="wallet",
        razorpay_order_id=None,
    )
    order_model.complete_order(oid)

    flash("Purchase successful! Your material is now unlocked.", "success")
    return redirect(url_for("payment.success", oid=oid))
