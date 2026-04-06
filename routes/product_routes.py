"""
Product routes — uses services.storage for all file operations.
Works with both Supabase Storage (production) and local disk (dev).
"""
import os
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, abort)
from config import ALLOWED_EXTENSIONS
from models import product_model, order_model, review_model
from services.storage import upload_file, delete_file, get_download_response, is_supabase_enabled

product_bp = Blueprint("product", __name__)


# ── Auth decorator ────────────────────────────────────────────────────────────
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Routes ────────────────────────────────────────────────────────────────────
@product_bp.route("/")
def index():
    search    = request.args.get("search", "").strip()
    subject   = request.args.get("subject", "").strip()
    max_price = request.args.get("max_price", "")
    college   = request.args.get("college", "").strip()

    products    = product_model.get_approved_products(
        search    = search    or None,
        subject   = subject   or None,
        max_price = float(max_price) if max_price else None,
        college   = college   or None,
    )
    subjects    = product_model.get_distinct_subjects()
    top_sellers = product_model.get_top_sellers(5)
    return render_template("index.html",
                           products=products, subjects=subjects,
                           top_sellers=top_sellers, search=search,
                           subject=subject, max_price=max_price, college=college)


@product_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if session.get("user_role") not in ("seller", "admin"):
        flash("Only sellers can upload materials.", "error")
        return redirect(url_for("product.index"))

    if request.method == "POST":
        title       = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        price       = request.form.get("price", "0")
        subject     = request.form.get("subject", "").strip()
        college     = request.form.get("college", "").strip()
        year_tag    = request.form.get("year_tag", "").strip()
        file_obj    = request.files.get("file")

        # ── Validation ────────────────────────────────────────────────────────
        if not title:
            flash("Title is required.", "error")
            return render_template("upload.html")
        if not file_obj or file_obj.filename == "":
            flash("Please select a file to upload.", "error")
            return render_template("upload.html")
        if not allowed_file(file_obj.filename):
            flash("Allowed file types: PDF, DOCX, DOC, PPT, PPTX.", "error")
            return render_template("upload.html")

        try:
            price_val = float(price)
            if price_val < 0:
                price_val = 0.0
        except ValueError:
            price_val = 0.0

        # ── Upload to Supabase Storage (or local fallback) ────────────────────
        try:
            file_url, ext = upload_file(file_obj, file_obj.filename)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("upload.html")
        except Exception as e:
            flash(f"Upload failed: {e}", "error")
            return render_template("upload.html")

        # ── Save metadata to DB ───────────────────────────────────────────────
        product_model.create_product(
            title=title, description=description, price=price_val,
            file_url=file_url, file_type=ext,
            subject=subject, college=college, year_tag=year_tag,
            seller_id=session["user_id"],
        )
        flash("Upload successful! Your material is pending admin approval.", "success")
        return redirect(url_for("product.seller_dashboard"))

    return render_template("upload.html", supabase=is_supabase_enabled())


@product_bp.route("/product/<int:pid>")
def detail(pid):
    product   = product_model.get_product_by_id(pid)
    if not product or product["status"] != "approved":
        abort(404)
    reviews   = review_model.get_product_reviews(pid)
    purchased = reviewed = False
    if "user_id" in session:
        purchased = order_model.has_purchased(session["user_id"], pid)
        reviewed  = review_model.has_reviewed(session["user_id"], pid)
    return render_template("product.html",
                           product=product, reviews=reviews,
                           purchased=purchased, reviewed=reviewed)


@product_bp.route("/product/<int:pid>/buy", methods=["POST"])
@login_required
def buy(pid):
    product = product_model.get_product_by_id(pid)
    if not product or product["status"] != "approved":
        abort(404)
    if product["seller_id"] == session["user_id"]:
        flash("You cannot buy your own material.", "error")
        return redirect(url_for("product.detail", pid=pid))
    if order_model.has_purchased(session["user_id"], pid):
        flash("You already own this material.", "info")
        return redirect(url_for("product.detail", pid=pid))

    # Free materials complete instantly
    if float(product["price"]) == 0:
        oid = order_model.create_order(
            user_id=session["user_id"], product_id=pid,
            seller_price=0, platform_fee=0, buyer_amount=0,
            payment_method="wallet", razorpay_order_id=None,
        )
        order_model.complete_order(oid)
        flash("Free material unlocked! Download below.", "success")
        return redirect(url_for("product.detail", pid=pid))

    return redirect(url_for("payment.checkout", pid=pid))


@product_bp.route("/download/<int:pid>")
@login_required
def download(pid):
    product  = product_model.get_product_by_id(pid)
    if not product:
        abort(404)

    is_owner = (product["seller_id"] == session["user_id"])
    is_admin = (session.get("user_role") == "admin")

    if not (is_owner or is_admin or order_model.has_purchased(session["user_id"], pid)):
        flash("Please purchase this material first.", "error")
        return redirect(url_for("product.detail", pid=pid))

    product_model.increment_downloads(pid)

    # Sanitise filename for download
    safe_name = "".join(
        c if c.isalnum() or c in " ._-" else "_"
        for c in product["title"]
    ).strip()
    download_name = f"{safe_name}.{product['file_type']}"

    # Delegate to storage service (handles both Supabase signed URL & local)
    return get_download_response(product["file_url"], download_name)


@product_bp.route("/review/<int:pid>", methods=["POST"])
@login_required
def add_review(pid):
    if not order_model.has_purchased(session["user_id"], pid):
        flash("Only buyers who purchased this material can review.", "error")
        return redirect(url_for("product.detail", pid=pid))
    rating  = max(1, min(5, int(request.form.get("rating", 5))))
    comment = request.form.get("comment", "").strip()
    review_model.add_review(session["user_id"], pid, rating, comment)
    flash("Review submitted!", "success")
    return redirect(url_for("product.detail", pid=pid))


@product_bp.route("/dashboard")
@login_required
def seller_dashboard():
    if session.get("user_role") not in ("seller", "admin"):
        flash("Seller dashboard is only for sellers.", "error")
        return redirect(url_for("product.index"))
    products       = product_model.get_seller_products(session["user_id"])
    total_sales    = sum(p["total_sales"] for p in products)
    total_earnings = sum(float(p["total_earnings"] or 0) for p in products)
    orders         = order_model.get_user_orders(session["user_id"])
    return render_template("dashboard.html",
                           products=products,
                           total_sales=total_sales,
                           total_earnings=total_earnings,
                           orders=orders)


@product_bp.route("/cart")
@login_required
def cart():
    orders = order_model.get_user_orders(session["user_id"])
    return render_template("cart.html", orders=orders)
