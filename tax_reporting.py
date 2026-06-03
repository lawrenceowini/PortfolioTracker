"""
tax_reporting.py — Phase 6: Tax Reporting
==========================================
Computes Kenyan tax obligations from portfolio transactions:

1. Capital Gains Tax (CGT)
   - Kenya introduced CGT on securities in 2023 at 15%
   - Applies to gains from sale of listed securities (NSE)
   - Loss from one security can offset gain from another in same year
   - Net losses cannot be carried forward for listed securities (NSE)
   - Holding period tracked (short-term vs long-term — informational only;
     Kenya does not currently differentiate rates by holding period)

2. Withholding Tax on Dividends (WHT)
   - Resident individuals: 5% WHT on dividends from listed companies
   - WHT is a final tax — no further income tax due on dividends
   - Tracked from the Dividends sheet

3. Securities Transaction Levy (STL) / Stamp Duty
   - 0.12% on the value of shares transferred (buy side)
   - Tracked from transaction fees where available

All figures are in KES. Tax year = Kenyan fiscal year (Jan–Dec).
"""

import datetime
import pandas as pd
import numpy as np
from typing import Optional

# ── Kenya Tax Rates (Finance Act 2023 onwards) ─────────────────────────────────
CGT_RATE_NSE          = 0.15    # 15% on net gains from listed securities
WHT_DIVIDEND_RESIDENT = 0.05    # 5% WHT on dividends (listed companies, residents)
STL_RATE              = 0.0012  # 0.12% Securities Transaction Levy (buy side)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean_tx(tx_df: pd.DataFrame) -> pd.DataFrame:
    if tx_df.empty:
        return tx_df
    df = tx_df.copy()
    df["Date"]          = pd.to_datetime(df.get("Date", pd.Series(dtype="object")), errors="coerce")
    df["Action"]        = df.get("Action", pd.Series(dtype="object")).astype(str).str.upper().str.strip()
    df["Quantity"]      = pd.to_numeric(df.get("Quantity",      0), errors="coerce").fillna(0)
    df["Price"]         = pd.to_numeric(df.get("Price",         0), errors="coerce").fillna(0)
    df["Fees"]          = pd.to_numeric(df.get("Fees",          0), errors="coerce").fillna(0)
    df["Realized Gain"] = pd.to_numeric(df.get("Realized Gain", 0), errors="coerce").fillna(0)
    return df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)


def _tax_year(date) -> int:
    """Kenya tax year is calendar year."""
    try:
        return pd.Timestamp(date).year
    except Exception:
        return datetime.datetime.now().year


# ── Capital Gains Tax ──────────────────────────────────────────────────────────

