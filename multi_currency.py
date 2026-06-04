"""
multi_currency.py — Phase 8: Multi-Currency Support
=====================================================
Handles portfolios containing assets denominated in multiple currencies.
All values are converted to KES as the base currency for reporting.

Supported currencies (extensible via custom input):
  KES — Kenyan Shilling (base, no conversion needed)
  USD — US Dollar
  GBP — British Pound Sterling
  EUR — Euro
  ZAR — South African Rand

FX Rate sources (tried in order):
  1. exchangerate-api.com (free tier, no key needed)
  2. open.er-api.com (free, no key needed)
  3. frankfurter.app (free ECB rates)
  4. Fallback: user-supplied manual rates stored in fx_config.json

Storage:
  fx_config.json — manual override rates + asset currency assignments
  fx_rates_cache.json — cached live rates with timestamp (1hr TTL)
"""

import json
import os
import datetime
import urllib.request
import urllib.error
from typing import Optional

import pandas as pd
import numpy as np

FX_CONFIG_FILE = "fx_config.json"
FX_CACHE_FILE  = "fx_rates_cache.json"
CACHE_TTL_MINS = 60   # refresh rates every 60 minutes

BASE_CURRENCY  = "KES"

SUPPORTED_CURRENCIES = {
    "KES": "Kenyan Shilling",
    "USD": "US Dollar",
    "GBP": "British Pound Sterling",
    "EUR": "Euro",
    "ZAR": "South African Rand",
}

USER_AGENT = "Mozilla/5.0 PRO_LAW-Portfolio-Tracker/1.0"
TIMEOUT    = 15


# ── Config persistence ─────────────────────────────────────────────────────────

