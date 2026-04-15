"""
StudyMarket — production Flask application.
Run: python app.py
"""
import os
from flask import Flask, render_template
from flask_wtf.csrf import CSRFProtect
from config import SECRET_KEY, UPLOAD_FOLDER, MAX_CONTENT_LENGTH

app = Flask(__name__)
app.secret_key               = SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = not os.environ.get("FLASK_DEBUG", "false").lower() == "true"
app.config["MAX_CONTENT_LENGTH"]      = MAX_CONTENT_LENGTH
app.config["UPLOAD_FOLDER"]           = UPLOAD_FOLDER
app.config["WTF_CSRF_TIME_LIMIT"]     = None  # don't expire CSRF tokens on long sessions

csrf = CSRFProtect(app)

# Ensure upload dirs exist
for sub in ("pdfs", "docs", "ppts", "previews"):
    os.makedirs(os.path.join(UPLOAD_FOLDER, sub), exist_ok=True)

# ── Blueprints ─────────────────────────────────────────────────────────────
from routes.auth_routes    import auth_bp
from routes.product_routes import product_bp
from routes.payment_routes import payment_bp   # Razorpay + wallet payments
from routes.wallet_routes  import wallet_bp    # Wallet dashboard + withdrawals
from routes.admin_routes   import admin_bp

app.register_blueprint(auth_bp)
app.register_blueprint(product_bp)
app.register_blueprint(payment_bp)
app.register_blueprint(wallet_bp)
app.register_blueprint(admin_bp)

# Exempt Razorpay AJAX endpoints from CSRF (they use HMAC signature verification instead)
csrf.exempt(payment_bp)

# ── DB Init — tables created in dependency order ───────────────────────────
from models import user_model, product_model, order_model, review_model
from models import wallet_model

with app.app_context():
    try:
        user_model.create_table()
        product_model.create_table()
        order_model.create_table()
        review_model.create_table()
        wallet_model.create_tables()
        print("✅  All database tables ready.")
    except Exception as e:
        print(f"⚠️  DB init warning: {e}")

# ── Error handlers ─────────────────────────────────────────────────────────
@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, msg="Access denied."), 403

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, msg="Page not found."), 404

@app.errorhandler(413)
def too_large(e):
    return render_template("error.html", code=413, msg="File too large. Max 50 MB."), 413

if __name__ == "__main__":
    app.run(debug=True, port=5000)
