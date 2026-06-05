"""
audit_trail.py — Phase 9: Audit Trail
======================================
Tamper-evident log of every significant change made to portfolio data.

Records:
  - Portfolio file loads (which file, when, file size/hash)
  - Holdings changes detected between loads (asset added/removed, value changes)
  - Risk parameter changes (sector limit, asset cap, exclusions)
  - Target allocation changes
  - Corporate actions recorded
  - FX rate overrides
  - Alert configuration changes
  - Report generation and email delivery
  - Script executions (update_portfolio.py runs)
  - User sessions (dashboard open/close)

Tamper-evidence mechanism:
  Each entry contains a SHA-256 hash of (previous_entry_hash + entry_content).
  Any modification to a past entry breaks the hash chain, making tampering
  detectable. This is a lightweight audit log — not a blockchain — but
  sufficient for internal accountability.

Storage: audit_log.json (append-only in normal operation)
"""

import json
import os
import hashlib
import datetime
import copy
from typing import Optional

import pandas as pd

AUDIT_FILE    = "audit_log.json"
MAX_ENTRIES   = 10000   # keep last 10,000 entries

# ── Event categories ──────────────────────────────────────────────────────────
EVENTS = {
    "FILE_LOAD"        : "Portfolio file loaded into dashboard",
    "HOLDINGS_CHANGE"  : "Change detected in holdings data",
    "SCRIPT_RUN"       : "update_portfolio.py executed",
    "RISK_CHANGE"      : "Risk parameters modified",
    "TARGET_CHANGE"    : "Target allocation modified",
    "CORP_ACTION"      : "Corporate action recorded",
    "FX_CHANGE"        : "FX rates or currency assignments modified",
    "ALERT_CHANGE"     : "Alert configuration modified",
    "ALERT_TRIGGERED"  : "Alert condition triggered",
    "REPORT_GENERATED" : "PDF report generated",
    "EMAIL_SENT"       : "Report emailed to recipient",
    "SESSION_START"    : "Dashboard session started",
    "DATA_EXPORT"      : "Data exported (CSV/download)",
    "CONFIG_CHANGE"    : "System configuration changed",
    "MANUAL_NOTE"      : "Manual note added by user",
}


# ── Hash chain ────────────────────────────────────────────────────────────────

def _hash_entry(prev_hash: str, entry_content: str) -> str:
    """SHA-256 of previous hash + entry content."""
    combined = (prev_hash + entry_content).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def _entry_content_str(entry: dict) -> str:
    """Deterministic string representation of an entry for hashing."""
    # Exclude the hash field itself
    e = {k: v for k, v in entry.items() if k != "entry_hash"}
    return json.dumps(e, sort_keys=True, default=str)


# ── Core persistence ──────────────────────────────────────────────────────────

def load_log() -> list:
    if not os.path.exists(AUDIT_FILE):
        return []
    try:
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_log(log: list) -> None:
    # Keep last MAX_ENTRIES
    log = log[-MAX_ENTRIES:]
    with open(AUDIT_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, default=str)


def append_entry(event_type: str, details: dict, user_note: str = "") -> dict:
    """
    Append a new entry to the audit log.
    Returns the created entry.
    """
    log      = load_log()
    prev_hash = log[-1]["entry_hash"] if log else "GENESIS"

    entry = {
        "id"          : len(log) + 1,
        "timestamp"   : datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event_type"  : event_type,
        "description" : EVENTS.get(event_type, event_type),
        "details"     : details,
        "user_note"   : user_note,
        "entry_hash"  : "",   # placeholder — filled below
    }

    content_str       = _entry_content_str(entry)
    entry["entry_hash"] = _hash_entry(prev_hash, content_str)

    log.append(entry)
    save_log(log)
    return entry


# ── Integrity verification ────────────────────────────────────────────────────

