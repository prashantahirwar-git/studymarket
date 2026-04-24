# 🚀 StudyMarket — Full Deployment Guide
## Supabase (DB + Storage) + Render (Hosting) — 100% Free

---

## Prerequisites (all free)

| Service | What for | Sign up |
|---|---|---|
| **GitHub** | Host your code | github.com |
| **Supabase** | PostgreSQL DB + File Storage | supabase.com |
| **Render** | Run your Flask app | render.com |
| **Razorpay** | Real payments | razorpay.com |

---

## STEP 1 — Supabase: Create Project

1. Go to [supabase.com](https://supabase.com) → **Start your project** → **Sign in with GitHub**
2. Click **New Project**
3. Fill in:
   - **Name:** `studymarket`
   - **Database Password:** make it strong, save it!
   - **Region:** `ap-south-1` (Mumbai — closest for India)
4. Wait ~2 minutes for provisioning

---

## STEP 2 — Supabase: Get Your Database URL

1. In your Supabase project → **Settings** (gear icon) → **Database**
2. Scroll to **Connection String** → select **URI** tab
3. Copy the string — it looks like:
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.xxxxxxxxxxxx.supabase.co:5432/postgres
   ```
4. Replace `[YOUR-PASSWORD]` with the password you set in Step 1
5. **Save this** — this is your `DATABASE_URL`

---

## STEP 3 — Supabase: Get API Keys

1. **Settings** → **API**
2. Copy:
   - **Project URL** → this is your `SUPABASE_URL`
     ```
     https://xxxxxxxxxxxx.supabase.co
     ```
   - **service_role** key (under "Project API Keys") → this is your `SUPABASE_KEY`
     ```
     eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
     ```
   > ⚠️ Use the **service_role** key (not anon) for server-side file uploads.
   > Keep it secret — never put it in frontend code.

---

## STEP 4 — Supabase: Create Storage Bucket

You only need **one bucket** — `study-materials`. Preview images live inside it under the `previews/` path.

1. In Supabase sidebar → **Storage** → **New bucket**
2. Settings:
   - **Name:** `study-materials`
   - **Public bucket:** ❌ NO (keep it private — documents are served via signed URLs only)
3. Click **Create bucket**
4. Go to **Storage** → **Policies** → click on `study-materials` bucket
5. Click **New policy** → **For full customization** and add these three policies:

**Policy 1 — Allow authenticated uploads:**
```sql
CREATE POLICY "Authenticated users can upload"
ON storage.objects FOR INSERT
TO authenticated
WITH CHECK (bucket_id = 'study-materials');
```

**Policy 2 — Public can read preview images** (previews/ subfolder only):
```sql
CREATE POLICY "Public preview images readable"
ON storage.objects FOR SELECT
TO public
USING (bucket_id = 'study-materials' AND (storage.foldername(name))[1] = 'previews');
```

**Policy 3 — Authenticated users can read documents** (for signed URL generation):
```sql
CREATE POLICY "Authenticated can read docs"
ON storage.objects FOR SELECT
TO authenticated
USING (bucket_id = 'study-materials');
```

> **Important:** Do NOT enable "Allow public access" on the whole bucket — documents  
> must stay private. Only the `previews/` subfolder is publicly readable via Policy 2.

---

## STEP 5 — Razorpay: Get API Keys

1. Sign up at [razorpay.com](https://razorpay.com) → complete KYC
2. **Settings** → **API Keys** → **Generate Test Key**
3. Copy:
   - **Key ID** → `RAZORPAY_KEY_ID` (starts with `rzp_test_`)
   - **Key Secret** → `RAZORPAY_KEY_SECRET`
4. For **live payments**, generate a Live Key (requires completed KYC)

---

## STEP 6 — GitHub: Push Your Code

```bash
cd study_market

# Initialize git
git init
git add .
git commit -m "Initial StudyMarket commit"

# Create repo at github.com/new, then:
git remote add origin https://github.com/YOUR_USERNAME/studymarket.git
git branch -M main
git push -u origin main
```

---

## STEP 7 — Render: Deploy the App

1. Go to [render.com](https://render.com) → **New** → **Web Service**
2. **Connect GitHub** → select your `studymarket` repository
3. Configure:
   - **Name:** `studymarket`
   - **Region:** Singapore (closest free region for India)
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT`
   - **Plan:** Free
4. Click **Advanced** → **Add Environment Variable** — add ALL of these:

| Key | Value |
|---|---|
| `DATABASE_URL` | `postgresql://postgres:...` (from Step 2) |
| `SUPABASE_URL` | `https://xxxx.supabase.co` (from Step 3) |
| `SUPABASE_KEY` | `eyJ...` service_role key (from Step 3) |
| `STORAGE_BUCKET` | `study-materials` |
| `SECRET_KEY` | Click **Generate** button |
| `RAZORPAY_KEY_ID` | `rzp_test_...` (from Step 5) |
| `RAZORPAY_KEY_SECRET` | Your secret (from Step 5) |

5. Click **Create Web Service** → deploy starts (~3 minutes)

---

## STEP 8 — Create Admin Account

After your first deploy succeeds:

1. In Render → your service → **Shell** tab
2. Run:
   ```bash
   python seed_admin.py
   ```
3. This prints:
   ```
   ✅ Admin created → email: admin@studymarket.com  password: admin123
   ```
4. **Change the password immediately** after first login!

---

## STEP 9 — Test Everything

Visit your Render URL (e.g. `https://studymarket.onrender.com`) and test:

- [ ] Register as buyer → Register as seller
- [ ] Seller uploads a PDF → check Supabase Storage bucket
- [ ] Admin approves the product
- [ ] Buyer purchases with Razorpay test card:
  - Card: `4111 1111 1111 1111`
  - Expiry: any future date
  - CVV: any 3 digits
  - OTP: `1234` (test mode)
- [ ] Download works after purchase
- [ ] Seller wallet shows earnings
- [ ] Buyer requests bank withdrawal

---

## ✅ You're Live!

Your stack:
```
User → Render (Flask app)
           ↓
    Supabase PostgreSQL (database)
    Supabase Storage    (PDF/DOCX/PPT files)
    Razorpay            (real money payments)
```

---

## 🔁 Future Deployments

Every time you push to GitHub main branch, Render **auto-deploys**:
```bash
git add .
git commit -m "Update something"
git push
# Render picks up the change and redeploys in ~2 minutes
```

---

## 💸 Cost Breakdown (Free Tier Limits)

| Service | Free Limit |
|---|---|
| **Render** | 750 hrs/month (1 service = always on), sleeps after 15min inactivity |
| **Supabase DB** | 500 MB storage, 2 GB bandwidth |
| **Supabase Storage** | 1 GB file storage, 2 GB bandwidth |
| **Razorpay** | No monthly fee — charges only per transaction (2%) |

> **Render sleep issue:** Free tier apps sleep after 15 minutes of inactivity.
> First request after sleep takes ~30 seconds to wake up.
> Upgrade to Render Starter ($7/mo) to keep it always awake.

---

## 🛠️ Troubleshooting

### "Application Error" on Render
→ Check Render logs: your service → **Logs** tab
→ Most common: wrong `DATABASE_URL` or missing env var

### "Invalid signature" on Razorpay
→ Double-check `RAZORPAY_KEY_SECRET` matches your Razorpay dashboard exactly

### Files not uploading
→ Check `SUPABASE_URL`, `SUPABASE_KEY`, and `STORAGE_BUCKET` env vars
→ Check Supabase Storage → bucket exists and policies are set

### "Table does not exist" error
→ Run `python seed_admin.py` in Render Shell — it creates all tables

### Supabase connection timeout
→ Supabase free tier pauses DB after 1 week of inactivity
→ Go to Supabase → your project → click **Restore** button
