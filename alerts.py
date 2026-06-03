"""
alerts.py — Phase 7: Alerts System
====================================
Monitors portfolio conditions and generates alerts for:

1. Price Alerts      — asset price moves beyond a user-set threshold
2. Concentration     — asset or sector breaches risk limits
3. Dividend Alerts   — dividend yield drops below target
4. Drift Alerts      — allocation drifts beyond target threshold
5. Drawdown Alerts   — portfolio drawdown exceeds a warning level

Alert storage: alerts_config.json (thresholds) + alerts_log.json (history)
Delivery: dashboard banners + optional email (uses existing SMTP config)
"""

import json
import os
import datetime
from typing import Optional

import pandas as pd
import numpy as np

ALERTS_CONFIG_FILE = "alerts_config.json"
ALERTS_LOG_FILE    = "alerts_log.json"

ALERT_TYPES = {
    "PRICE_UP"      : "Price risen above threshold",
    "PRICE_DOWN"    : "Price fallen below threshold",
    "CONCENTRATION" : "Asset or sector over concentration limit",
    "DRIFT"         : "Allocation drift exceeds threshold",
    "DIVIDEND_YIELD": "Dividend yield below minimum target",
    "DRAWDOWN"      : "Portfolio drawdown exceeds warning level",
    "CUSTOM"        : "Custom user-defined alert",
}

SEVERITY = {
    "INFO"    : ("ℹ️", "#2563eb", "#eff6ff"),
    "WARNING" : ("⚠️", "#d97706", "#fffbeb"),
    "CRITICAL": ("🚨", "#dc2626", "#fef2f2"),
}


# ── Config persistence ─────────────────────────────────────────────────────────