def verify_chain() -> tuple:
    """
    Verify the hash chain integrity of the entire audit log.
    Returns (is_valid: bool, first_broken_id: int or None, message: str)
    """
    log = load_log()
    if not log:
        return True, None, "Audit log is empty."

    prev_hash = "GENESIS"
    for entry in log:
        stored_hash  = entry.get("entry_hash", "")
        content_str  = _entry_content_str(entry)
        expected     = _hash_entry(prev_hash, content_str)
        if stored_hash != expected:
            return False, entry.get("id"), (
                f"Hash chain broken at entry #{entry.get('id')} "
                f"({entry.get('timestamp','?')} — {entry.get('event_type','?')}). "
                f"This entry may have been tampered with."
            )
        prev_hash = stored_hash

    return True, None, f" All {len(log)} entries verified — log is intact."


# ── Change detection ──────────────────────────────────────────────────────────

def _file_hash(file_path: str) -> str:
    """SHA-256 of a file's contents."""
    try:
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return "unknown"


def _file_size_kb(file_path: str) -> float:
    try:
        return round(os.path.getsize(file_path) / 1024, 1)
    except Exception:
        return 0.0


def log_file_load(file_path: str, sheet_names: list) -> None:
    """Log a portfolio file being loaded."""
    append_entry("FILE_LOAD", {
        "file"       : os.path.basename(file_path),
        "path"       : file_path,
        "size_kb"    : _file_size_kb(file_path),
        "file_hash"  : _file_hash(file_path),
        "sheets"     : sheet_names,
    })


def detect_holdings_changes(prev_df: pd.DataFrame, curr_df: pd.DataFrame) -> list:
    """
    Compare two holdings DataFrames and return a list of detected changes.
    """
    changes = []
    if prev_df.empty and curr_df.empty:
        return changes

    asset_col = next((c for c in curr_df.columns if c.strip().lower() == "asset"), None)
    mv_col    = next((c for c in curr_df.columns if c.strip().lower() == "market value"), None)

    if not asset_col:
        return changes

    prev_assets = set(prev_df[asset_col].dropna().astype(str)) if asset_col in prev_df.columns else set()
    curr_assets = set(curr_df[asset_col].dropna().astype(str))

    # New assets
    for a in sorted(curr_assets - prev_assets):
        changes.append({"type": "ASSET_ADDED", "asset": a})

    # Removed assets
    for a in sorted(prev_assets - curr_assets):
        changes.append({"type": "ASSET_REMOVED", "asset": a})

    # Value changes
    if mv_col and mv_col in prev_df.columns:
        prev_mv = prev_df.set_index(asset_col)[mv_col] if asset_col in prev_df.columns else pd.Series()
        curr_mv = curr_df.set_index(asset_col)[mv_col]

        for asset in curr_assets & prev_assets:
            try:
                p = float(pd.to_numeric(prev_mv.get(asset, 0), errors="coerce") or 0)
                c = float(pd.to_numeric(curr_mv.get(asset, 0), errors="coerce") or 0)
                if p > 0 and abs(c - p) / p > 0.01:   # >1% change
                    changes.append({
                        "type"   : "VALUE_CHANGE",
                        "asset"  : asset,
                        "before" : round(p, 2),
                        "after"  : round(c, 2),
                        "change_pct": round((c - p) / p * 100, 2),
                    })
            except Exception:
                continue

    return changes


def log_holdings_change(changes: list, file_name: str) -> None:
    if not changes:
        return
    append_entry("HOLDINGS_CHANGE", {
        "file"           : file_name,
        "changes_count"  : len(changes),
        "changes"        : changes[:50],   # cap at 50 to keep log manageable
    })


def log_risk_change(old_params: dict, new_params: dict) -> None:
    append_entry("RISK_CHANGE", {
        "before": old_params,
        "after" : new_params,
    })


def log_target_change(old_targets: dict, new_targets: dict, target_type: str) -> None:
    append_entry("TARGET_CHANGE", {
        "type"  : target_type,
        "before": old_targets,
        "after" : new_targets,
    })


