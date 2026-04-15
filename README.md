# 📚 StudyMarket — Production

A production-ready student-to-student marketplace for buying and selling study materials, with **Razorpay payments**, **wallets for every user**, and **bank withdrawal requests**.

---

## 🗂️ Project Structure

```
study_market/
├── app.py                    ← Flask entry point
├── config.py                 ← DB, Razorpay keys, fee structure
├── requirements.txt
├── setup_db.sql              ← Create MySQL DB
├── seed_admin.py             ← Create first admin account
├── .env.example              ← Copy to .env with real credentials
│
├── models/
│   ├── user_model.py         ← Users, roles, bcrypt passwords
│   ├── product_model.py      ← Study material CRUD
│   ├── order_model.py        ← Orders (Razorpay + wallet)
│   ├── review_model.py       ← Ratings & comments
│   └── wallet_model.py       ← Wallets, transactions, withdrawals
│
├── routes/
│   ├── auth_routes.py        ← /register /login /logout
│   ├── product_routes.py     ← / /upload /product/<id> /download
│   ├── payment_routes.py     ← /checkout /payment/create-order
│   │                           /payment/verify /payment/success
│   │                           /wallet/confirm-purchase
│   │                           /wallet/execute-purchase
│   ├── wallet_routes.py      ← /wallet/ /wallet/withdraw
│   └── admin_routes.py       ← /admin/* (full management)
│
├── templates/
│   ├── index.html            ← Marketplace homepage
│   ├── login.html / register.html
│   ├── upload.html           ← Seller file upload
│   ├── product.html          ← Detail + reviews
│   ├── checkout.html         ← Payment method selection (Razorpay / Wallet)
│   ├── wallet_confirm.html   ← Wallet purchase confirmation (step 1 of 2)
│   ├── payment_success.html  ← Success screen
│   ├── wallet.html           ← Wallet dashboard + bank withdrawal form
│   ├── dashboard.html        ← Seller dashboard
│   ├── cart.html             ← Buyer's purchases
│   ├── admin.html            ← Admin panel (6 tabs)
│   └── error.html
│
├── static/css/main.css
├── static/js/main.js
└── uploads/{pdfs,docs,ppts}/
```

---

## ⚡ Quick Start

### 1. Prerequisites

