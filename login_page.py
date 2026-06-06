"""
login_page.py — Login UI for PRO_LAW Portfolio Tracker
=======================================================
Renders the full login experience:
  - First-run admin bootstrap (no users exist yet)
  - Email + password login form
  - MFA verification step
  - Session timeout notice
  - Forgot password placeholder

Import and call render_login_page() before any dashboard content.
"""

import os
import streamlit as st

import auth as _auth
import permissions as _perm

# ── Brand colours (keep in sync with dashboard) ───────────────────────────────
DARK_OLIVE   = "#3B4436"
CREAM        = "#F1E9CB"
ACCENT       = "#7A8C6E"
TEXT_DARK    = "#2F332E"
BORDER_COLOR = "#B8AA91"


# ── CSS for login page ────────────────────────────────────────────────────────

LOGIN_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, .stApp, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', sans-serif;
    background-color: #ECEAE4 !important;
}

.login-wrapper {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 80vh;
    padding: 2rem 1rem;
}

.login-card {
    background: #ffffff;
    border: 1px solid #B8AA91;
    border-radius: 16px;
    padding: 2.5rem 2.8rem;
    width: 100%;
    max-width: 420px;
    box-shadow: 0 4px 24px rgba(59,68,54,0.10);
}

.login-logo {
    text-align: center;
    margin-bottom: 1.5rem;
}

.login-title {
    font-size: 1.5rem;
    font-weight: 700;
    color: #3B4436;
    text-align: center;
    margin-bottom: 0.3rem;
    letter-spacing: -0.02em;
}

.login-subtitle {
    font-size: 0.85rem;
    color: #7A8C6E;
    text-align: center;
    margin-bottom: 1.8rem;
}

.session-expired {
    background: #fff8e7;
    border-left: 3px solid #d97706;
    border-radius: 8px;
    padding: 0.7rem 1rem;
    margin-bottom: 1rem;
    font-size: 0.85rem;
    color: #2F332E;
}

