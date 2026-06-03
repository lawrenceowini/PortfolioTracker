"""
target_allocation.py — Phase 4: Target Allocation Engine
=========================================================
Allows the user to define target weights per sector and per asset,
then computes:
  - Drift: how far each position has moved from its target
  - Drift alerts: positions breaching a configurable threshold
  - Trade suggestions: the exact buys/sells to restore targets
  - Drift history: saved across sessions via a JSON file

Storage: targets and drift history are saved to
  target_allocation_config.json  (same folder as the scripts)
"""

import json
import math
import os
import datetime
from typing import Optional

import pandas as pd
import numpy as np

CONFIG_FILE = "target_allocation_config.json"


# ── Persistence ────────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load saved target allocation config from disk."""
    if not os.path.exists(CONFIG_FILE):
        return {"sector_targets": {}, "asset_targets": {}, "drift_threshold": 5.0, "drift_history": []}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"sector_targets": {}, "asset_targets": {}, "drift_threshold": 5.0, "drift_history": []}


def save_config(config: dict) -> None:
    """Persist target allocation config to disk."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, default=str)


# ── Core drift computation ─────────────────────────────────────────────────────

def compute_sector_drift(holdings_df: pd.DataFrame, sector_targets: dict) -> pd.DataFrame:
    """
    Compare actual sector weights against targets.

    Returns a DataFrame with:
      Sector | Actual % | Target % | Drift pp | Drift Direction | Breached
    """
    if holdings_df.empty or "Sector" not in holdings_df.columns:
        return pd.DataFrame()

    h = holdings_df.copy()
    h["Market Value"] = pd.to_numeric(h["Market Value"], errors="coerce").fillna(0)
    total = h["Market Value"].sum()
    if total == 0:
        return pd.DataFrame()

    sector_actual = h.groupby("Sector")["Market Value"].sum() / total * 100
    all_sectors   = sorted(set(list(sector_actual.index) + list(sector_targets.keys())))

    rows = []
    for sector in all_sectors:
        actual = round(float(sector_actual.get(sector, 0.0)), 2)
        target = round(float(sector_targets.get(sector, 0.0)), 2)
        drift  = round(actual - target, 2)
        rows.append({
            "Sector"         : sector,
            "Actual %"       : actual,
            "Target %"       : target,
            "Drift (pp)"     : drift,
            "Direction"      : "Overweight" if drift > 0 else ("Underweight" if drift < 0 else "On Target"),
        })

    return pd.DataFrame(rows).sort_values("Drift (pp)", key=abs, ascending=False).reset_index(drop=True)


def compute_asset_drift(holdings_df: pd.DataFrame, asset_targets: dict) -> pd.DataFrame:
    """
    Compare actual asset weights against per-asset targets.
    """
    if holdings_df.empty or "Asset" not in holdings_df.columns:
        return pd.DataFrame()

    h = holdings_df.copy()
    h["Market Value"] = pd.to_numeric(h["Market Value"], errors="coerce").fillna(0)
    total = h["Market Value"].sum()
    if total == 0:
        return pd.DataFrame()

    asset_actual = (h.set_index("Asset")["Market Value"] / total * 100).to_dict()
    all_assets   = sorted(set(list(asset_actual.keys()) + list(asset_targets.keys())))

    rows = []
    for asset in all_assets:
        actual = round(float(asset_actual.get(asset, 0.0)), 2)
        target = round(float(asset_targets.get(asset, 0.0)), 2)
        drift  = round(actual - target, 2)
        # sector lookup
        sector = ""
        if not holdings_df.empty and "Sector" in holdings_df.columns:
            match = holdings_df[holdings_df["Asset"] == asset]
            if not match.empty:
                sector = str(match.iloc[0].get("Sector", ""))
        rows.append({
            "Asset"      : asset,
            "Sector"     : sector,
            "Actual %"   : actual,
            "Target %"   : target,
            "Drift (pp)" : drift,
            "Direction"  : "Overweight" if drift > 0 else ("Underweight" if drift < 0 else "On Target"),
        })

    return pd.DataFrame(rows).sort_values("Drift (pp)", key=abs, ascending=False).reset_index(drop=True)


def get_breached(drift_df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Filter drift DataFrame to only rows breaching the threshold."""
    if drift_df.empty or "Drift (pp)" not in drift_df.columns:
        return pd.DataFrame()
    return drift_df[drift_df["Drift (pp)"].abs() > threshold].copy()


# ── Trade suggestions ──────────────────────────────────────────────────────────

