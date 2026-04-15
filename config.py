import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# ── Supabase / PostgreSQL ─────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── Supabase Storage ──────────────────────────────────────────────────────────
SUPABASE_URL   = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY   = os.environ.get("SUPABASE_KEY", "")
STORAGE_BUCKET = os.environ.get("STORAGE_BUCKET", "study-materials")

# ── Flask ─────────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-in-production")

# ── Razorpay ──────────────────────────────────────────────────────────────────
RAZORPAY_KEY_ID     = os.environ.get("RAZORPAY_KEY_ID",     "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")

# ── Fee structure ─────────────────────────────────────────────────────────────
PLATFORM_FEE_PERCENT    = 5.0
PLATFORM_PROFIT_PERCENT = 3.0   # was PLATFORM_PROFIT_PERCE (typo fixed)
RAZORPAY_FEE_PERCENT    = 2.0

# ── Wallet ────────────────────────────────────────────────────────────────────
MIN_WITHDRAWAL_AMOUNT = 50.0

# ── Local uploads fallback ────────────────────────────────────────────────────
UPLOAD_FOLDER      = os.path.join(os.path.dirname(__file__), "uploads")
ALLOWED_EXTENSIONS = {"pdf", "docx", "ppt", "pptx", "doc"}
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_FILE_SIZE_MB   = 50
MAX_CONTENT_LENGTH = MAX_FILE_SIZE_MB * 1024 * 1024

UPLOAD_SUBFOLDERS = {
    "pdf":  "pdfs",
    "docx": "docs",
    "doc":  "docs",
    "ppt":  "ppts",
    "pptx": "ppts",
    "jpg":  "previews",
    "jpeg": "previews",
    "png":  "previews",
    "webp": "previews",
}