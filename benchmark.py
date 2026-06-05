"""
benchmark.py — Phase 1: NSE Benchmark Comparison
=================================================
Fetches NSE 20 Share Index and NASI (All Share Index) live from
the web and compares them against the portfolio's own return history.

Public data sources tried in order:
  1. investing.com  (NSE 20, NASI historical)
  2. afx.kwayisi.org (NSE 20 fallback)
  3. nairobi-stock-exchange.com / marketdata

All scraping is isolated here so the rest of the system stays clean.
"""

import re
import json
import datetime
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional

import pandas as pd
import numpy as np

# ── Constants ──────────────────────────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20

NSE20_NAME  = "NSE 20 Share Index"
NASI_NAME   = "NSE All Share (NASI)"

# investing.com pair IDs (stable internal IDs, not tickers)
# NSE 20:  /indices/nse-20-share-index-historical-data
# NASI:    /indices/nairobi-all-share-historical-data
INVESTING_NSE20_URL = "https://www.investing.com/indices/nse-20-share-index-historical-data"
INVESTING_NASI_URL  = "https://www.investing.com/indices/nairobi-all-share-historical-data"

# AFX fallback for NSE 20
AFX_URL = "https://afx.kwayisi.org/nseke/"


# ── Low-level HTTP fetch ───────────────────────────────────────────────────────

def _fetch(url: str, extra_headers: Optional[dict] = None) -> str:
    headers = {
        "User-Agent"      : USER_AGENT,
        "Accept"          : "text/html,application/xhtml+xml,*/*;q=0.9",
        "Accept-Language" : "en-US,en;q=0.9",
        "Accept-Encoding" : "gzip, deflate",
        "Connection"      : "keep-alive",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
        enc = r.headers.get_content_charset("utf-8")
        try:
            import gzip
            return gzip.decompress(raw).decode(enc, errors="replace")
        except Exception:
            return raw.decode(enc, errors="replace")


# ── Current index level scrapers ───────────────────────────────────────────────

def _parse_current_from_afx(html: str) -> Optional[float]:
    """Extract current NSE 20 value from afx.kwayisi.org."""
    # The page shows: <span class="...">4,234.56</span> near "NSE 20"
    match = re.search(
        r'NSE\s*20.*?<[^>]+>\s*([\d,]+\.?\d*)\s*</[^>]+>',
        html, re.IGNORECASE | re.DOTALL
    )
    if match:
        return float(match.group(1).replace(",", ""))
    # Broader fallback: first large number on the page
    numbers = re.findall(r'\b(\d{1,3}(?:,\d{3})+(?:\.\d+)?)\b', html)
    for n in numbers:
        v = float(n.replace(",", ""))
        if 500 < v < 20000:   # plausible NSE 20 range
            return v
    return None


def _parse_current_from_investing(html: str) -> Optional[float]:
    """Extract current index value from investing.com page."""
    # Try JSON-LD or data attributes first
    match = re.search(
        r'"price"\s*:\s*"?([\d,]+\.?\d*)"?',
        html
    )
    if match:
        return float(match.group(1).replace(",", ""))
    # Fallback: look for the large price span
    match = re.search(
        r'class="[^"]*instrument-price-last[^"]*"[^>]*>\s*([\d,]+\.?\d*)',
        html
    )
    if match:
        return float(match.group(1).replace(",", ""))
    match = re.search(
        r'data-last-val="([\d.]+)"',
        html
    )
    if match:
        return float(match.group(1))
    return None


def fetch_current_nse20() -> dict:
    """Return current NSE 20 value + metadata."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Try AFX first (lighter page, more reliable scraping)
    try:
        html  = _fetch(AFX_URL)
        value = _parse_current_from_afx(html)
        if value:
            return {"index": NSE20_NAME, "value": value, "source": "afx.kwayisi.org", "updated": now}
    except Exception:
        pass
    # Try investing.com
    try:
        html  = _fetch(INVESTING_NSE20_URL)
        value = _parse_current_from_investing(html)
        if value:
            return {"index": NSE20_NAME, "value": value, "source": "investing.com", "updated": now}
    except Exception:
        pass
    return {"index": NSE20_NAME, "value": None, "source": "unavailable", "updated": now}


def fetch_current_nasi() -> dict:
    """Return current NASI value + metadata."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        html  = _fetch(INVESTING_NASI_URL)
        value = _parse_current_from_investing(html)
        if value:
            return {"index": NASI_NAME, "value": value, "source": "investing.com", "updated": now}
    except Exception:
        pass
    # Try mansamarkets as fallback (they sometimes list NASI)
    try:
        html = _fetch("https://www.mansamarkets.com/kenya")
        match = re.search(r'NASI.*?([\d,]+\.?\d*)', html, re.IGNORECASE | re.DOTALL)
        if match:
            value = float(match.group(1).replace(",", ""))
            if 50 < value < 500:   # plausible NASI range (usually 100–250)
                return {"index": NASI_NAME, "value": value, "source": "mansamarkets.com", "updated": now}
    except Exception:
        pass
    return {"index": NASI_NAME, "value": None, "source": "unavailable", "updated": now}


# ── Historical index data ──────────────────────────────────────────────────────

def _parse_historical_from_investing(html: str) -> pd.DataFrame:
    """
    Parse historical price table from investing.com.
    They embed data in a <table id="curr_table"> or similar, or in JSON.
    """
    # Try JSON inside script tags first
    json_match = re.search(
        r'historical_data_json\s*=\s*(\[.*?\])\s*;',
        html, re.DOTALL
    )
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            rows = []
            for item in data:
                try:
                    date  = pd.to_datetime(item.get("rowDateRaw") or item.get("date"))
                    close = float(str(item.get("last_close") or item.get("price") or 0).replace(",", ""))
                    if close > 0:
                        rows.append({"Date": date, "Close": close})
                except Exception:
                    continue
            if rows:
                return pd.DataFrame(rows).sort_values("Date")
        except Exception:
            pass

    # Fallback: parse HTML table
    rows = []
    table_match = re.search(
        r'<table[^>]*>.*?</table>',
        html, re.DOTALL | re.IGNORECASE
    )
    if table_match:
        table_html = table_match.group(0)
        tr_blocks  = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)
        for tr in tr_blocks:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL)
            cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if len(cells) >= 2:
                try:
                    date  = pd.to_datetime(cells[0])
                    price = float(cells[1].replace(",", ""))
                    if price > 0:
                        rows.append({"Date": date, "Close": price})
                except Exception:
                    continue
    return pd.DataFrame(rows).sort_values("Date") if rows else pd.DataFrame()


