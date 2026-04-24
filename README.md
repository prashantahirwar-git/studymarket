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


| Fonts | Sora + DM Sans (Google Fonts) |
