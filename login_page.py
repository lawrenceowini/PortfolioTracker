"""
login_page.py — Login, Signup & Invite UI for PRO_LAW Portfolio Tracker
"""

import os
import streamlit as st
import auth as _auth

DARK_OLIVE   = "#3B4436"
CREAM        = "#F1E9CB"
ACCENT       = "#7A8C6E"
TEXT_DARK    = "#2F332E"
BORDER_COLOR = "#B8AA91"

LOGIN_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, .stApp, [data-testid="stAppViewContainer"],
[data-testid="stMainBlockContainer"] {
    font-family: 'Inter', sans-serif;
    background: linear-gradient(135deg, #2d3a2e 0%, #1e2720 50%, #3B4436 100%) !important;
    min-height: 100vh;
}

.auth-card {
    background: rgba(59, 68, 54, 0.18);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid rgba(241, 233, 203, 0.18);
    border-radius: 20px;
    padding: 2.8rem 2.6rem 2.2rem 2.6rem;
    box-shadow: 0 8px 40px rgba(0,0,0,0.38), 0 1px 0 rgba(241,233,203,0.08) inset;
    margin: 0 auto;
}

.auth-logo { text-align: center; margin-bottom: 1.4rem; }

.auth-title {
    font-size: 1.55rem;
    font-weight: 700;
    color: #F1E9CB;
    text-align: center;
    margin-bottom: 0.25rem;
    letter-spacing: -0.02em;
}

.auth-subtitle {
    font-size: 0.83rem;
    color: rgba(241,233,203,0.60);
    text-align: center;
    margin-bottom: 1.6rem;
}

.auth-divider {
    text-align: center;
    color: rgba(241,233,203,0.40);
    font-size: 0.78rem;
    margin: 1rem 0;
    position: relative;
}

.auth-footer {
    text-align: center;
    font-size: 0.72rem;
    color: rgba(241,233,203,0.45);
    margin-top: 1.4rem;
    line-height: 1.7;
}

.session-notice {
    background: rgba(217,119,6,0.20);
    border-left: 3px solid #d97706;
    border-radius: 8px;
    padding: 0.65rem 0.9rem;
    margin-bottom: 1rem;
    font-size: 0.83rem;
    color: #fde68a;
}

.strength-bar-bg {
    height: 4px; border-radius: 2px;
    background: rgba(241,233,203,0.15);
    margin: 4px 0 2px 0;
}

/* Override Streamlit inputs for dark background */
.stTextInput input {
    background: rgba(255,255,255,0.09) !important;
    border: 1px solid rgba(241,233,203,0.22) !important;
    border-radius: 9px !important;
    color: #F1E9CB !important;
    font-size: 0.875rem !important;
}
.stTextInput input::placeholder { color: rgba(241,233,203,0.35) !important; }
.stTextInput label { color: rgba(241,233,203,0.75) !important; font-size:0.82rem !important; }

.stButton > button {
    width: 100%;
    background: #3B4436 !important;
    color: #F1E9CB !important;
    border: 1px solid rgba(241,233,203,0.25) !important;
    border-radius: 9px !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    padding: 0.58rem 1rem !important;
    transition: all 0.2s !important;
}
.stButton > button:hover {
    background: #4a5a44 !important;
    border-color: rgba(241,233,203,0.40) !important;
}

/* Tab switcher */
.stTabs [data-baseweb="tab-list"] {
    background: rgba(255,255,255,0.06) !important;
    border-radius: 10px !important;
    gap: 4px;
    padding: 4px;
}
.stTabs [data-baseweb="tab"] {
    color: rgba(241,233,203,0.60) !important;
    border-radius: 7px !important;
    font-size: 0.85rem !important;
}
.stTabs [aria-selected="true"] {
    background: #3B4436 !important;
    color: #F1E9CB !important;
}
</style>
"""


def _logo_html(max_width: int = 180) -> str:
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Logo.png")
    if not os.path.exists(logo_path):
        return f'<div style="font-size:1.6rem;font-weight:800;color:#F1E9CB;letter-spacing:-0.04em;">PRO_LAW</div>'
    import base64
    with open(logo_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return (
        f'<img src="data:image/png;base64,{b64}" '
        f'style="max-width:{max_width}px;max-height:55px;object-fit:contain;'
        f'filter:brightness(1.8) contrast(1.1);" />'
    )


def _strength_bar(score: int) -> str:
    colours = ["#ef4444","#ef4444","#f59e0b","#22c55e","#22c55e"]
    labels  = ["Very weak","Weak","Fair","Strong","Very strong"]
    widths  = [15, 35, 55, 80, 100]
    c, w, l = colours[score], widths[score], labels[score]
    return (
        f'<div class="strength-bar-bg">'
        f'<div style="height:4px;border-radius:2px;background:{c};width:{w}%;transition:width 0.3s;"></div></div>'
        f'<div style="font-size:0.70rem;color:{c};margin-bottom:6px;">{l}</div>'
    )


def _card_open() -> str:
    return '<div class="auth-card">'


def _card_close() -> str:
    return '</div>'


def _footer() -> str:
    return (
        '<div class="auth-footer">'
        'PRO_LAW Portfolio Tracking System &nbsp;·&nbsp; © 2026 PRO_LAW<br>'
        '<a href="mailto:lawrenceowini17@gmail.com" '
        'style="color:rgba(241,233,203,0.50);text-decoration:none;">'
        'lawrenceowini17@gmail.com</a>'
        '</div>'
    )


# ── Query param helpers ────────────────────────────────────────────────────────

def _qp(name: str):
    try:
        v = st.query_params.get(name)
    except Exception:
        v = (st.experimental_get_query_params() or {}).get(name)
    return (v[0] if isinstance(v, list) else v) or ""


def _clear_qp():
    try:
        st.query_params.clear()
    except Exception:
        try: st.experimental_set_query_params()
        except Exception: pass


# ── Audit helper ───────────────────────────────────────────────────────────────

def _log(event: str, details: dict):
    try:
        import audit_trail as _audit
        _audit.append_entry(event, details)
    except Exception:
        pass


# ── Bootstrap screen ───────────────────────────────────────────────────────────

def _render_bootstrap():
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            f'{_card_open()}'
            f'<div class="auth-logo">{_logo_html()}</div>'
            f'<div class="auth-title">Welcome to PRO_LAW</div>'
            f'<div class="auth-subtitle">Create your administrator account to get started.</div>',
            unsafe_allow_html=True,
        )
        with st.form("bootstrap_form"):
            name  = st.text_input("Full Name", placeholder="Lawrence Owini")
            email = st.text_input("Email", placeholder="admin@example.com")
            pwd   = st.text_input("Password", type="password")
            pwd2  = st.text_input("Confirm Password", type="password")
            if pwd:
                score, issues = _auth.check_password_strength(pwd)
                st.markdown(_strength_bar(score), unsafe_allow_html=True)
                for issue in issues:
                    st.caption(f"• {issue}")
            ok = st.form_submit_button("Create Administrator Account")
        if ok:
            if not email or not pwd:
                st.error("Email and password are required.")
            elif pwd != pwd2:
                st.error("Passwords do not match.")
            else:
                success, msg = _auth.bootstrap_admin(email, pwd, name or "Administrator")
                if success:
                    st.success(f"✓ {msg} You can now sign in.")
                    st.rerun()
                else:
                    st.error(msg)
        st.markdown(f'{_footer()}{_card_close()}', unsafe_allow_html=True)


# ── MFA screen ────────────────────────────────────────────────────────────────

def _render_mfa():
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            f'{_card_open()}'
            f'<div class="auth-logo">{_logo_html()}</div>'
            f'<div class="auth-title">Two-Factor Authentication</div>'
            f'<div class="auth-subtitle">Enter the 6-digit code from your authenticator app.</div>',
            unsafe_allow_html=True,
        )
        with st.form("mfa_form"):
            token = st.text_input("6-digit code", max_chars=6, placeholder="123456")
            ok    = st.form_submit_button("Verify")
        if ok:
            secret = _auth.get_mfa_secret(st.session_state.get("user_email",""))
            if secret and _auth.verify_totp(secret, token.strip()):
                st.session_state.mfa_verified = True
                st.rerun()
            else:
                st.error("Invalid code. Please try again.")
        if st.button("Cancel", key="mfa_cancel"):
            _auth.logout_user()
            st.rerun()
        st.markdown(f'{_footer()}{_card_close()}', unsafe_allow_html=True)


# ── Invite password setup ──────────────────────────────────────────────────────

def _render_invite():
    token_hash  = _qp("token_hash") or _qp("token")
    invite_email = _qp("email")

    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            f'{_card_open()}'
            f'<div class="auth-logo">{_logo_html()}</div>'
            f'<div class="auth-title">Complete Your Invite</div>'
            f'<div class="auth-subtitle">Set a password to activate your PRO_LAW account.</div>',
            unsafe_allow_html=True,
        )
        if not token_hash:
            st.error("Invite link is missing its token. Ask an admin to resend it.")
            if st.button("Back to Sign In"):
                _clear_qp()
                st.rerun()
            st.markdown(f'{_footer()}{_card_close()}', unsafe_allow_html=True)
            return

        with st.form("invite_form"):
            # Auto-fill email from query params but make it read-only visually
            st.text_input("Email", value=invite_email, disabled=True)
            pwd  = st.text_input("New Password", type="password")
            pwd2 = st.text_input("Confirm Password", type="password")
            if pwd:
                score, issues = _auth.check_password_strength(pwd)
                st.markdown(_strength_bar(score), unsafe_allow_html=True)
                for issue in issues:
                    st.caption(f"• {issue}")
            ok = st.form_submit_button("Set Password and Sign In")

        if ok:
            if not pwd or not pwd2:
                st.error("Please enter and confirm your password.")
            elif pwd != pwd2:
                st.error("Passwords do not match.")
            else:
                with st.spinner("Completing invite…"):
                    success, result = _auth.complete_supabase_invite(token_hash, pwd)
                if success:
                    _auth.login_user(result, "supabase")
                    _log("SESSION_START", {"email": result.get("email",""), "provider":"supabase_invite"})
                    _clear_qp()
                    st.success("Account activated. Signing you in…")
                    st.rerun()
                else:
                    st.error(str(result))
        st.markdown(f'{_footer()}{_card_close()}', unsafe_allow_html=True)


# ── Main login + signup form ───────────────────────────────────────────────────

def _render_login_signup(session_expired: bool = False):
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            f'{_card_open()}'
            f'<div class="auth-logo">{_logo_html()}</div>'
            f'<div class="auth-title">PRO_LAW</div>'
            f'<div class="auth-subtitle">Portfolio Tracking System</div>',
            unsafe_allow_html=True,
        )

        if session_expired:
            st.markdown(
                f'<div class="session-notice">⏱ Session expired after '
                f'{_auth.SESSION_TIMEOUT_M} minutes. Please sign in again.</div>',
                unsafe_allow_html=True,
            )

        # Rate limit guard
        if st.session_state.get("login_attempts", 0) >= _auth.MAX_LOGIN_ATTEMPTS:
            st.error(f"Too many failed attempts. Please wait {_auth.LOCKOUT_MINUTES} minutes.")
            st.markdown(f'{_footer()}{_card_close()}', unsafe_allow_html=True)
            return

        tab_in, tab_up = st.tabs(["Sign In", "Create Account"])

        # ── Sign In tab ────────────────────────────────────────────────────────
        with tab_in:
            with st.form("login_form"):
                email    = st.text_input("Email", placeholder="you@example.com", key="li_email")
                password = st.text_input("Password", type="password", key="li_pwd")
                submitted = st.form_submit_button("Sign In")

            if submitted:
                if not email or not password:
                    st.error("Enter your email and password.")
                else:
                    with st.spinner("Verifying…"):
                        try:
                            ok, result, provider = _auth.authenticate(
                                email.strip().lower(), password
                            )
                        except Exception as ex:
                            ok, result, provider = False, f"Unexpected error: {ex}", "error"

                    if ok:
                        st.session_state.login_attempts = 0
                        _auth.login_user(result, provider)
                        _log("SESSION_START", {
                            "email"   : email.strip().lower(),
                            "provider": provider,
                            "role"    : result.get("role","viewer"),
                        })
                        st.rerun()
                    else:
                        attempts = st.session_state.get("login_attempts", 0) + 1
                        st.session_state.login_attempts = attempts

                        if result == "EMAIL_NOT_CONFIRMED":
                            st.warning(
                                "Your email address has not been confirmed yet. "
                                "Check your inbox for a confirmation email from Supabase, "
                                "or ask your admin to disable email confirmation in "
                                "Supabase → Authentication → Settings."
                            )
                        else:
                            st.error(str(result))
                            with st.expander("Troubleshooting"):
                                st.markdown("""
- Make sure you are using the **exact email and password** you registered with
- If you signed up via invite, use the password you set on the invite page
- To skip email confirmation: Supabase → **Authentication → Settings** → disable **Enable email confirmations**
- Check your `.env` has the correct `SUPABASE_URL` and `SUPABASE_ANON_KEY`
                                """)

        # ── Sign Up tab ────────────────────────────────────────────────────────
        with tab_up:
            st.markdown(
                '<div style="font-size:0.78rem;color:rgba(241,233,203,0.55);'
                'margin-bottom:0.8rem;text-align:center;">'
                'New accounts have <strong style="color:rgba(241,233,203,0.75);">Viewer</strong> '
                'access by default. An admin can change your role after sign-up.</div>',
                unsafe_allow_html=True,
            )
            with st.form("signup_form"):
                su_name  = st.text_input("Full Name", placeholder="Your Name", key="su_name")
                su_email = st.text_input("Email", placeholder="you@example.com", key="su_email")
                su_pwd   = st.text_input("Password", type="password", key="su_pwd")
                su_pwd2  = st.text_input("Confirm Password", type="password", key="su_pwd2")
                if su_pwd:
                    score, issues = _auth.check_password_strength(su_pwd)
                    st.markdown(_strength_bar(score), unsafe_allow_html=True)
                    for issue in issues:
                        st.caption(f"• {issue}")
                su_ok = st.form_submit_button("Create Account")

            if su_ok:
                if not su_email or not su_pwd:
                    st.error("Email and password are required.")
                elif su_pwd != su_pwd2:
                    st.error("Passwords do not match.")
                else:
                    score, issues = _auth.check_password_strength(su_pwd)
                    if score < 2:
                        st.error("Password too weak: " + "; ".join(issues))
                    else:
                        sb = _auth._get_supabase()
                        if sb:
                            with st.spinner("Creating account…"):
                                ok, result = _auth.signup_supabase(
                                    su_email.strip().lower(), su_pwd,
                                    su_name.strip()
                                )
                            if ok:
                                st.success(
                                    "Account created! "
                                    + ("Check your email to confirm your account, then sign in."
                                       if _email_confirmation_likely_on()
                                       else "You can now sign in.")
                                )
                                _log("CONFIG_CHANGE", {
                                    "action": "user_signup",
                                    "email" : su_email.strip().lower(),
                                })
                            else:
                                st.error(str(result))
                        else:
                            # Local fallback signup (viewer only)
                            try:
                                _auth.create_local_user(
                                    su_email.strip().lower(), su_pwd,
                                    role="viewer",
                                    full_name=su_name.strip(),
                                )
                                st.success("Account created. You can now sign in.")
                            except ValueError as ve:
                                st.error(str(ve))

        st.markdown(f'{_footer()}{_card_close()}', unsafe_allow_html=True)


def _email_confirmation_likely_on() -> bool:
    """Heuristic — we can't query Supabase settings, so assume on unless .env says otherwise."""
    return os.environ.get("SUPABASE_EMAIL_CONFIRM", "true").lower() not in ("false","0","no")


# ── Public entry point ─────────────────────────────────────────────────────────

def render_login_gate(session_expired: bool = False) -> bool:
    _auth.init_session()

    supabase_ok  = bool(
        os.environ.get("SUPABASE_URL","").strip() and
        os.environ.get("SUPABASE_ANON_KEY","").strip()
    )
    admin_exists = _auth.ensure_admin_exists()

    # Invite link from Supabase email
    invite_type = _qp("type").lower()
    token_hash  = _qp("token_hash") or _qp("token")
    if invite_type == "invite" or (token_hash and not st.session_state.get("authenticated")):
        _render_invite()
        st.stop()
        return False

    # First run — no admin and no Supabase
    if not admin_exists and not supabase_ok:
        _render_bootstrap()
        st.stop()
        return False

    # Not authenticated
    if not st.session_state.get("authenticated"):
        _render_login_signup(session_expired=session_expired)
        st.stop()
        return False

    # MFA pending
    user = st.session_state.get("user", {})
    if user.get("mfa_enabled") and not st.session_state.get("mfa_verified"):
        _render_mfa()
        st.stop()
        return False

    return True
