"""
permissions.py — Phase B & C: Role-Based Access Control
=========================================================
Defines what each role can see and do.

Roles (lowest to highest):
  viewer  — read-only, assigned portfolios only
  manager — read + reports + email, all portfolios
  admin   — full access including user management and system config

Usage:
    from permissions import can_access_page, require_permission, filter_nav

    # In a page:
    require_permission("risk_settings")   # stops page if no access

    # In nav builder:
    visible_pages = filter_nav(ALL_PAGES, user_role)
"""

import streamlit as st
from typing import Optional

# ── Page permission map ────────────────────────────────────────────────────────
# Format: "page_key": ["role1", "role2", ...]
# Page keys match the nav label strings in the dashboard

PAGE_PERMISSIONS: dict = {
    # ── PORTFOLIO ──────────────────────────────────────────────────────────────
    "📈 Portfolio Summary"   : ["viewer", "manager", "admin"],
    "🏦 NSE Live Prices"     : ["viewer", "manager", "admin"],
    "🥧 Allocation Charts"   : ["viewer", "manager", "admin"],
    "💰 Dividends"           : ["viewer", "manager", "admin"],

    # ── ANALYTICS ─────────────────────────────────────────────────────────────
    "📊 Benchmark Comparison": ["viewer", "manager", "admin"],
    "📐 Risk-Adjusted Returns": ["viewer", "manager", "admin"],
    "💼 Cost & P&L Tracking" : ["viewer", "manager", "admin"],
    "📅 Performance History" : ["viewer", "manager", "admin"],
    "💱 Multi-Currency"      : ["manager", "admin"],

    # ── MANAGEMENT ────────────────────────────────────────────────────────────
    "⚠️ Risk & Rebalancing"  : ["manager", "admin"],
    "🎛️ Risk Settings"       : ["admin"],
    "🎯 Target Allocation"   : ["manager", "admin"],
    "📋 Corporate Actions"   : ["admin"],
    "🔄 Transactions"        : ["viewer", "manager", "admin"],

    # ── SYSTEM ────────────────────────────────────────────────────────────────
    "🔔 Alerts"              : ["manager", "admin"],
    "🧾 Tax Reporting"       : ["manager", "admin"],
    "📧 Reports & Email"     : ["manager", "admin"],
    "🔏 Audit Trail"         : ["admin"],
    "👤 User Management"     : ["admin"],
    "⚙️ My Account"          : ["viewer", "manager", "admin"],
}

# ── Action permissions (for fine-grained controls within pages) ───────────────
ACTION_PERMISSIONS: dict = {
    "generate_pdf"          : ["manager", "admin"],
    "send_email"            : ["manager", "admin"],
    "edit_risk_settings"    : ["admin"],
    "edit_target_allocation": ["manager", "admin"],
    "record_corp_action"    : ["admin"],
    "delete_corp_action"    : ["admin"],
    "manage_users"          : ["admin"],
    "view_audit_trail"      : ["admin"],
    "run_script"            : ["admin"],
    "edit_fx_settings"      : ["admin"],
    "configure_alerts"      : ["admin"],
    "add_manual_note"       : ["manager", "admin"],
    "export_data"           : ["manager", "admin"],
    "view_tax_report"       : ["manager", "admin"],
    "change_own_password"   : ["viewer", "manager", "admin"],
    "enable_mfa"            : ["viewer", "manager", "admin"],
}

# ── Nav group structure (matches dashboard sidebar) ───────────────────────────
NAV_GROUPS = [
    ("PORTFOLIO", [
        "📈 Portfolio Summary",
        "🏦 NSE Live Prices",
        "🥧 Allocation Charts",
        "💰 Dividends",
    ]),
    ("ANALYTICS", [
        "📊 Benchmark Comparison",
        "📐 Risk-Adjusted Returns",
        "💼 Cost & P&L Tracking",
        "📅 Performance History",
        "💱 Multi-Currency",
    ]),
    ("MANAGEMENT", [
        "⚠️ Risk & Rebalancing",
        "🎛️ Risk Settings",
        "🎯 Target Allocation",
        "📋 Corporate Actions",
        "🔄 Transactions",
    ]),
    ("SYSTEM", [
        "🔔 Alerts",
        "🧾 Tax Reporting",
        "📧 Reports & Email",
        "🔏 Audit Trail",
        "👤 User Management",
        "⚙️ My Account",
    ]),
]


# ── Core permission checks ─────────────────────────────────────────────────────

def can_access_page(page: str, role: Optional[str]) -> bool:
    """Return True if the given role can access the page."""
    if not role:
        return False
    allowed = PAGE_PERMISSIONS.get(page, [])
    return role in allowed


def can_perform(action: str, role: Optional[str]) -> bool:
    """Return True if the given role can perform the action."""
    if not role:
        return False
    allowed = ACTION_PERMISSIONS.get(action, [])
    return role in allowed


def require_page_permission(page: str) -> None:
    """
    Call at the top of every page renderer.
    Stops rendering and shows error if user lacks permission.
    """
    role = st.session_state.get("user_role")
    if not can_access_page(page, role):
        st.error(
            f"⛔ You do not have permission to access **{page}**. "
            f"Contact your administrator if you need access."
        )
        st.stop()


def require_action_permission(action: str, silent: bool = False) -> bool:
    """
    Check action permission. If silent=False and no permission, show error and stop.
    If silent=True, just return False without stopping.
    """
    role = st.session_state.get("user_role")
    if can_perform(action, role):
        return True
    if not silent:
        st.error(
            f"⛔ You do not have permission to perform this action. "
            f"Required role: **{_min_role_for_action(action)}** or higher."
        )
        st.stop()
    return False


def _min_role_for_action(action: str) -> str:
    """Return the minimum role required for an action."""
    allowed = ACTION_PERMISSIONS.get(action, [])
    for role in ["viewer", "manager", "admin"]:
        if role in allowed:
            return role
    return "admin"


def filter_nav(role: Optional[str]) -> list:
    """
    Return nav groups filtered to only pages the role can access.
    Groups with no accessible pages are omitted entirely.
    """
    filtered = []
    for group_label, pages in NAV_GROUPS:
        visible = [p for p in pages if can_access_page(p, role)]
        if visible:
            filtered.append((group_label, visible))
    return filtered


def role_badge(role: Optional[str]) -> str:
    """Return an HTML badge string for the role."""
    colours = {
        "admin"  : ("#3B4436", "#F1E9CB"),
        "manager": ("#2d6a4f", "#d8f3dc"),
        "viewer" : ("#4a4e69", "#c9d6f0"),
    }
    bg, fg = colours.get(role or "viewer", ("#888", "#fff"))
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 10px;'
        f'border-radius:12px;font-size:0.75rem;font-weight:600;">'
        f'{(role or "viewer").upper()}</span>'
    )


def can_access_portfolio(portfolio_filename: str, user: dict) -> bool:
    """
    Check if a user can access a specific portfolio file.
    Admins and managers can access all portfolios.
    Viewers can only access their assigned_portfolios list.
    """
    role = user.get("role", "viewer")
    if role in ("admin", "manager"):
        return True
    assigned = user.get("assigned_portfolios", [])
    # Match on basename without extension
    base = portfolio_filename.replace("_Dashboard_Output.xlsx", "").replace(".xlsx", "")
    return any(
        base.lower() in str(p).lower() or str(p).lower() in base.lower()
        for p in assigned
    )


def get_accessible_portfolios(all_files: list, user: dict) -> list:
    """Filter a list of portfolio filenames to only those the user can access."""
    return [f for f in all_files if can_access_portfolio(f, user)]
