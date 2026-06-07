# PRO_LAW Portfolio Tracker

A Python and Streamlit portfolio management app for Kenyan/NSE portfolios. It converts client Excel workbooks into styled dashboard workbooks and PDF reports, then presents the generated data in an authenticated Streamlit dashboard.

## What It Does

- Processes client portfolio workbooks from `clients/`.
- Fetches mapped NSE prices for supported holdings.
- Builds Excel dashboard outputs in `reports/`.
- Generates branded PDF portfolio reports.
- Tracks allocations, concentration risk, rebalancing suggestions, dividends, performance history, transactions, taxes, alerts, FX exposure, and audit events.
- Supports role-based access with local users or Supabase-backed authentication.

## Main Entry Points

- `streamlit_dashboard.py` - main web dashboard.
- `update_portfolio.py` - batch processor that reads `clients/*.xlsx` and writes `reports/*`.
- `supabase_setup.sql` - optional Supabase schema for hosted authentication/profile data.

## Project Layout

```text
PortfolioTracker/
  streamlit_dashboard.py        # Streamlit dashboard
  update_portfolio.py           # Excel/PDF generation pipeline
  auth.py                       # Local/Supabase authentication
  permissions.py                # Role and page permissions
  pdf_report.py                 # Professional PDF reports
  alerts.py                     # Portfolio alert checks
  multi_currency.py             # FX rates and KES conversion
  target_allocation.py          # Target allocation drift/trades
  clients/                      # Local input workbooks, ignored by git
  reports/                      # Generated dashboard workbooks/PDFs, ignored by git
  Template/                     # Starter workbook template
  Images/, Logo.png, Icon.png   # Branding assets
```

## Setup

Use Python 3.10 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Running The Dashboard

```bash
streamlit run streamlit_dashboard.py
```

On first run, if Supabase is not configured and no local admin exists, the login page lets you create an administrator account.

## Generating Portfolio Outputs

Place client workbooks in `clients/`, then run:

```bash
python update_portfolio.py
```

The processor creates:

- `reports/<Portfolio>_Dashboard_Output.xlsx`
- `reports/<Portfolio>_Report.pdf`
- `backup_<Portfolio>_<timestamp>.xlsx`

The dashboard can then load generated workbooks automatically from `reports/`.

## Workbook Expectations

Input workbooks should include a `Holdings` sheet with at least:

- `Asset`
- `Sector`
- `Shares`
- `Buy Price`
- `Current Price`

Optional dividend data can be provided in a `Dividend Tracking` sheet.

Generated dashboard workbooks include sheets such as:

- `Dashboard1`
- `Holdings`
- `Dividends`
- `Performance History`
- `NSE_Prices`
- `Transactions`
- `Portfolio_State`

## Configuration

Create a local `.env` file for secrets and service settings. This file is ignored by git.

```dotenv
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USERNAME=you@example.com
EMAIL_SMTP_PASSWORD=your-app-password
EMAIL_FROM=you@example.com
EMAIL_USE_TLS=True

SUPABASE_URL=
SUPABASE_ANON_KEY=
```

Supabase is optional. If `SUPABASE_URL` and `SUPABASE_ANON_KEY` are missing, the app uses the local user store.

## Git Hygiene

The repository ignores local secrets, generated reports, backups, caches, logs, and client workbooks. If these files were already tracked before `.gitignore` was added, remove them from git tracking without deleting local copies:

```bash
git rm --cached .env
git rm --cached -r __pycache__ reports
git rm --cached backup_*.xlsx Portfolio_Dashboard_Output.xlsx
git rm --cached clients/*.xlsx
git rm --cached alerts_log.json audit_log.json fx_rates_cache.json
```

Run those commands only when you are ready to clean the repository index.