def log_corp_action(action: dict) -> None:
    append_entry("CORP_ACTION", {
        "asset"       : action.get("asset"),
        "action_type" : action.get("action_type"),
        "date"        : action.get("effective_date"),
        "ratio"       : f"{action.get('ratio_to')}-for-{action.get('ratio_from')}",
    })


def log_fx_change(change_type: str, details: dict) -> None:
    append_entry("FX_CHANGE", {"change_type": change_type, **details})


def log_alert_triggered(alerts: list) -> None:
    if not alerts:
        return
    append_entry("ALERT_TRIGGERED", {
        "count"   : len(alerts),
        "critical": sum(1 for a in alerts if a.get("severity") == "CRITICAL"),
        "warning" : sum(1 for a in alerts if a.get("severity") == "WARNING"),
        "alerts"  : [{"type": a.get("type"), "asset": a.get("asset"), "message": a.get("message")} for a in alerts],
    })


def log_email_sent(recipient: str, file_name: str, success: bool) -> None:
    append_entry("EMAIL_SENT", {
        "recipient": recipient,
        "file"     : file_name,
        "success"  : success,
    })


def log_script_run(success: bool, return_code: int, duration_s: float) -> None:
    append_entry("SCRIPT_RUN", {
        "success"    : success,
        "return_code": return_code,
        "duration_s" : round(duration_s, 1),
    })


def log_manual_note(note: str) -> None:
    append_entry("MANUAL_NOTE", {"note": note})


def log_session_start() -> None:
    append_entry("SESSION_START", {
        "dashboard_version": "PRO_LAW v1.0",
        "python_version"   : __import__("sys").version.split()[0],
    })


# ── Display helpers ───────────────────────────────────────────────────────────

def build_log_df(log: list, event_filter: Optional[str] = None) -> pd.DataFrame:
    """Convert audit log to display DataFrame."""
    if not log:
        return pd.DataFrame()

    filtered = log if not event_filter else [e for e in log if e.get("event_type") == event_filter]
    rows = []
    for e in reversed(filtered):   # newest first
        rows.append({
            "#"          : e.get("id", ""),
            "Timestamp"  : e.get("timestamp", ""),
            "Event"      : e.get("event_type", ""),
            "Description": e.get("description", ""),
            "Key Detail" : _summarise_details(e.get("details", {})),
            "Note"       : e.get("user_note", ""),
            "Hash"       : e.get("entry_hash", "")[:12] + "…",
        })
    return pd.DataFrame(rows)


def _summarise_details(details: dict) -> str:
    """One-line summary of an entry's details for the log table."""
    if not details:
        return ""
    if "file" in details:
        return f"File: {details['file']}"
    if "changes_count" in details:
        return f"{details['changes_count']} holdings changes"
    if "asset" in details:
        return f"Asset: {details['asset']}"
    if "recipient" in details:
        return f"To: {details['recipient']} — {'OK' if details.get('success') else 'FAILED'}"
    if "return_code" in details:
        return f"Script {'succeeded' if details.get('success') else 'failed'} in {details.get('duration_s','?')}s"
    if "note" in details:
        return details["note"][:80]
    # Generic: first key-value pair
    first_key = next(iter(details))
    return f"{first_key}: {str(details[first_key])[:60]}"


def get_stats(log: list) -> dict:
    """Summary statistics for the audit log."""
    if not log:
        return {}
    from collections import Counter
    event_counts = Counter(e.get("event_type") for e in log)
    return {
        "total_entries"    : len(log),
        "first_entry"      : log[0].get("timestamp", ""),
        "latest_entry"     : log[-1].get("timestamp", ""),
        "event_breakdown"  : dict(event_counts),
        "file_loads"       : event_counts.get("FILE_LOAD", 0),
        "script_runs"      : event_counts.get("SCRIPT_RUN", 0),
        "alerts_triggered" : event_counts.get("ALERT_TRIGGERED", 0),
        "emails_sent"      : event_counts.get("EMAIL_SENT", 0),
        "manual_notes"     : event_counts.get("MANUAL_NOTE", 0),
    }
