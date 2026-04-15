"""
seed_admin.py — Run once to create the first admin account.
Usage: python seed_admin.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from models.user_model  import create_table, create_user, get_user_by_email
from models.product_model import create_table as pt
from models.order_model   import create_table as ot
from models.review_model  import create_table as rt
from models.wallet_model  import create_tables as wt

print("Creating tables...")
create_table(); pt(); ot(); rt(); wt()
print("Tables ready.")

ADMIN_EMAIL = "prashantahirwar850@gmail.com"
ADMIN_PASS  = "lj56iuhoaetrigljn374hjdf4gg8e"         # ← Change before deploying!
ADMIN_NAME  = "Prashant Ahirwar"

if get_user_by_email(ADMIN_EMAIL):
    print(f"Admin already exists: {ADMIN_EMAIL}")
else:
    uid = create_user(ADMIN_NAME, ADMIN_EMAIL, ADMIN_PASS, role="admin")
    print(f"✅ Admin created → email: {ADMIN_EMAIL}  password: {ADMIN_PASS}")