def fetch_historical_nse20(months: int = 12) -> pd.DataFrame:
    """Fetch NSE 20 historical monthly closes for the last N months."""
    try:
        html = _fetch(INVESTING_NSE20_URL)
        df   = _parse_historical_from_investing(html)
        if not df.empty:
            cutoff = pd.Timestamp.now() - pd.DateOffset(months=months)
            return df[df["Date"] >= cutoff].reset_index(drop=True)
    except Exception:
        pass
    return pd.DataFrame(columns=["Date", "Close"])


def fetch_historical_nasi(months: int = 12) -> pd.DataFrame:
    """Fetch NASI historical monthly closes for the last N months."""
    try:
        html = _fetch(INVESTING_NASI_URL)
        df   = _parse_historical_from_investing(html)
        if not df.empty:
            cutoff = pd.Timestamp.now() - pd.DateOffset(months=months)
            return df[df["Date"] >= cutoff].reset_index(drop=True)
    except Exception:
        pass
    return pd.DataFrame(columns=["Date", "Close"])


# ── Benchmark comparison engine ────────────────────────────────────────────────

def compute_index_returns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Given a DataFrame with Date + Close columns, compute period returns.
    Returns a DataFrame with columns: Date, Close, Return_pct (cumulative from first point).
    """
    if df.empty or len(df) < 2:
        return df
    df = df.copy().sort_values("Date").reset_index(drop=True)
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df = df.dropna(subset=["Close"])
    first = df["Close"].iloc[0]
    if first == 0:
        df["Return_pct"] = 0.0
    else:
        df["Return_pct"] = ((df["Close"] - first) / first) * 100
    return df


def compute_portfolio_returns(history_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert portfolio value history into a cumulative return series
    matching the same shape as index return DataFrames.
    """
    if history_df.empty:
        return pd.DataFrame(columns=["Date", "Close", "Return_pct"])
    df = history_df.copy()
    df["Date"]  = pd.to_datetime(df["Date"], errors="coerce")
    df["Close"] = pd.to_numeric(df["Portfolio Value"], errors="coerce")
    df = df.dropna(subset=["Date", "Close"]).sort_values("Date").reset_index(drop=True)
    first = df["Close"].iloc[0]
    if first == 0:
        df["Return_pct"] = 0.0
    else:
        df["Return_pct"] = ((df["Close"] - first) / first) * 100
    return df[["Date", "Close", "Return_pct"]]


def build_comparison_table(
    portfolio_ret: pd.DataFrame,
    nse20_ret: pd.DataFrame,
    nasi_ret: pd.DataFrame,
) -> pd.DataFrame:
    """
    Produce a summary table of total return, best month, worst month,
    and current value for portfolio vs both indices.
    """
    def summarise(df: pd.DataFrame, label: str) -> dict:
        if df.empty or "Return_pct" not in df.columns:
            return {"Series": label, "Total Return %": "N/A", "Best Period %": "N/A",
                    "Worst Period %": "N/A", "Data Points": 0}
        ret = df["Return_pct"]
        # Period-over-period returns
        pct_changes = df["Close"].pct_change().dropna() * 100
        return {
            "Series"         : label,
            "Total Return %"  : f"{ret.iloc[-1]:.2f}%" if len(ret) else "N/A",
            "Best Period %"   : f"{pct_changes.max():.2f}%" if len(pct_changes) else "N/A",
            "Worst Period %"  : f"{pct_changes.min():.2f}%" if len(pct_changes) else "N/A",
            "Data Points"     : len(df),
        }

    rows = [
        summarise(portfolio_ret, "Your Portfolio"),
        summarise(nse20_ret,     f"{NSE20_NAME}"),
        summarise(nasi_ret,      f"{NASI_NAME}"),
    ]
    return pd.DataFrame(rows)


def resample_to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample a Date+Close series to month-end closes for chart alignment."""
    if df.empty:
        return df
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    monthly = df[numeric_cols].resample("ME").last().dropna()
    return monthly.reset_index()


# ── Alpha / outperformance metric ─────────────────────────────────────────────

def compute_alpha(portfolio_ret: pd.DataFrame, benchmark_ret: pd.DataFrame) -> Optional[float]:
    """
    Simple alpha: portfolio total return minus benchmark total return (in %).
    Positive = outperformed, negative = underperformed.
    """
    if portfolio_ret.empty or benchmark_ret.empty:
        return None
    p = portfolio_ret["Return_pct"].iloc[-1] if len(portfolio_ret) else None
    b = benchmark_ret["Return_pct"].iloc[-1] if len(benchmark_ret) else None
    if p is None or b is None:
        return None
    return round(p - b, 2)