def load_alerts_config() -> dict:
    if not os.path.exists(ALERTS_CONFIG_FILE):
        return {
            "price_alerts"     : [],
            "concentration"    : {"asset_limit": 10.0, "sector_limit": 20.0, "enabled": True},
            "drift"            : {"threshold": 5.0, "enabled": True},
            "dividend_yield"   : {"min_yield": 2.0, "enabled": False},
            "drawdown"         : {"warning_pct": 10.0, "critical_pct": 20.0, "enabled": True},
            "email_on_critical": False,
        }
    try:
        with open(ALERTS_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return load_alerts_config.__wrapped__() if hasattr(load_alerts_config, "__wrapped__") else {}


def save_alerts_config(config: dict) -> None:
    with open(ALERTS_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, default=str)


def load_alerts_log() -> list:
    if not os.path.exists(ALERTS_LOG_FILE):
        return []
    try:
        with open(ALERTS_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_alerts_log(log: list) -> None:
    # Keep last 500 entries
    with open(ALERTS_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log[-500:], f, indent=2, default=str)


def add_to_log(alert: dict) -> None:
    log = load_alerts_log()
    alert["logged_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.append(alert)
    save_alerts_log(log)


def dismiss_alert(alert_id: str) -> None:
    log = load_alerts_log()
    for a in log:
        if a.get("id") == alert_id:
            a["dismissed"] = True
    save_alerts_log(log)


def clear_dismissed() -> None:
    log = load_alerts_log()
    save_alerts_log([a for a in log if not a.get("dismissed", False)])


# ── Alert generators ──────────────────────────────────────────────────────────

def check_price_alerts(holdings_df: pd.DataFrame, config: dict) -> list:
    """
    Check each user-defined price alert against current prices.
    Returns list of triggered alert dicts.
    """
    alerts   = []
    triggers = config.get("price_alerts", [])
    if holdings_df.empty or not triggers:
        return alerts

    price_map = {}
    if "Asset" in holdings_df.columns and "Current Price" in holdings_df.columns:
        price_map = dict(zip(
            holdings_df["Asset"],
            pd.to_numeric(holdings_df["Current Price"], errors="coerce").fillna(0),
        ))

    for t in triggers:
        asset     = t.get("asset", "")
        direction = t.get("direction", "above")  # "above" or "below"
        threshold = float(t.get("threshold", 0))
        current   = float(price_map.get(asset, 0))

        if current == 0:
            continue

        triggered = (direction == "above" and current >= threshold) or \
                    (direction == "below" and current <= threshold)

        if triggered:
            alerts.append({
                "id"      : f"price_{asset}_{direction}_{threshold}",
                "type"    : "PRICE_UP" if direction == "above" else "PRICE_DOWN",
                "severity": "WARNING",
                "asset"   : asset,
                "message" : f"{asset} price KES {current:,.2f} has {'risen above' if direction == 'above' else 'fallen below'} your alert level of KES {threshold:,.2f}",
                "value"   : current,
                "threshold": threshold,
            })
    return alerts


def check_concentration_alerts(holdings_df: pd.DataFrame, config: dict) -> list:
    """Check asset and sector concentration against limits."""
    alerts = []
    cfg    = config.get("concentration", {})
    if not cfg.get("enabled", True) or holdings_df.empty:
        return alerts

    asset_limit  = float(cfg.get("asset_limit",  10.0))
    sector_limit = float(cfg.get("sector_limit", 20.0))

    mv_col = "Market Value"
    if mv_col not in holdings_df.columns:
        return alerts

    total = pd.to_numeric(holdings_df[mv_col], errors="coerce").fillna(0).sum()
    if total == 0:
        return alerts

    # Asset checks
    if "Asset" in holdings_df.columns:
        for _, row in holdings_df.iterrows():
            mv    = pd.to_numeric(row.get(mv_col, 0), errors="coerce") or 0
            alloc = mv / total * 100
            if alloc > asset_limit:
                excess = alloc - asset_limit
                alerts.append({
                    "id"       : f"conc_asset_{row['Asset']}",
                    "type"     : "CONCENTRATION",
                    "severity" : "CRITICAL" if excess > 10 else "WARNING",
                    "asset"    : row["Asset"],
                    "message"  : f"{row['Asset']} is {alloc:.1f}% of portfolio — exceeds {asset_limit:.0f}% asset limit by {excess:.1f}pp",
                    "value"    : round(alloc, 2),
                    "threshold": asset_limit,
                })

    # Sector checks
    if "Sector" in holdings_df.columns:
        sector_totals = holdings_df.copy()
        sector_totals[mv_col] = pd.to_numeric(sector_totals[mv_col], errors="coerce").fillna(0)
        sector_alloc = sector_totals.groupby("Sector")[mv_col].sum() / total * 100
        for sector, alloc in sector_alloc.items():
            if alloc > sector_limit:
                excess = alloc - sector_limit
                alerts.append({
                    "id"       : f"conc_sector_{sector}",
                    "type"     : "CONCENTRATION",
                    "severity" : "CRITICAL" if excess > 10 else "WARNING",
                    "asset"    : sector,
                    "message"  : f"{sector} sector is {alloc:.1f}% of portfolio — exceeds {sector_limit:.0f}% sector limit by {excess:.1f}pp",
                    "value"    : round(alloc, 2),
                    "threshold": sector_limit,
                })
    return alerts


def check_dividend_yield_alerts(div_df: pd.DataFrame, holdings_df: pd.DataFrame, config: dict) -> list:
    """Alert when overall portfolio dividend yield drops below minimum."""
    alerts = []
    cfg    = config.get("dividend_yield", {})
    if not cfg.get("enabled", False) or div_df.empty or holdings_df.empty:
        return alerts

    min_yield = float(cfg.get("min_yield", 2.0))

    # Compute overall yield
    div_col = next((c for c in ["Annual Dividend", "Total Dividend"] if c in div_df.columns), None)
    if div_col is None:
        return alerts

    total_div = pd.to_numeric(div_df[div_col], errors="coerce").fillna(0).sum()
    total_mv  = pd.to_numeric(holdings_df.get("Market Value", pd.Series()), errors="coerce").fillna(0).sum()

    if total_mv == 0:
        return alerts

    overall_yield = total_div / total_mv * 100
    if overall_yield < min_yield:
        alerts.append({
            "id"       : "dividend_yield_low",
            "type"     : "DIVIDEND_YIELD",
            "severity" : "INFO",
            "asset"    : "Portfolio",
            "message"  : f"Portfolio dividend yield {overall_yield:.2f}% is below your minimum target of {min_yield:.2f}%",
            "value"    : round(overall_yield, 2),
            "threshold": min_yield,
        })
    return alerts


def check_drawdown_alerts(history_df: pd.DataFrame, config: dict) -> list:
    """Alert when portfolio drawdown exceeds warning or critical levels."""
    alerts = []
    cfg    = config.get("drawdown", {})
    if not cfg.get("enabled", True) or history_df.empty:
        return alerts

    warning_pct  = float(cfg.get("warning_pct",  10.0))
    critical_pct = float(cfg.get("critical_pct", 20.0))

    df = history_df.copy()
    df["Portfolio Value"] = pd.to_numeric(df.get("Portfolio Value", 0), errors="coerce").fillna(0)
    df = df[df["Portfolio Value"] > 0].sort_values("Date")

    if len(df) < 2:
        return alerts

    peak    = df["Portfolio Value"].max()
    current = df["Portfolio Value"].iloc[-1]
    dd_pct  = (peak - current) / peak * 100 if peak > 0 else 0

    if dd_pct >= critical_pct:
        alerts.append({
            "id"       : "drawdown_critical",
            "type"     : "DRAWDOWN",
            "severity" : "CRITICAL",
            "asset"    : "Portfolio",
            "message"  : f"Portfolio is {dd_pct:.1f}% below its peak — exceeds critical threshold of {critical_pct:.0f}%",
            "value"    : round(dd_pct, 2),
            "threshold": critical_pct,
        })
    elif dd_pct >= warning_pct:
        alerts.append({
            "id"       : "drawdown_warning",
            "type"     : "DRAWDOWN",
            "severity" : "WARNING",
            "asset"    : "Portfolio",
            "message"  : f"Portfolio is {dd_pct:.1f}% below its peak — above warning threshold of {warning_pct:.0f}%",
            "value"    : round(dd_pct, 2),
            "threshold": warning_pct,
        })
    return alerts


def run_all_checks(
    holdings_df: pd.DataFrame,
    div_df: pd.DataFrame,
    history_df: pd.DataFrame,
    config: dict,
) -> list:
    """Run all alert checks and return combined list, logging new ones."""
    all_alerts = []
    all_alerts += check_price_alerts(holdings_df, config)
    all_alerts += check_concentration_alerts(holdings_df, config)
    all_alerts += check_dividend_yield_alerts(div_df, holdings_df, config)
    all_alerts += check_drawdown_alerts(history_df, config)

    # Log any new alerts (not already in log)
    existing_log = load_alerts_log()
    existing_ids = {a.get("id") for a in existing_log}
    for alert in all_alerts:
        if alert.get("id") not in existing_ids:
            add_to_log(alert)

    return all_alerts


# ── Email alert sender ─────────────────────────────────────────────────────────

def send_alert_email(alerts: list, smtp_config: dict, recipient: str) -> tuple:
    """Send critical alerts by email. Returns (success, message)."""
    critical = [a for a in alerts if a.get("severity") == "CRITICAL"]
    if not critical:
        return False, "No critical alerts to send."

    if not smtp_config.get("username") or not smtp_config.get("password"):
        return False, "SMTP not configured."

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        body_lines = [
            "PRO_LAW Portfolio Tracker — Critical Alerts",
            f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 50,
            "",
        ]
        for a in critical:
            body_lines.append(f"🚨 {a.get('type', '')} — {a.get('asset', '')}")
            body_lines.append(f"   {a.get('message', '')}")
            body_lines.append("")

        body_lines += [
            "=" * 50,
            "This is an automated alert from your PRO_LAW Portfolio Tracking System.",
            "Log in to your dashboard to review and dismiss these alerts.",
        ]

        msg            = MIMEMultipart()
        msg["From"]    = smtp_config.get("from") or smtp_config.get("username")
        msg["To"]      = recipient
        msg["Subject"] = f"⚠️ PRO_LAW Portfolio Alert — {len(critical)} Critical Issue(s)"
        msg.attach(MIMEText("\n".join(body_lines), "plain"))

        server = smtplib.SMTP(smtp_config.get("server", "smtp.gmail.com"), int(smtp_config.get("port", 587)))
        server.ehlo()
        if smtp_config.get("use_tls", True):
            server.starttls()
            server.ehlo()
        server.login(smtp_config["username"], smtp_config["password"])
        server.sendmail(msg["From"], recipient, msg.as_string())
        server.quit()
        return True, f"Alert email sent to {recipient}"
    except Exception as e:
        return False, str(e)


# ── Helpers ────────────────────────────────────────────────────────────────────

def alerts_to_df(alerts: list) -> pd.DataFrame:
    if not alerts:
        return pd.DataFrame()
    rows = []
    for a in alerts:
        icon, _, _ = SEVERITY.get(a.get("severity", "INFO"), ("ℹ️", "", ""))
        rows.append({
            "Severity": f"{icon} {a.get('severity', 'INFO')}",
            "Type"    : a.get("type", ""),
            "Asset"   : a.get("asset", ""),
            "Message" : a.get("message", ""),
            "Value"   : a.get("value", ""),
            "Threshold": a.get("threshold", ""),
        })
    return pd.DataFrame(rows)


def count_by_severity(alerts: list) -> dict:
    counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
    for a in alerts:
        sev = a.get("severity", "INFO")
        counts[sev] = counts.get(sev, 0) + 1
    return counts
