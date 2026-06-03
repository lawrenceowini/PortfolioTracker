"""
corporate_actions.py — Phase 5: Corporate Actions Tracking
===========================================================
Handles stock splits, reverse splits, rights issues, and bonus shares.
These events affect position size and cost basis but are NOT regular
buy/sell transactions — they need separate treatment.

Storage: corporate_actions_log.json (same folder as scripts)

Each action type:
  SPLIT        — shares multiply, price divides (e.g. 2-for-1 split)
  REVERSE_SPLIT — shares divide, price multiplies (e.g. 1-for-10)
  BONUS        — new shares issued free (like a split but from reserves)
  RIGHTS       — right to buy new shares at a discount; user chooses to exercise
  CONSOLIDATION — same as reverse split

Effect on holdings:
  - New share count = old shares × ratio
  - New cost basis per share = old cost basis / ratio (SPLIT/BONUS)
  - New cost basis per share = old cost basis × ratio (REVERSE_SPLIT)
  - Rights: new shares added at subscription price (cash outflow recorded)
"""

import json
import os
import datetime
import math
from typing import Optional

import pandas as pd
import numpy as np

ACTIONS_FILE = "corporate_actions_log.json"

ACTION_TYPES = {
    "SPLIT"        : "Stock Split (e.g. 2-for-1: you receive extra shares)",
    "REVERSE_SPLIT": "Reverse Split / Consolidation (e.g. 1-for-10: shares reduced)",
    "BONUS"        : "Bonus Issue (free shares from company reserves)",
    "RIGHTS"       : "Rights Issue (right to buy new shares at discount price)",
}

NSE_ASSETS = [
    "Co-op Bank", "Equity", "KCB", "NCBA", "Safaricom",
    "Jubilee", "CIC", "Britam", "KenGen", "Kenya Power",
    "Total Energies Marketing",
]


# ── Persistence ────────────────────────────────────────────────────────────────