def build_target_trades(
    holdings_df: pd.DataFrame,
    asset_targets: dict,
    total_value: float,
    available_cash: float = 0.0,
) -> pd.DataFrame:
    """
    Generate trade suggestions to move from actual to target allocation.

    Logic:
      1. For each asset with a target, compute target value = target% × total_value
      2. delta = target_value - current_market_value
      3. delta > 0 → BUY, delta < 0 → SELL
      4. Shares = ceil(|delta| / current_price)

    available_cash: extra cash available to fund buys (e.g. new capital being added)
    """
    if holdings_df.empty or not asset_targets or total_value == 0:
        return pd.DataFrame()

    h = holdings_df.copy()
    h["Market Value"]   = pd.to_numeric(h["Market Value"],   errors="coerce").fillna(0)
    h["Current Price"]  = pd.to_numeric(h["Current Price"],  errors="coerce").fillna(0)
    asset_mv    = h.set_index("Asset")["Market Value"].to_dict()
    asset_price = h.set_index("Asset")["Current Price"].to_dict()
    asset_sector= h.set_index("Asset")["Sector"].to_dict() if "Sector" in h.columns else {}

    effective_total = total_value + available_cash
    trades = []

    for asset, target_pct in asset_targets.items():
        if target_pct <= 0:
            continue
        target_value  = target_pct / 100 * effective_total
        current_value = float(asset_mv.get(asset, 0.0))
        delta         = target_value - current_value
        price         = float(asset_price.get(asset, 0.0))

        if abs(delta) < 100 or price <= 0:   # ignore trivial trades
            continue

        action = "BUY" if delta > 0 else "SELL"
        shares = math.ceil(abs(delta) / price)
        est_value = shares * price

        trades.append({
            "Action"          : action,
            "Asset"           : asset,
            "Sector"          : asset_sector.get(asset, ""),
            "Current Value"   : round(current_value, 2),
            "Target Value"    : round(target_value, 2),
            "Delta (KES)"     : round(delta, 2),
            "Shares"          : shares,
            "Price (KES)"     : round(price, 2),
            "Est. Trade Value": round(est_value, 2),
            "Reason"          : f"Restore {asset} to {target_pct:.1f}% target",
        })

    if not trades:
        return pd.DataFrame()

    df = pd.DataFrame(trades)
    # Sort: SELLs first (free up cash), then BUYs
    df["_order"] = df["Action"].map({"SELL": 0, "BUY": 1})
    return df.sort_values(["_order", "Est. Trade Value"], ascending=[True, False]).drop(columns=["_order"]).reset_index(drop=True)


# ── Drift history ──────────────────────────────────────────────────────────────

def record_drift_snapshot(config: dict, sector_drift: pd.DataFrame, asset_drift: pd.DataFrame, total_value: float) -> dict:
    """
    Append today's drift snapshot to the drift history list in config.
    Keeps last 90 snapshots.
    """
    if sector_drift.empty:
        return config

    snapshot = {
        "date"        : datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_value" : total_value,
        "max_sector_drift": float(sector_drift["Drift (pp)"].abs().max()) if not sector_drift.empty else 0,
        "max_asset_drift" : float(asset_drift["Drift (pp)"].abs().max())  if not asset_drift.empty  else 0,
        "breached_sectors": sector_drift[sector_drift["Drift (pp)"].abs() > config.get("drift_threshold", 5)]["Sector"].tolist(),
        "breached_assets" : asset_drift[asset_drift["Drift (pp)"].abs()  > config.get("drift_threshold", 5)]["Asset"].tolist()  if not asset_drift.empty else [],
    }

    history = config.get("drift_history", [])
    history.append(snapshot)
    config["drift_history"] = history[-90:]   # keep last 90
    return config


def get_drift_history_df(config: dict) -> pd.DataFrame:
    """Convert drift history list to a DataFrame for charting."""
    history = config.get("drift_history", [])
    if not history:
        return pd.DataFrame()
    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


# ── Validation ─────────────────────────────────────────────────────────────────

def validate_targets(targets: dict) -> tuple:
    """
    Validate that target weights sum to ≤ 100%.
    Returns (is_valid: bool, message: str, total: float)
    """
    total = sum(float(v) for v in targets.values() if v)
    if total > 100.01:
        return False, f"Targets sum to {total:.2f}% — must be ≤ 100%.", total
    if total < 99.0:
        return True, f"Targets sum to {total:.2f}% — {100-total:.2f}% is unallocated (treated as cash/unassigned).", total
    return True, f"Targets sum to {total:.2f}% ✓", total