def compute_cgt_by_year(tx_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute annual Capital Gains Tax summary.

    For each tax year:
      - Total realised gains from SELL transactions
      - Total realised losses from SELL transactions
      - Net taxable gain (gains - losses, floored at 0)
      - CGT due at 15%
      - Effective rate on gross gains
    """
    df = _clean_tx(tx_df)
    if df.empty:
        return pd.DataFrame()

    sells = df[df["Action"] == "SELL"].copy()
    if sells.empty:
        return pd.DataFrame()

    sells["Tax Year"]    = sells["Date"].apply(_tax_year)
    sells["Is Gain"]     = sells["Realized Gain"] > 0
    sells["Is Loss"]     = sells["Realized Gain"] < 0

    annual = sells.groupby("Tax Year").apply(lambda g: pd.Series({
        "Total Gains (KES)"       : g.loc[g["Is Gain"], "Realized Gain"].sum(),
        "Total Losses (KES)"      : abs(g.loc[g["Is Loss"], "Realized Gain"].sum()),
        "Net Gain (KES)"          : max(0, g["Realized Gain"].sum()),
        "CGT Due (KES)"           : max(0, g["Realized Gain"].sum()) * CGT_RATE_NSE,
        "Transactions"            : len(g),
    }), include_groups=False).reset_index()

    annual["CGT Rate"]            = f"{CGT_RATE_NSE*100:.0f}%"
    annual["Net Loss Carried Fwd"]= "Not applicable (NSE)"

    return annual.sort_values("Tax Year", ascending=False).reset_index(drop=True)


def compute_cgt_by_asset(tx_df: pd.DataFrame, tax_year: Optional[int] = None) -> pd.DataFrame:
    """
    Per-asset CGT breakdown for a given tax year (defaults to current year).
    Shows each sell transaction with its gain/loss and CGT due.
    """
    df = _clean_tx(tx_df)
    if df.empty:
        return pd.DataFrame()

    year = tax_year or datetime.datetime.now().year
    sells = df[df["Action"] == "SELL"].copy()
    sells["Tax Year"] = sells["Date"].apply(_tax_year)
    sells = sells[sells["Tax Year"] == year]

    if sells.empty:
        return pd.DataFrame()

    rows = []
    for _, row in sells.iterrows():
        gain    = float(row["Realized Gain"])
        cgt_due = max(0, gain) * CGT_RATE_NSE
        rows.append({
            "Date"              : row["Date"].strftime("%Y-%m-%d"),
            "Asset"             : row.get("Asset", ""),
            "Shares Sold"       : row["Quantity"],
            "Sale Price (KES)"  : row["Price"],
            "Gross Proceeds"    : row["Quantity"] * row["Price"],
            "Realised Gain/Loss": gain,
            "CGT Due (KES)"     : round(cgt_due, 2),
            "Status"            : "Gain" if gain > 0 else ("Loss" if gain < 0 else "Break-even"),
        })

    return pd.DataFrame(rows)


def compute_holding_periods(tx_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each current open position, compute how long it has been held.
    Uses the OPENING or first BUY date per asset.
    Holding period informs tax planning (e.g. whether to hold or sell).
    """
    df = _clean_tx(tx_df)
    if df.empty:
        return pd.DataFrame()

    today = pd.Timestamp.now()
    rows  = []

    for asset, grp in df.groupby("Asset"):
        buys = grp[grp["Action"].isin(["BUY", "OPENING"])].sort_values("Date")
        if buys.empty:
            continue

        # Most recent position quantity
        last_row    = grp.sort_values("Date").iloc[-1]
        pos_qty     = pd.to_numeric(last_row.get("Position Quantity", 0), errors="coerce") or 0
        if pos_qty <= 0:
            continue   # position closed

        first_buy   = buys.iloc[0]["Date"]
        days_held   = (today - first_buy).days
        years_held  = days_held / 365.25

        rows.append({
            "Asset"          : asset,
            "First Purchase" : first_buy.strftime("%Y-%m-%d"),
            "Days Held"      : days_held,
            "Years Held"     : round(years_held, 2),
            "Shares Held"    : round(pos_qty, 2),
            "Holding Status" : "Long-term (>1yr)" if years_held >= 1 else "Short-term (<1yr)",
        })

    return pd.DataFrame(rows).sort_values("Days Held", ascending=False).reset_index(drop=True)


# ── Withholding Tax on Dividends ───────────────────────────────────────────────

def compute_wht_by_year(div_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute annual WHT on dividends.
    Expects the Dividends sheet from the output Excel.
    """
    if div_df.empty:
        return pd.DataFrame()

    df = div_df.copy()

    # Find the annual dividend column
    div_col = None
    for col in ["Annual Dividend", "Total Dividend", "Dividend per Share"]:
        if col in df.columns:
            div_col = col
            break

    if div_col is None:
        return pd.DataFrame()

    df[div_col] = pd.to_numeric(df[div_col], errors="coerce").fillna(0)

    # If there's a year column use it, else assign current year
    if "Year" in df.columns:
        df["Tax Year"] = pd.to_numeric(df["Year"], errors="coerce").fillna(
            datetime.datetime.now().year
        ).astype(int)
    else:
        df["Tax Year"] = datetime.datetime.now().year

    annual = df.groupby("Tax Year").agg(
        Gross_Dividends=(div_col, "sum"),
        Assets=("Asset", "count") if "Asset" in df.columns else (div_col, "count"),
    ).reset_index()

    annual.columns   = ["Tax Year", "Gross Dividends (KES)", "Assets"]
    annual["WHT Due (KES)"]   = (annual["Gross Dividends (KES)"] * WHT_DIVIDEND_RESIDENT).round(2)
    annual["WHT Rate"]        = f"{WHT_DIVIDEND_RESIDENT*100:.0f}%"
    annual["Net Received"]    = (annual["Gross Dividends (KES)"] - annual["WHT Due (KES)"]).round(2)
    annual["Tax Treatment"]   = "Final tax — no further income tax due"

    return annual.sort_values("Tax Year", ascending=False).reset_index(drop=True)


def compute_wht_by_asset(div_df: pd.DataFrame) -> pd.DataFrame:
    """Per-asset WHT breakdown."""
    if div_df.empty:
        return pd.DataFrame()

    df = div_df.copy()
    div_col = next((c for c in ["Annual Dividend", "Total Dividend"] if c in df.columns), None)
    if div_col is None:
        return pd.DataFrame()

    df[div_col] = pd.to_numeric(df[div_col], errors="coerce").fillna(0)
    asset_col   = "Asset" if "Asset" in df.columns else df.columns[0]

    rows = []
    for _, row in df.iterrows():
        gross    = float(row[div_col])
        wht      = round(gross * WHT_DIVIDEND_RESIDENT, 2)
        rows.append({
            "Asset"                 : row.get(asset_col, ""),
            "Gross Dividend (KES)"  : round(gross, 2),
            "WHT (5%) (KES)"        : wht,
            "Net Dividend (KES)"    : round(gross - wht, 2),
            "Dividend Yield %"      : row.get("Dividend Yield %", ""),
        })

    return pd.DataFrame(rows)


# ── Securities Transaction Levy ────────────────────────────────────────────────

def compute_stl(tx_df: pd.DataFrame, tax_year: Optional[int] = None) -> pd.DataFrame:
    """
    Estimate STL paid on buy transactions.
    STL = 0.12% of the transaction value on the buy side.
    """
    df = _clean_tx(tx_df)
    if df.empty:
        return pd.DataFrame()

    year  = tax_year or datetime.datetime.now().year
    buys  = df[df["Action"].isin(["BUY", "OPENING"])].copy()
    buys["Tax Year"]   = buys["Date"].apply(_tax_year)
    buys              = buys[buys["Tax Year"] == year]

    if buys.empty:
        return pd.DataFrame()

    buys["Trade Value"] = buys["Quantity"] * buys["Price"]
    buys["STL (KES)"]   = (buys["Trade Value"] * STL_RATE).round(2)

    result = buys.groupby("Tax Year").agg(
        Total_Trade_Value=("Trade Value", "sum"),
        Total_STL=("STL (KES)", "sum"),
        Transactions=("Trade Value", "count"),
    ).reset_index()
    result.columns = ["Tax Year", "Total Trade Value (KES)", "STL Paid (KES)", "Buy Transactions"]
    result["STL Rate"] = f"{STL_RATE*100:.2f}%"
    return result


# ── Annual tax summary ─────────────────────────────────────────────────────────

def build_annual_tax_summary(
    tx_df: pd.DataFrame,
    div_df: pd.DataFrame,
    tax_year: Optional[int] = None,
) -> pd.DataFrame:
    """
    Single consolidated tax summary for a given year.
    """
    year = tax_year or datetime.datetime.now().year

    cgt_annual  = compute_cgt_by_year(tx_df)
    wht_annual  = compute_wht_by_year(div_df)
    stl_annual  = compute_stl(tx_df, year)

    # Extract year rows
    cgt_row = cgt_annual[cgt_annual["Tax Year"] == year].iloc[0] if not cgt_annual.empty and year in cgt_annual["Tax Year"].values else None
    wht_row = wht_annual[wht_annual["Tax Year"] == year].iloc[0] if not wht_annual.empty and year in wht_annual["Tax Year"].values else None
    stl_row = stl_annual[stl_annual["Tax Year"] == year].iloc[0] if not stl_annual.empty else None

    cgt_due = float(cgt_row["CGT Due (KES)"])   if cgt_row is not None else 0.0
    wht_due = float(wht_row["WHT Due (KES)"])   if wht_row is not None else 0.0
    stl_due = float(stl_row["STL Paid (KES)"])  if stl_row is not None else 0.0
    total   = cgt_due + wht_due + stl_due

    rows = [
        ("Capital Gains Tax (CGT)",
         f"KES {cgt_due:,.2f}",
         f"{CGT_RATE_NSE*100:.0f}% of net realised gains on NSE securities",
         "Due on filing"),
        ("Withholding Tax on Dividends (WHT)",
         f"KES {wht_due:,.2f}",
         f"{WHT_DIVIDEND_RESIDENT*100:.0f}% of gross dividends — final tax",
         "Deducted at source"),
        ("Securities Transaction Levy (STL)",
         f"KES {stl_due:,.2f}",
         f"{STL_RATE*100:.2f}% of buy-side trade value",
         "Paid at transaction"),
        ("─────────────────", "─────────────", "─────────────────────────────────────────", "───────────────"),
        ("TOTAL TAX OBLIGATION",
         f"KES {total:,.2f}",
         f"Tax year {year}",
         ""),
    ]
    return pd.DataFrame(rows, columns=["Tax Head", "Amount", "Basis", "Payment Timing"])


# ── Tax calendar ──────────────────────────────────────────────────────────────

def build_tax_calendar(tax_year: int) -> pd.DataFrame:
    """
    Key Kenyan tax dates for securities investors.
    """
    rows = [
        (f"{tax_year}-12-31", "End of tax year",
         "All transactions after this date fall in the next tax year"),
        (f"{tax_year+1}-01-01", "New tax year begins",
         "Start of new CGT computation period"),
        (f"{tax_year+1}-04-30", "Individual tax return deadline",
         "File KRA iTax return including CGT from securities sales"),
        (f"{tax_year+1}-06-30", "CGT payment deadline",
         "Pay any outstanding CGT balance to KRA"),
        ("Ongoing", "WHT on dividends",
         "Deducted at source by the company before dividend is paid to you"),
        ("Ongoing", "STL on purchases",
         "Collected by broker at time of purchase — already paid"),
    ]
    return pd.DataFrame(rows, columns=["Date", "Event", "Notes"])


# ── Disclaimer ─────────────────────────────────────────────────────────────────
DISCLAIMER = (
    "⚠️ **Tax Disclaimer:** This tool provides estimates based on publicly available "
    "Kenyan tax law as of 2024–2025. Tax law changes frequently. These figures are for "
    "**informational and planning purposes only** and do not constitute tax advice. "
    "Consult a licensed Kenyan tax advisor or the Kenya Revenue Authority (KRA) for "
    "official guidance before filing. The CGT rules for NSE securities continue to evolve "
    "following the Finance Act 2023."
)
