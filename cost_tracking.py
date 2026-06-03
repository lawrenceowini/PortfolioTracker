"""
cost_tracking.py — Phase 3: Portfolio Cost Tracking
=====================================================
Computes true portfolio profitability by tracking:
  - Total capital invested (cumulative cash put in)
  - Total capital withdrawn (proceeds from sells)
  - Net capital deployed
  - True profit/loss = current market value - net capital deployed
  - Return on invested capital (ROIC)
  - Cash flow timeline (when money went in/out)
  - Cost basis per asset vs current market value
  - Unrealised vs realised gain breakdown

All functions accept the Transactions DataFrame produced by update_portfolio.py
and the Holdings DataFrame from the output Excel file.
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple


# ── Constants ──────────────────────────────────────────────────────────────────
BUY_ACTIONS      = {"BUY", "OPENING"}
SELL_ACTIONS     = {"SELL"}
INCOME_ACTIONS   = {"DIVIDEND", "INTEREST", "BONUS"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean_tx(tx_df: pd.DataFrame) -> pd.DataFrame:
    """Normalise and clean a transactions DataFrame."""
    if tx_df.empty:
        return tx_df
    df = tx_df.copy()
    df["Date"]     = pd.to_datetime(df.get("Date", pd.Series(dtype="object")), errors="coerce")
    df["Action"]   = df.get("Action", pd.Series(dtype="object")).astype(str).str.upper().str.strip()
    df["Quantity"] = pd.to_numeric(df.get("Quantity", 0), errors="coerce").fillna(0)
    df["Price"]    = pd.to_numeric(df.get("Price",    0), errors="coerce").fillna(0)
    df["Fees"]     = pd.to_numeric(df.get("Fees",     0), errors="coerce").fillna(0)
    df["Gross"]    = df["Quantity"] * df["Price"]
    return df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)


# ── Core calculations ──────────────────────────────────────────────────────────

def total_capital_invested(tx_df: pd.DataFrame) -> float:
    """
    Sum of all cash outflows: BUY/OPENING transactions (quantity × price + fees).
    Excludes OPENING transactions from the total if they represent
    pre-existing positions (no actual new cash deployed).
    """
    df = _clean_tx(tx_df)
    if df.empty:
        return 0.0
    buys = df[df["Action"].isin(BUY_ACTIONS)]
    return float((buys["Gross"] + buys["Fees"]).sum())


def total_capital_withdrawn(tx_df: pd.DataFrame) -> float:
    """
    Sum of all cash inflows: SELL transactions (quantity × price - fees).
    """
    df = _clean_tx(tx_df)
    if df.empty:
        return 0.0
    sells = df[df["Action"].isin(SELL_ACTIONS)]
    return float((sells["Gross"] - sells["Fees"]).sum())


def net_capital_deployed(tx_df: pd.DataFrame) -> float:
    """
    Net cash still working in the portfolio:
    capital invested - capital withdrawn.
    """
    return total_capital_invested(tx_df) - total_capital_withdrawn(tx_df)


def true_profit_loss(tx_df: pd.DataFrame, current_market_value: float) -> float:
    """
    True P&L = current market value - net capital deployed.
    Positive = profit, negative = loss.
    """
    return current_market_value - net_capital_deployed(tx_df)


def return_on_invested_capital(tx_df: pd.DataFrame, current_market_value: float) -> Optional[float]:
    """
    ROIC % = true P&L / net capital deployed × 100.
    """
    net = net_capital_deployed(tx_df)
    if net == 0:
        return None
    return round(true_profit_loss(tx_df, current_market_value) / net * 100, 2)


def realised_gain_total(tx_df: pd.DataFrame) -> float:
    """Total realised gain from all SELL transactions (from Realized Gain column)."""
    df = _clean_tx(tx_df)
    if df.empty or "Realized Gain" not in df.columns:
        return 0.0
    return float(pd.to_numeric(df["Realized Gain"], errors="coerce").fillna(0).sum())


def unrealised_gain_total(tx_df: pd.DataFrame) -> float:
    """
    Latest unrealised gain per asset (last transaction row per asset).
    """
    df = _clean_tx(tx_df)
    if df.empty or "Unrealized Gain" not in df.columns:
        return 0.0
    # Take the most recent unrealised gain per asset
    latest = df.sort_values("Date").groupby("Asset").last().reset_index()
    return float(pd.to_numeric(latest["Unrealized Gain"], errors="coerce").fillna(0).sum())


# ── Cash flow timeline ─────────────────────────────────────────────────────────

def build_cashflow_timeline(tx_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a monthly cash flow timeline showing:
    - Capital In (buys)
    - Capital Out (sells)
    - Net Cash Flow
    - Cumulative Capital Deployed

    Returns a DataFrame indexed by month with these columns.
    """
    df = _clean_tx(tx_df)
    if df.empty:
        return pd.DataFrame()

    # Cash in = buys (negative cash flow from investor perspective)
    df_buys = df[df["Action"].isin(BUY_ACTIONS)].copy()
    df_buys["Cash_In"]  = df_buys["Gross"] + df_buys["Fees"]
    df_buys["Cash_Out"] = 0.0

    # Cash out = sells (positive cash flow — money returned)
    df_sells = df[df["Action"].isin(SELL_ACTIONS)].copy()
    df_sells["Cash_In"]  = 0.0
    df_sells["Cash_Out"] = df_sells["Gross"] - df_sells["Fees"]

    combined = pd.concat([df_buys[["Date", "Cash_In", "Cash_Out"]],
                          df_sells[["Date", "Cash_In", "Cash_Out"]]], ignore_index=True)
    combined["Date"] = pd.to_datetime(combined["Date"])
    combined = combined.set_index("Date").sort_index()

    monthly = combined.resample("ME").sum()
    monthly["Net_Cash_Flow"]          = monthly["Cash_Out"] - monthly["Cash_In"]
    monthly["Cumulative_Capital_In"]  = monthly["Cash_In"].cumsum()
    monthly["Cumulative_Capital_Out"] = monthly["Cash_Out"].cumsum()
    monthly["Net_Capital_Deployed"]   = (monthly["Cash_In"] - monthly["Cash_Out"]).cumsum()

    monthly = monthly.reset_index()
    monthly.columns = [
        "Month", "Capital_In", "Capital_Out",
        "Net_Cash_Flow", "Cumulative_Capital_In",
        "Cumulative_Capital_Out", "Net_Capital_Deployed",
    ]
    return monthly


