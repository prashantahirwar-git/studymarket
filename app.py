"""
StudyMarket — production Flask application.
Run: python app.py
"""
import logging
import os
from flask import Flask, render_template
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import SECRET_KEY, UPLOAD_FOLDER, MAX_CONTENT_LENGTH

# ── Logging — structured, goes to stdout (Render captures it) ─────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key                        = SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = not os.environ.get("FLASK_DEBUG", "false").lower() == "true"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["MAX_CONTENT_LENGTH"]      = MAX_CONTENT_LENGTH
app.config["UPLOAD_FOLDER"]           = UPLOAD_FOLDER
app.config["WTF_CSRF_TIME_LIMIT"]     = None

# ── CSRF ──────────────────────────────────────────────────────────────────────
csrf = CSRFProtect(app)

# ── Rate limiter (backed by memory — swap to Redis storage for multi-worker) ──
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],           # no global limit — apply per-route only
    storage_uri="memory://",
)

# ── Upload dirs ───────────────────────────────────────────────────────────────
for sub in ("pdfs", "docs", "ppts", "previews"):
    os.makedirs(os.path.join(UPLOAD_FOLDER, sub), exist_ok=True)

# ── Blueprints ────────────────────────────────────────────────────────────────
from routes.auth_routes    import auth_bp
from routes.product_routes import product_bp
from routes.payment_routes import payment_bp
from routes.wallet_routes  import wallet_bp
from routes.admin_routes   import admin_bp

app.register_blueprint(auth_bp)
app.register_blueprint(product_bp)
app.register_blueprint(payment_bp)
app.register_blueprint(wallet_bp)
app.register_blueprint(admin_bp)

# Payment AJAX routes use Razorpay HMAC — exempt from CSRF token requirement
csrf.exempt(payment_bp)

# ── Per-route rate limits ─────────────────────────────────────────────────────
# Must use app.view_functions (not auth_bp.view_functions — blueprints don't
# populate their own view_functions dict). Applied after register_blueprint.
limiter.limit("10 per minute")(app.view_functions["auth.login"])
limiter.limit("5 per minute")(app.view_functions["auth.register"])

# ── DB Init ───────────────────────────────────────────────────────────────────
from models import user_model, product_model, order_model, review_model
from models import wallet_model

with app.app_context():
    try:
        user_model.create_table()
        product_model.create_table()
        order_model.create_table()
        review_model.create_table()
        wallet_model.create_tables()
        logger.info("All database tables ready.")
    except Exception as e:
        logger.warning("DB init warning: %s", e)

# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, msg="Access denied."), 403

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, msg="Page not found."), 404

@app.errorhandler(413)
def too_large(e):
    return render_template("error.html", code=413, msg="File too large. Max 50 MB."), 413

@app.errorhandler(429)
def rate_limited(e):
    return render_template("error.html", code=429,
                           msg="Too many attempts. Please wait a moment and try again."), 429

if __name__ == "__main__":
    app.run(debug=True, port=5000)
