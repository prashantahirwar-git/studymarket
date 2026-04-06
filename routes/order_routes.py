"""
order_routes.py — legacy shim.
Payment logic has moved to payment_routes.py.
This file is kept for any backward-compatible redirects.
"""
from flask import Blueprint

order_bp = Blueprint("order", __name__)
# All payment routes are now in payment_routes.py (payment_bp)