.pwd-strength-0 { color: #dc2626; font-size: 0.78rem; }
.pwd-strength-1 { color: #dc2626; font-size: 0.78rem; }
.pwd-strength-2 { color: #d97706; font-size: 0.78rem; }
.pwd-strength-3 { color: #16a34a; font-size: 0.78rem; }
.pwd-strength-4 { color: #16a34a; font-size: 0.78rem; font-weight: 600; }

.login-footer {
    text-align: center;
    font-size: 0.72rem;
    color: #7A8C6E;
    margin-top: 1.5rem;
    line-height: 1.6;
}

.stTextInput input {
    border-radius: 8px !important;
    border-color: #B8AA91 !important;
    font-size: 0.875rem !important;
}

.stButton > button {
    width: 100%;
    background: #3B4436 !important;
    color: #F1E9CB !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    padding: 0.6rem 1rem !important;
    transition: background 0.2s !important;
}

.stButton > button:hover {
    background: #4a5a44 !important;
}
</style>
"""


def _logo_html() -> str:
    """Return img tag for logo if file exists."""
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Logo.png")
    if not os.path.exists(logo_path):
        return '<div style="font-size:1.8rem;font-weight:800;color:#3B4436;letter-spacing:-0.04em;">PRO_LAW</div>'
    import base64
    with open(logo_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f'<img src="data:image/png;base64,{b64}" style="max-width:200px;max-height:60px;object-fit:contain;" />'


def _strength_bar(score: int) -> str:
    colours = ["#dc2626","#dc2626","#d97706","#16a34a","#16a34a"]
    labels  = ["Very weak","Weak","Fair","Strong","Very strong"]
    widths  = [20, 35, 55, 80, 100]
    c = colours[score]
    w = widths[score]
    l = labels[score]
    return (
        f'<div style="height:4px;border-radius:2px;background:#e5e7eb;margin:4px 0 2px 0;">'
        f'<div style="height:4px;border-radius:2px;background:{c};width:{w}%;transition:width 0.3s;"></div></div>'
        f'<div style="font-size:0.72rem;color:{c};">{l}</div>'
    )


# ── First-run bootstrap ────────────────────────────────────────────────────────

def _render_bootstrap():
    """Render the first-run admin account creation screen."""
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    _, col, _ = st.columns([1, 2, 1])
    with col:
        try:
            st.markdown(f'<div class="login-logo">{_logo_html()}</div>', unsafe_allow_html=True)
        except Exception:
            st.markdown("### PRO_LAW")
        st.markdown('<div class="login-title">Welcome to PRO_LAW</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="login-subtitle">No administrator account exists yet.<br>'
            'Create yours to get started.</div>',
            unsafe_allow_html=True,
        )

        with st.form("bootstrap_form"):
            full_name = st.text_input("Full Name", placeholder="Lawrence Owini")
            email     = st.text_input("Email Address", placeholder="admin@example.com")
            pwd       = st.text_input("Password", type="password")
            pwd2      = st.text_input("Confirm Password", type="password")

            if pwd:
                score, issues = _auth.check_password_strength(pwd)
                st.markdown(_strength_bar(score), unsafe_allow_html=True)
                if issues:
                    for issue in issues:
                        st.caption(f"• {issue}")

            submitted = st.form_submit_button("Create Administrator Account")

        if submitted:
            if not email or not pwd:
                st.error("Email and password are required.")
            elif pwd != pwd2:
                st.error("Passwords do not match.")
            else:
                ok, msg = _auth.bootstrap_admin(email, pwd, full_name or "Administrator")
                if ok:
                    st.success(f"✓ {msg} You can now log in.")
                    st.rerun()
                else:
                    st.error(msg)

        st.markdown(
            '<div class="login-footer">PRO_LAW Portfolio Tracking System<br>'
            '© 2026 PRO_LAW · lawrenceowini17@gmail.com</div>',
            unsafe_allow_html=True,
        )



# ── MFA verification ───────────────────────────────────────────────────────────

def _render_mfa():
    """Render the MFA token entry step."""
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(f'<div style="text-align:center;margin-bottom:1rem;">{_logo_html()}</div>', unsafe_allow_html=True)
        st.markdown("### Two-Factor Authentication")
        st.markdown(
            "Open your authenticator app and enter the 6-digit code for "
            "**PRO_LAW Portfolio Tracker**."
        )

        with st.form("mfa_form"):
            token = st.text_input("6-digit code", max_chars=6, placeholder="123456")
            submitted = st.form_submit_button("Verify")

        if submitted:
            secret = _auth.get_mfa_secret(st.session_state.get("user_email", ""))
            if secret and _auth.verify_totp(secret, token.strip()):
                st.session_state.mfa_verified = True
                st.rerun()
            else:
                st.error("Invalid code. Please try again.")

        if st.button("Cancel / Log out", key="mfa_cancel"):
            _auth.logout_user()
            st.rerun()


# ── Main login form ────────────────────────────────────────────────────────────

def _render_login(session_expired: bool = False):
    """Render the main email + password login form."""
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    _, col, _ = st.columns([1, 2, 1])
    with col:
        try:
            st.markdown(f'<div class="login-logo">{_logo_html()}</div>', unsafe_allow_html=True)
        except Exception:
            st.markdown("### PRO_LAW")
        st.markdown('<div class="login-title">Sign In</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="login-subtitle">PRO_LAW Portfolio Tracking System</div>',
            unsafe_allow_html=True,
        )

        if session_expired:
            st.markdown(
                '<div class="session-expired">⏱ Your session expired after '
                f'{_auth.SESSION_TIMEOUT_M} minutes of inactivity. Please sign in again.</div>',
                unsafe_allow_html=True,
            )

        # Check for too many attempts in this browser session
        attempts = st.session_state.get("login_attempts", 0)
        if attempts >= _auth.MAX_LOGIN_ATTEMPTS:
            st.error(
                f"Too many failed login attempts. Please wait {_auth.LOCKOUT_MINUTES} "
                "minutes before trying again."
            )
            st.stop()

        with st.form("login_form"):
            email    = st.text_input("Email Address", placeholder="you@example.com")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In")

        if submitted:
            if not email or not password:
                st.error("Please enter your email and password.")
            else:
                with st.spinner("Verifying credentials…"):
                    try:
                        ok, result, provider = _auth.authenticate(email.strip().lower(), password)
                    except Exception as _login_ex:
                        ok     = False
                        result = f"Unexpected error: {_login_ex}"
                        provider = "error"

                if ok:
                    st.session_state.login_attempts = 0
                    _auth.login_user(result, provider)

                    # Log to audit trail
                    try:
                        import audit_trail as _audit
                        _audit.append_entry("SESSION_START", {
                            "email"   : email.strip().lower(),
                            "provider": provider,
                            "role"    : result.get("role", "viewer"),
                        })
                    except Exception:
                        pass

                    st.rerun()
                else:
                    st.session_state.login_attempts = attempts + 1
                    st.error(str(result))
                    # Show hint for Supabase users
                    if "confirm" in str(result).lower():
                        st.info(
                            "Tip: In your Supabase dashboard go to **Authentication → Users**, "
                            "find your user and click **Send confirmation email**, or disable "
                            "email confirmation under **Authentication → Settings → Email**."
                        )
                    elif "invalid" in str(result).lower() or "password" in str(result).lower():
                        with st.expander("Troubleshooting"):
                            st.markdown("""
**Common causes:**
- Email confirmation is required — check your inbox for a confirmation email from Supabase
- To skip email confirmation: Supabase dashboard → **Authentication → Settings** → disable **Enable email confirmations**
- Password must match exactly what you set in Supabase
- Make sure your `.env` has the correct `SUPABASE_URL` and `SUPABASE_ANON_KEY`
                            """)

        st.markdown(
            '<div class="login-footer">'
            'PRO_LAW Portfolio Tracking System · © 2026 PRO_LAW<br>'
            '<a href="mailto:lawrenceowini17@gmail.com" '
            'style="color:#7A8C6E;text-decoration:none;">lawrenceowini17@gmail.com</a>'
            '</div>',
            unsafe_allow_html=True,
        )



# ── Public entry point ─────────────────────────────────────────────────────────

def render_login_gate(session_expired: bool = False) -> bool:
    """
    Call this at the very top of streamlit_dashboard.py.
    Returns True if user is authenticated and MFA is verified.
    Renders the appropriate screen and calls st.stop() if not authenticated.
    """
    _auth.init_session()

    # First run — no admin exists anywhere (local or Supabase)
    _supabase_ok = _get_supabase_configured()
    _admin_exists = _auth.ensure_admin_exists()

    if not _admin_exists and not _supabase_ok:
        # Show bootstrap screen
        _render_bootstrap()
        st.stop()
        return False

    # Not authenticated — show login
    if not st.session_state.get("authenticated"):
        _render_login(session_expired=session_expired)
        st.stop()
        return False

    # Authenticated but MFA pending
    user = st.session_state.get("user", {})
    if user.get("mfa_enabled") and not st.session_state.get("mfa_verified"):
        _render_mfa()
        st.stop()
        return False

    # Fully authenticated
    return True


def _get_supabase_configured() -> bool:
    return bool(
        os.environ.get("SUPABASE_URL", "").strip() and
        os.environ.get("SUPABASE_ANON_KEY", "").strip()
    )
