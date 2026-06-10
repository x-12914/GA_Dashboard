# GA Money Advisor

Reads a Google Analytics 4 property and turns the numbers into a **prioritized,
plain-English to-do list focused on making more money** — fix the mobile
checkout, cut wasted ad spend, double down on your best channel, etc.

- **Backend:** Python + FastAPI
- **Frontend:** plain HTML/CSS/JS dashboard
- **Brains:** Claude (when an API key is set) or a built-in rule-based analyzer
- **Data:** real GA4 via the Analytics Data API, or built-in sample data

Runs on sample data out of the box, so you can see it working before connecting
anything.

---

## 1. Run it (sample data)

```powershell
cd "c:\Users\BRAHIOM BASHIR\Downloads\dev"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # optional for sample mode
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000 → you'll see metrics + suggestions from sample data.

---

## 2. Make the suggestions smarter with Claude (optional)

1. Get an API key from https://console.anthropic.com
2. In `.env` set:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
3. Restart the server. The status bar will show `Analyzer: claude:...`.

Without a key it still works using the rule-based analyzer.

---

## 3. Connect your real GA4 property

You need (a) a GA4 property and (b) a Google Cloud service account that can read it.

### a. Create the GA4 property
- In Google Analytics, create a property for your site/app and install the tag.
- Note the **numeric Property ID**: Admin → Property Settings (e.g. `123456789`).
  This is *not* the `G-XXXXXXX` measurement id.

### b. Create a service account (Google Cloud)
1. Go to https://console.cloud.google.com → create/select a project.
2. **APIs & Services → Library →** enable **"Google Analytics Data API"**.
3. **APIs & Services → Credentials → Create credentials → Service account.**
4. Create it, then open it → **Keys → Add key → JSON**. A `.json` file downloads.
5. Copy the service account's email (looks like `name@project.iam.gserviceaccount.com`).

### c. Give the service account access to GA4
- In Google Analytics: **Admin → Property Access Management → +** → add that
  email with the **Viewer** role.

### d. Point the app at it
In `.env`:
```
USE_MOCK=false
GA4_PROPERTY_ID=123456789
GOOGLE_APPLICATION_CREDENTIALS=C:\full\path\to\service-account.json
```
Restart. The status bar should now show `Data: ga4`.

---

## How it's wired

```
frontend/  → calls /api/insights
backend/
  main.py        FastAPI: serves dashboard + API
  ga4_client.py  pulls metrics from GA4 (or mock_data)
  mock_data.py   realistic sample analytics
  analyzer.py    Claude or rule-based → ranked suggestions
  config.py      reads .env
```

API endpoints:
- `GET /api/status` – current mode (mock/ga4) and analyzer
- `GET /api/report?days=28` – raw metrics
- `GET /api/insights?days=28` – metrics + suggestions

---

## Turning this into a product (roadmap)

This MVP is single-property (yours). To sell it to others, the path is:

1. **Multi-user OAuth** – let users connect *their* GA4 with Google sign-in
   instead of a service-account file (replace the service-account auth in
   `ga4_client.py` with the OAuth flow).
2. **Accounts + billing** – add user accounts and Stripe subscriptions.
3. **Weekly email report** – the killer retention feature: email each user
   their top 3 actions every Monday. (Schedule `analyzer.analyze` per user.)
4. **Niche it** – e.g. "GA advisor for Shopify stores" converts far better
   than a generic tool.
# GA_Dashboard