- Python 3.8+
- MySQL 8.0+
- A Razorpay account (free at [razorpay.com](https://razorpay.com))

### 2. Install dependencies

```bash
cd study_market
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your MySQL password and Razorpay keys
```

Or edit `config.py` directly:

```python
DB_CONFIG = { "password": "YOUR_MYSQL_PASSWORD", ... }
RAZORPAY_KEY_ID     = "rzp_test_XXXXXXXXXXXXXXXX"
RAZORPAY_KEY_SECRET = "XXXXXXXXXXXXXXXXXXXXXXXX"
```

### 4. Create the database

```bash
mysql -u root -p < setup_db.sql
```

### 5. Start the app

```bash
python app.py
# → Tables auto-created on first launch
# → Server starts at http://localhost:5000
```

### 6. Create the admin account

```bash
python seed_admin.py
# → Email: admin@studymarket.com | Password: admin123
```

---

## 💳 Payment System

### Razorpay Integration (Production-Ready)

```
Buyer clicks Buy → /checkout/<pid>
  ↓
AJAX POST /payment/create-order
  → Backend creates Razorpay order (server-side)
  → Returns razorpay_order_id to frontend
  ↓
Razorpay JS SDK opens payment modal
  (UPI / Card / NetBanking / Wallets)
  ↓
User completes payment in Razorpay UI
  ↓
AJAX POST /payment/verify
  → Backend HMAC-SHA256 signature check
  → NO frontend trust — signature verified with secret key
  → On success: order marked complete, wallets credited
  ↓
Redirect to /payment/success/<oid>
```

**All verification happens on the backend. Frontend only initiates and passes through the signature — it cannot fake a payment.**

### Fee Structure

| Who pays / receives | Amount |
|---|---|
| Buyer pays | `seller_price × 1.05` (5% surcharge) |
| Razorpay deducts | ~2% of buyer amount |
| StudyMarket receives | ~3% of seller price → Admin wallet |
| Seller receives | `seller_price` → Seller wallet |

**Example: Seller sets ₹100**
- Buyer pays: ₹105
- Razorpay fee: ~₹2.10
- Net received: ₹102.90
- Seller wallet credited: ₹100
- Admin wallet credited: ₹2.90

### Wallet Purchases (Zero surcharge)
- Users can buy notes directly from their wallet balance
- No 5% surcharge (the surcharge exists only to cover Razorpay fees)
- Platform still takes 3% from seller's credit → admin wallet
- 2-step confirmation before deducting funds

---

## 👛 Wallet System

Every user (buyer, seller, admin) gets a wallet automatically.

### How money flows in:

| Event | Who gets credited |
|---|---|
| Razorpay payment verified | Seller + Admin (split) |
| Wallet purchase | Seller + Admin (split, no surcharge) |
| Admin manual credit | Any user |
| Withdrawal rejected | User (refund) |

### How money flows out:

| Event | Who gets debited |
|---|---|
| Wallet purchase | Buyer |
| Bank withdrawal request | User (immediately held) |

### Bank Withdrawals
1. User fills bank details + amount on `/wallet/`
2. Amount is deducted from wallet immediately (held in escrow)
3. Admin reviews in Admin Panel → Withdrawals tab
4. Admin approves → processes bank transfer manually (NEFT/IMPS)
5. If rejected → amount is refunded back to wallet

### Minimum withdrawal: ₹50

---

## 🗄️ Database Schema

### `wallets`
| Column | Type | Notes |
|---|---|---|
| id | INT PK | |
| user_id | INT UNIQUE FK | One wallet per user |
| balance | DECIMAL(12,2) | Current balance |
| updated_at | TIMESTAMP | Auto-updated |

### `wallet_transactions`
| Column | Type | Notes |
|---|---|---|
| id | INT PK | |
| wallet_id | INT FK | |
| user_id | INT FK | |
| type | ENUM | credit/debit/purchase/sale_credit/platform_fee/refund/withdrawal |
| amount | DECIMAL(12,2) | Always positive |
| balance_after | DECIMAL(12,2) | Balance snapshot after transaction |
| description | VARCHAR(300) | Human-readable label |
| ref_id | VARCHAR(120) | order_id or other reference |

### `withdrawal_requests`
| Column | Type | Notes |
|---|---|---|
| id | INT PK | |
| user_id | INT FK | |
| amount | DECIMAL(12,2) | |
| bank_name | VARCHAR(120) | |
| account_number | VARCHAR(30) | |
| ifsc_code | VARCHAR(20) | |
| account_name | VARCHAR(120) | |
| status | ENUM | pending/approved/rejected |
| admin_note | VARCHAR(300) | Admin response |

### `orders` (updated)
| Column | Type | Notes |
|---|---|---|
| seller_price | DECIMAL(10,2) | Price set by seller |
| platform_fee | DECIMAL(10,2) | Fee collected by platform |
| buyer_amount | DECIMAL(10,2) | Total paid by buyer |
| payment_method | ENUM | razorpay / wallet |
| razorpay_order_id | VARCHAR(120) | From Razorpay API |
| razorpay_payment_id | VARCHAR(120) | After payment |
| razorpay_signature | VARCHAR(300) | For audit trail |

---

## 🔒 Security

- Passwords hashed with **bcrypt**
- Razorpay payments verified with **HMAC-SHA256** on backend — frontend cannot spoof
- Session-based authentication with role checks
- File type whitelist (no executables)
- File size limit (50 MB)
- Download gated behind purchase verification
- Wallet operations use **atomic MySQL transactions** — no double-spend
- `FOR UPDATE` row locking during wallet debit to prevent race conditions

---

## 🚀 Going Live (Production Checklist)

1. **Switch Razorpay keys** from `rzp_test_*` to `rzp_live_*`
2. Set `DEBUG = False` in `app.py`
3. Generate a strong `SECRET_KEY` (32+ random chars)
4. Use **Gunicorn** as WSGI server: `gunicorn -w 4 app:app`
5. Serve `/uploads` directly via **Nginx** (bypass Flask for static files)
6. Use **environment variables** for all secrets (never commit `.env`)
7. Enable **HTTPS** via Let's Encrypt
8. Set up **MySQL backups** (daily at minimum)
9. Configure Razorpay **webhook** for payment.captured events as backup verification
10. Change admin password in `seed_admin.py` before running

---

## 🎨 Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3 + Flask |
| Database | MySQL 8 (raw queries, no ORM) |
| Payments | Razorpay (production SDK) |
| Auth | bcrypt + Flask sessions |
| Frontend | HTML5 + CSS3 + Vanilla JS |
| Fonts | Sora + DM Sans (Google Fonts) |