# ── Per-asset cost basis breakdown ────────────────────────────────────────────

def build_cost_basis_table(tx_df: pd.DataFrame, holdings_df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-asset table showing:
    - Asset, Sector
    - Shares held
    - Average purchase price (cost basis / shares)
    - Current price
    - Cost basis (total capital in that position)
    - Current market value
    - Unrealised P&L and %
    - Realised P&L (cumulative from sells)
    - Total P&L (realised + unrealised)
    """
    df = _clean_tx(tx_df)
    if df.empty:
        return pd.DataFrame()

    # Get latest state per asset from transactions
    latest = df.sort_values("Date").groupby("Asset").last().reset_index()

    rows = []
    for _, row in latest.iterrows():
        asset = row["Asset"]

        # Pull sector and current price from holdings
        hold_row = pd.Series(dtype=object)
        if not holdings_df.empty and "Asset" in holdings_df.columns:
            match = holdings_df[holdings_df["Asset"] == asset]
            if not match.empty:
                hold_row = match.iloc[0]

        sector        = hold_row.get("Sector", "Unknown") if not hold_row.empty else "Unknown"
        current_price = pd.to_numeric(hold_row.get("Current Price", 0), errors="coerce") if not hold_row.empty else 0
        shares_held   = pd.to_numeric(row.get("Position Quantity", 0), errors="coerce") or 0
        cost_basis    = pd.to_numeric(row.get("Cost Basis", 0), errors="coerce") or 0
        avg_price     = pd.to_numeric(row.get("Average Purchase Price", 0), errors="coerce") or 0
        unreal_gain   = pd.to_numeric(row.get("Unrealized Gain", 0), errors="coerce") or 0

        # Realised gain: sum across all sell rows for this asset
        asset_sells  = df[(df["Asset"] == asset) & (df["Action"].isin(SELL_ACTIONS))]
        real_gain    = pd.to_numeric(asset_sells.get("Realized Gain", pd.Series(dtype=float)), errors="coerce").fillna(0).sum() if not asset_sells.empty else 0.0

        market_value = shares_held * current_price if current_price > 0 else (cost_basis + unreal_gain)
        total_pl     = real_gain + unreal_gain
        unreal_pct   = (unreal_gain / cost_basis * 100) if cost_basis > 0 else 0.0

        rows.append({
            "Asset"                 : asset,
            "Sector"                : sector,
            "Shares Held"           : round(shares_held, 4),
            "Avg Purchase Price"    : round(avg_price, 2),
            "Current Price"         : round(float(current_price), 2),
            "Cost Basis (KES)"      : round(cost_basis, 2),
            "Market Value (KES)"    : round(market_value, 2),
            "Unrealised P&L (KES)"  : round(unreal_gain, 2),
            "Unrealised P&L %"      : round(unreal_pct, 2),
            "Realised P&L (KES)"    : round(real_gain, 2),
            "Total P&L (KES)"       : round(total_pl, 2),
        })

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    # Sort by market value descending
    result = result.sort_values("Market Value (KES)", ascending=False).reset_index(drop=True)
    return result


# ── Summary metrics ────────────────────────────────────────────────────────────

def build_cost_summary(tx_df: pd.DataFrame, current_market_value: float) -> pd.DataFrame:
    """
    High-level cost and P&L summary table for display.
    """
    invested   = total_capital_invested(tx_df)
    withdrawn  = total_capital_withdrawn(tx_df)
    net_dep    = net_capital_deployed(tx_df)
    true_pl    = true_profit_loss(tx_df, current_market_value)
    roic       = return_on_invested_capital(tx_df, current_market_value)
    real_gain  = realised_gain_total(tx_df)
    unreal_gain= unrealised_gain_total(tx_df)

    def kes(v): return f"KES {v:,.2f}"
    def pct(v): return f"{v:.2f}%" if v is not None else "N/A"

    rows = [
        ("Total Capital Ever Invested",  kes(invested),
         "All buy transactions including fees"),
        ("Total Capital Withdrawn",       kes(withdrawn),
         "All sell proceeds net of fees"),
        ("Net Capital Deployed",          kes(net_dep),
         "Cash still working in the portfolio"),
        ("Current Market Value",          kes(current_market_value),
         "Today's value of all holdings"),
        ("True Profit / Loss",            kes(true_pl),
         "Market value minus net capital deployed"),
        ("Return on Invested Capital",    pct(roic),
         "True P&L as % of net capital deployed"),
        ("Realised Gains",                kes(real_gain),
         "Locked-in profit from completed sells"),
        ("Unrealised Gains",              kes(unreal_gain),
         "Paper profit on current open positions"),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value", "Description"])


# ── Investment pace ────────────────────────────────────────────────────────────

def build_investment_pace(tx_df: pd.DataFrame) -> pd.DataFrame:
    """
    Monthly capital invested — useful for seeing when large tranches
    were deployed and whether investment is regular or lumpy.
    """
    df = _clean_tx(tx_df)
    if df.empty:
        return pd.DataFrame()
    buys = df[df["Action"].isin(BUY_ACTIONS)].copy()
    buys["Month"] = buys["Date"].dt.to_period("M").astype(str)
    pace = buys.groupby("Month").agg(
        Capital_Invested=("Gross", "sum"),
        Transactions=("Gross", "count"),
    ).reset_index()
    pace.columns = ["Month", "Capital Invested (KES)", "Transactions"]
    return pace