def load_fx_config() -> dict:
    if not os.path.exists(FX_CONFIG_FILE):
        return {
            "manual_rates"      : {},   # {"USD": 130.5, "GBP": 168.2, ...}
            "asset_currencies"  : {},   # {"Apple Inc": "USD", "Vodafone": "GBP"}
            "use_live_rates"    : True,
            "custom_currencies" : {},   # {"SGD": "Singapore Dollar", ...}
        }
    try:
        with open(FX_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return load_fx_config()


def save_fx_config(config: dict) -> None:
    with open(FX_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, default=str)


def load_fx_cache() -> dict:
    if not os.path.exists(FX_CACHE_FILE):
        return {}
    try:
        with open(FX_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_fx_cache(cache: dict) -> None:
    with open(FX_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, default=str)


# ── Live FX rate fetching ──────────────────────────────────────────────────────

def _fetch_url(url: str) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def _fetch_from_exchangerate_api(currencies: list) -> dict:
    """
    exchangerate-api.com free tier — base USD, convert to KES pairs.
    Returns {currency: rate_vs_KES} dict.
    """
    url  = "https://open.er-api.com/v6/latest/KES"
    text = _fetch_url(url)
    if not text:
        return {}
    try:
        data  = json.loads(text)
        rates = data.get("rates", {})
        result = {}
        # rates are X per 1 KES, we want KES per 1 X
        for ccy in currencies:
            if ccy == "KES":
                result["KES"] = 1.0
            elif ccy in rates and rates[ccy] != 0:
                result[ccy] = round(1.0 / rates[ccy], 4)
        return result
    except Exception:
        return {}


def _fetch_from_frankfurter(currencies: list) -> dict:
    """
    frankfurter.app — ECB rates. Base EUR, then cross to KES.
    """
    non_kes = [c for c in currencies if c not in ("KES", "EUR")]
    symbols = ",".join(["KES"] + non_kes)
    url     = f"https://api.frankfurter.app/latest?from=EUR&to={symbols}"
    text    = _fetch_url(url)
    if not text:
        return {}
    try:
        data  = json.loads(text)
        rates = data.get("rates", {})
        kes_per_eur = float(rates.get("KES", 0))
        if kes_per_eur == 0:
            return {}
        result = {"KES": 1.0, "EUR": round(kes_per_eur, 4)}
        for ccy in non_kes:
            if ccy in rates and rates[ccy] != 0:
                # cross rate: KES per CCY = (KES/EUR) / (CCY/EUR)
                result[ccy] = round(kes_per_eur / float(rates[ccy]), 4)
        return result
    except Exception:
        return {}


def fetch_live_rates(currencies: list, force_refresh: bool = False) -> dict:
    """
    Fetch live FX rates for all requested currencies vs KES.
    Uses cache (60min TTL) to avoid excessive API calls.
    Returns {currency_code: kes_equivalent} e.g. {"USD": 130.5, "GBP": 168.2}
    """
    cache = load_fx_cache()
    now   = datetime.datetime.now()

    # Check cache validity
    if not force_refresh and cache:
        cached_at = cache.get("fetched_at", "")
        try:
            age_mins = (now - datetime.datetime.fromisoformat(cached_at)).total_seconds() / 60
            if age_mins < CACHE_TTL_MINS:
                cached_rates = cache.get("rates", {})
                if all(c in cached_rates for c in currencies if c != "KES"):
                    return cached_rates
        except Exception:
            pass

    # Fetch fresh rates
    result = {"KES": 1.0}
    non_kes = [c for c in currencies if c != "KES"]

    if non_kes:
        # Try source 1
        rates = _fetch_from_exchangerate_api(non_kes)
        if rates:
            result.update(rates)
        else:
            # Try source 2
            rates = _fetch_from_frankfurter(non_kes)
            if rates:
                result.update(rates)

    # Cache results
    cache = {
        "fetched_at": now.isoformat(),
        "rates"     : result,
        "source"    : "open.er-api.com / frankfurter.app",
    }
    save_fx_cache(cache)
    return result


def get_effective_rates(fx_config: dict, currencies: list) -> tuple:
    """
    Return effective rates + source description.
    If use_live_rates is True, fetch live (with cache).
    Manual overrides always take precedence over live rates.
    Returns (rates_dict, source_str, last_updated_str)
    """
    use_live     = fx_config.get("use_live_rates", True)
    manual_rates = fx_config.get("manual_rates", {})

    if use_live:
        live_rates = fetch_live_rates(currencies)
        # Manual overrides take precedence
        rates = {**live_rates, **{k: float(v) for k, v in manual_rates.items() if v}}
        source = "Live (open.er-api.com)"
    else:
        rates  = {"KES": 1.0, **{k: float(v) for k, v in manual_rates.items() if v}}
        source = "Manual rates"

    # Load cache for timestamp
    cache      = load_fx_cache()
    updated_at = cache.get("fetched_at", "unknown")
    try:
        updated_at = datetime.datetime.fromisoformat(updated_at).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass

    rates["KES"] = 1.0
    return rates, source, updated_at


# ── Currency conversion helpers ────────────────────────────────────────────────

def convert_to_kes(amount: float, currency: str, rates: dict) -> float:
    """Convert an amount in given currency to KES using provided rates."""
    if currency == "KES":
        return amount
    rate = rates.get(currency)
    if not rate or rate == 0:
        return amount   # fallback: treat as KES if rate unknown
    return amount * rate


def convert_holdings_to_kes(
    holdings_df: pd.DataFrame,
    asset_currencies: dict,
    rates: dict,
) -> pd.DataFrame:
    """
    Return a new holdings DataFrame with all monetary columns
    converted to KES based on each asset's assigned currency.

    asset_currencies: {"Apple Inc": "USD", "Vodafone": "GBP", ...}
    Columns converted: Buy Price, Current Price, Market Value, Gain/Loss
    New columns added: Currency, FX Rate, Market Value (KES)
    """
    if holdings_df.empty:
        return holdings_df

    df = holdings_df.copy().reset_index(drop=True)

    # ── Normalise column names: strip whitespace, fix common variants ──────────
    col_map = {}
    for col in df.columns:
        stripped = str(col).strip()
        col_map[col] = stripped
    df.columns = [col_map[c] for c in df.columns]

    # Case-insensitive column finder
    def find_col(df, target):
        for c in df.columns:
            if c.lower().strip() == target.lower().strip():
                return c
        return None

    asset_col = find_col(df, "Asset")
    mv_col    = find_col(df, "Market Value")

    # ── Currency assignment ────────────────────────────────────────────────────
    if asset_col:
        df["Currency"] = [
            asset_currencies.get(str(a), "KES") if pd.notna(a) else "KES"
            for a in df[asset_col]
        ]
    else:
        df["Currency"] = ["KES"] * len(df)

    df["FX Rate"] = [float(rates.get(c, 1.0)) for c in df["Currency"]]

    # ── Convert money columns ──────────────────────────────────────────────────
    # Find actual column names case-insensitively
    target_money = ["Buy Price", "Current Price", "Market Value", "Gain/Loss"]
    for target in target_money:
        actual = find_col(df, target)
        if actual is None:
            continue
        # Extract as plain list to avoid formula/mixed-type issues
        raw = list(df[actual])
        numeric = pd.to_numeric(pd.Series(raw, dtype=object), errors="coerce").fillna(0).values
        df[f"{actual} (native)"] = numeric
        df[actual]               = numeric * df["FX Rate"].values

    # ── Market Value (KES) canonical column ───────────────────────────────────
    mv_actual = find_col(df, "Market Value")
    if mv_actual:
        df["Market Value (KES)"] = df[mv_actual]
    else:
        df["Market Value (KES)"] = 0.0

    return df


def build_currency_exposure(
    holdings_df: pd.DataFrame,
    asset_currencies: dict,
    rates: dict,
) -> pd.DataFrame:
    """
    Summarise portfolio exposure by currency.
    Shows total KES value, % of portfolio, and FX rate for each currency.
    """
    if holdings_df.empty:
        return pd.DataFrame()

    df = holdings_df.copy().reset_index(drop=True)

    # Normalise column names
    df.columns = [str(c).strip() for c in df.columns]

    def find_col(df, target):
        for c in df.columns:
            if c.lower().strip() == target.lower().strip():
                return c
        return None

    asset_col = find_col(df, "Asset")
    mv_col    = find_col(df, "Market Value")

    # Safely extract Market Value
    if mv_col:
        raw_mv = list(df[mv_col])
    else:
        raw_mv = [0] * len(df)
    df["_mv"] = pd.to_numeric(pd.Series(raw_mv, dtype=object), errors="coerce").fillna(0).values

    # Currency per asset
    if asset_col:
        df["_ccy"] = [
            asset_currencies.get(str(a), "KES") if pd.notna(a) else "KES"
            for a in df[asset_col]
        ]
    else:
        df["_ccy"] = ["KES"] * len(df)

    df["_rate"]   = [float(rates.get(c, 1.0)) for c in df["_ccy"]]
    df["_mv_kes"] = df["_mv"] * df["_rate"]

    total = float(df["_mv_kes"].sum())
    if total == 0:
        return pd.DataFrame()

    agg_col = asset_col if asset_col else "_mv"
    grouped = df.groupby("_ccy").agg(
        Assets    =(agg_col,   "count"),
        Total_KES =("_mv_kes", "sum"),
    ).reset_index()
    grouped.columns = ["Currency Code", "Assets", "Total Value (KES)"]

    grouped["% of Portfolio"]   = (grouped["Total Value (KES)"] / total * 100).round(2)
    grouped["FX Rate (vs KES)"] = [round(float(rates.get(c, 1.0)), 4) for c in grouped["Currency Code"]]
    grouped["Currency Name"]    = [
        SUPPORTED_CURRENCIES.get(c, "Custom") for c in grouped["Currency Code"]
    ]
    grouped["Total Value (KES)"] = grouped["Total Value (KES)"].round(2)

    return grouped.sort_values("% of Portfolio", ascending=False).reset_index(drop=True)


def build_fx_risk_summary(exposure_df: pd.DataFrame) -> pd.DataFrame:
    """
    FX risk summary: non-KES exposure creates currency risk.
    A 10% move in USD/KES affects your portfolio proportionally.
    """
    if exposure_df.empty:
        return pd.DataFrame()

    if "Currency Code" not in exposure_df.columns:
        return pd.DataFrame()
    non_kes = exposure_df[exposure_df["Currency Code"] != "KES"].copy()
    if non_kes.empty:
        return pd.DataFrame([{
            "Metric": "FX Risk",
            "Value" : "None — all holdings in KES",
        }])

    rows = []
    total_non_kes_pct = non_kes["% of Portfolio"].sum()
    rows.append({"Metric": "Non-KES Exposure", "Value": f"{total_non_kes_pct:.1f}% of portfolio"})

    for _, row in non_kes.iterrows():
        ccy     = row["Currency Code"]
        pct     = row["% of Portfolio"]
        impact_10 = pct * 0.10  # 10% FX move impact on total portfolio
        rows.append({
            "Metric": f"{ccy} exposure",
            "Value" : f"{pct:.1f}% of portfolio — a 10% {ccy}/KES move = {impact_10:.1f}pp portfolio impact",
        })

    return pd.DataFrame(rows)


# ── Historical FX for context ──────────────────────────────────────────────────

def fetch_historical_fx(currency: str, months: int = 6) -> pd.DataFrame:
    """
    Fetch monthly historical FX rate for currency vs KES.
    Uses frankfurter.app historical endpoint.
    """
    if currency == "KES":
        return pd.DataFrame()

    end_date   = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=months * 31)
    url = (
        f"https://api.frankfurter.app/{start_date}..{end_date}"
        f"?from={currency}&to=KES"
    )
    text = _fetch_url(url)
    if not text:
        return pd.DataFrame()
    try:
        data  = json.loads(text)
        rates = data.get("rates", {})
        rows  = []
        for date_str, rate_dict in rates.items():
            kes_rate = rate_dict.get("KES")
            if kes_rate:
                rows.append({"Date": pd.Timestamp(date_str), "Rate": round(float(kes_rate), 4)})
        return pd.DataFrame(rows).sort_values("Date").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()