def load_actions() -> list:
    if not os.path.exists(ACTIONS_FILE):
        return []
    try:
        with open(ACTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_actions(actions: list) -> None:
    with open(ACTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(actions, f, indent=2, default=str)


def add_action(
    asset: str,
    action_type: str,
    effective_date: str,
    ratio_from: float,
    ratio_to: float,
    subscription_price: Optional[float] = None,
    notes: str = "",
) -> dict:
    """
    Create and persist a new corporate action record.

    ratio_from / ratio_to:
      SPLIT 2-for-1  → ratio_from=1, ratio_to=2  (you get 2 for every 1)
      REVERSE 1-for-10 → ratio_from=10, ratio_to=1
      BONUS 1-for-5  → ratio_from=5, ratio_to=1  (1 bonus for every 5 held)
      RIGHTS 1-for-4 → ratio_from=4, ratio_to=1  (right to buy 1 for every 4)
    """
    action = {
        "id"                : f"{asset}_{action_type}_{effective_date}_{int(datetime.datetime.now().timestamp())}",
        "asset"             : asset,
        "action_type"       : action_type,
        "effective_date"    : effective_date,
        "ratio_from"        : ratio_from,
        "ratio_to"          : ratio_to,
        "subscription_price": subscription_price,
        "notes"             : notes,
        "recorded_at"       : datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "applied"           : False,
    }
    actions = load_actions()
    actions.append(action)
    save_actions(actions)
    return action


def delete_action(action_id: str) -> bool:
    actions = load_actions()
    before = len(actions)
    actions = [a for a in actions if a.get("id") != action_id]
    save_actions(actions)
    return len(actions) < before


# ── Impact calculations ────────────────────────────────────────────────────────

def compute_split_ratio(ratio_from: float, ratio_to: float) -> float:
    """
    Returns the multiplier for shares.
    SPLIT 2-for-1: ratio_from=1, ratio_to=2 → multiplier=2.0
    BONUS 1-for-5: ratio_from=5, ratio_to=1 → multiplier=1.2 (you get 1 extra per 5 = 6/5)
    """
    if ratio_from <= 0:
        return 1.0
    return ratio_to / ratio_from


def compute_bonus_multiplier(ratio_from: float, ratio_to: float) -> float:
    """
    Bonus: receive ratio_to new shares for every ratio_from held.
    Total new shares = (ratio_from + ratio_to) / ratio_from
    e.g. 1-for-5 → (5+1)/5 = 1.2×
    """
    if ratio_from <= 0:
        return 1.0
    return (ratio_from + ratio_to) / ratio_from


def apply_action_to_holdings(
    action: dict,
    holdings_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Return a NEW holdings DataFrame with the corporate action applied.
    Does NOT modify the original. Records the change as metadata.
    """
    if holdings_df.empty:
        return holdings_df

    df      = holdings_df.copy()
    asset   = action["asset"]
    atype   = action["action_type"]
    rf      = float(action["ratio_from"])
    rt      = float(action["ratio_to"])
    sub_px  = action.get("subscription_price") or 0.0

    mask = df["Asset"] == asset
    if not mask.any():
        return df   # asset not in current holdings

    df["Shares"]        = pd.to_numeric(df["Shares"],        errors="coerce").fillna(0)
    df["Buy Price"]     = pd.to_numeric(df["Buy Price"],      errors="coerce").fillna(0)
    df["Current Price"] = pd.to_numeric(df["Current Price"], errors="coerce").fillna(0)
    df["Market Value"]  = pd.to_numeric(df["Market Value"],  errors="coerce").fillna(0)

    if atype == "SPLIT":
        multiplier = compute_split_ratio(rf, rt)
        df.loc[mask, "Shares"]    = df.loc[mask, "Shares"]    * multiplier
        df.loc[mask, "Buy Price"] = df.loc[mask, "Buy Price"]  / multiplier
        # Current price also adjusts on ex-date (approximation)
        df.loc[mask, "Current Price"] = df.loc[mask, "Current Price"] / multiplier

    elif atype in ("REVERSE_SPLIT", "CONSOLIDATION"):
        # ratio_from=10, ratio_to=1 → divide shares by 10
        divisor = rf / rt if rt > 0 else rf
        df.loc[mask, "Shares"]        = (df.loc[mask, "Shares"] / divisor).apply(math.floor)
        df.loc[mask, "Buy Price"]     = df.loc[mask, "Buy Price"]     * divisor
        df.loc[mask, "Current Price"] = df.loc[mask, "Current Price"] * divisor

    elif atype == "BONUS":
        multiplier = compute_bonus_multiplier(rf, rt)
        df.loc[mask, "Shares"]    = df.loc[mask, "Shares"]   * multiplier
        # Cost basis per share drops (same total cost, more shares)
        df.loc[mask, "Buy Price"] = df.loc[mask, "Buy Price"] / multiplier

    elif atype == "RIGHTS":
        # User exercises rights: for every rf shares held, buy rt new at sub_px
        current_shares = df.loc[mask, "Shares"].values[0]
        new_shares     = math.floor(current_shares / rf) * rt
        old_cost_basis = df.loc[mask, "Buy Price"].values[0] * current_shares
        rights_cost    = new_shares * sub_px
        total_shares   = current_shares + new_shares
        new_avg_price  = (old_cost_basis + rights_cost) / total_shares if total_shares > 0 else sub_px

        df.loc[mask, "Shares"]    = total_shares
        df.loc[mask, "Buy Price"] = round(new_avg_price, 4)

    # Recalculate market value
    df.loc[mask, "Market Value"] = df.loc[mask, "Shares"] * df.loc[mask, "Current Price"]

    return df


# ── Impact preview ─────────────────────────────────────────────────────────────

def preview_action_impact(
    action: dict,
    holdings_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Return a before/after comparison table for a given corporate action.
    """
    if holdings_df.empty:
        return pd.DataFrame()

    asset = action["asset"]
    mask  = holdings_df["Asset"] == asset
    if not mask.any():
        return pd.DataFrame([{
            "Field": "Status",
            "Before": "—",
            "After" : f"{asset} not found in current holdings",
        }])

    before_row = holdings_df[mask].iloc[0]
    after_df   = apply_action_to_holdings(action, holdings_df)
    after_row  = after_df[after_df["Asset"] == asset].iloc[0]

    rows = []
    for field in ["Shares", "Buy Price", "Current Price", "Market Value"]:
        b = pd.to_numeric(before_row.get(field, 0), errors="coerce") or 0
        a = pd.to_numeric(after_row.get(field, 0),  errors="coerce") or 0
        rows.append({
            "Field" : field,
            "Before": f"{b:,.4f}" if "Price" in field or "Value" in field else f"{b:,.2f}",
            "After" : f"{a:,.4f}" if "Price" in field or "Value" in field else f"{a:,.2f}",
            "Change": f"{((a-b)/b*100):+.2f}%" if b != 0 else "New",
        })
    return pd.DataFrame(rows)


# ── Summary table ──────────────────────────────────────────────────────────────

def build_actions_table(actions: list) -> pd.DataFrame:
    """Convert the actions list into a display DataFrame."""
    if not actions:
        return pd.DataFrame()
    rows = []
    for a in sorted(actions, key=lambda x: x.get("effective_date", ""), reverse=True):
        atype = a.get("action_type", "")
        rf    = a.get("ratio_from", 1)
        rt    = a.get("ratio_to",   1)
        rows.append({
            "Date"       : a.get("effective_date", ""),
            "Asset"      : a.get("asset", ""),
            "Type"       : atype,
            "Ratio"      : f"{rt}-for-{rf}" if atype in ("SPLIT", "BONUS", "RIGHTS") else f"{rf}-for-{rt}",
            "Sub. Price" : f"KES {a['subscription_price']:,.2f}" if a.get("subscription_price") else "—",
            "Notes"      : a.get("notes", ""),
            "Applied"    : "✓" if a.get("applied") else "Pending",
            "_id"        : a.get("id", ""),
        })
    return pd.DataFrame(rows)


# ── NSE historical corporate actions (reference data) ─────────────────────────

KNOWN_NSE_ACTIONS = [
    {
        "asset": "Safaricom", "action_type": "BONUS",
        "effective_date": "2007-07-01",
        "ratio_from": 1, "ratio_to": 1,
        "notes": "1-for-1 bonus issue on IPO shares (illustrative)",
    },
    {
        "asset": "Equity", "action_type": "SPLIT",
        "effective_date": "2011-07-04",
        "ratio_from": 1, "ratio_to": 10,
        "notes": "10-for-1 stock split: KES 5 par → KES 0.50",
    },
    {
        "asset": "KCB", "action_type": "RIGHTS",
        "effective_date": "2020-11-01",
        "ratio_from": 10, "ratio_to": 1,
        "notes": "Rights issue at KES 7.00 per share",
        "subscription_price": 7.0,
    },
]
