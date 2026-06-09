"""
login_page.py — Sign In UI for PRO_LAW Portfolio Tracker
Accounts are created by admins only. Forgot password notifies admin.
Persistent session via st.session_state (survives refresh).
"""

import os
import auth as _auth
import streamlit as st
st.write(st.secrets)

SESSION_TIMEOUT_M = _auth.SESSION_TIMEOUT_M

LOGIN_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMainBlockContainer"] {
    font-family: 'Inter', sans-serif;
    background: linear-gradient(135deg,#2d3a2e 0%,#1e2720 50%,#3B4436 100%) !important;
    min-height: 100vh;
}

.auth-card{
    background:rgba(255,255,255,0.08);
    backdrop-filter:blur(24px);
    -webkit-backdrop-filter:blur(24px);

    border:1px solid rgba(255,255,255,0.12);

    border-radius:28px;

    padding:3rem 2.8rem;

    box-shadow:
        0 15px 50px rgba(0,0,0,0.45),
        0 25px 80px rgba(0,0,0,0.25),
        0 0 40px rgba(255,255,255,0.03) inset;

    margin:0 auto;
}
.auth-logo  { text-align:center; margin-bottom:1.3rem; }
.auth-title {
    font-size:1.5rem; font-weight:700; color:#F1E9CB;
    text-align:center; margin-bottom:0.25rem; letter-spacing:-0.02em;
}
.auth-subtitle {
    font-size:0.82rem; color:rgba(241,233,203,0.52);
    text-align:center; margin-bottom:1.6rem;
}
.auth-footer {
    text-align:center; font-size:0.71rem;
    color:rgba(241,233,203,0.35); margin-top:1.5rem; line-height:1.75;
}
.session-notice {
    background:rgba(217,119,6,0.18); border-left:3px solid #d97706;
    border-radius:8px; padding:0.62rem 0.9rem; margin-bottom:1rem;
    font-size:0.82rem; color:#fde68a;
}
.success-notice {
    background:rgba(22,163,74,0.18); border-left:3px solid #22c55e;
    border-radius:8px; padding:0.7rem 0.9rem; margin-bottom:0.8rem;
    font-size:0.83rem; color:#86efac; line-height:1.55;
}
.info-notice {
    background:rgba(59,68,54,0.35); border-left:3px solid rgba(241,233,203,0.35);
    border-radius:8px; padding:0.7rem 0.9rem; margin-bottom:0.8rem;
    font-size:0.82rem; color:rgba(241,233,203,0.70); line-height:1.55;
}

/* Inputs */
.stTextInput input{
    background:rgba(255,255,255,0.07) !important;
    border:1px solid rgba(255,255,255,0.15) !important;
    border-radius:14px !important;

    color:#F1E9CB !important;

    height:52px !important;

    backdrop-filter:blur(10px);
}
.stTextInput input::placeholder { color:rgba(241,233,203,0.28) !important; }
.stTextInput label {
    color:rgba(241,233,203,0.70) !important; font-size:0.81rem !important;
}
.stTextInput input:focus {
    border-color:rgba(241,233,203,0.42) !important;
    box-shadow:0 0 0 2px rgba(241,233,203,0.09) !important;
    outline:none !important;
}

/* Buttons */
.stButton > button{
    width:100%;
    height:52px;

    background:rgba(59,68,54,0.85) !important;

    border:1px solid rgba(255,255,255,0.15) !important;

    border-radius:50% !important;

    color:#F1E9CB !important;

    font-weight:600;

    transition:0.3s;
}

.stButton > button:hover{
    background:#4a5a44 !important;

    transform:translateY(-2px);

    box-shadow:
        0 8px 25px rgba(0,0,0,0.35);
}
/* Ghost/link-style button */
button[kind="secondary"] {
    background:transparent !important;
    color:rgba(241,233,203,0.55) !important;
    border:none !important; font-size:0.78rem !important;
    font-weight:400 !important; padding:0 !important;
    text-decoration:underline; width:auto !important;
}
button[kind="secondary"]:hover {
    color:#F1E9CB !important; background:transparent !important;
}
.forgot-link{
    text-align:center;
    margin-top:12px;
}
</style>
"""


def _logo(w=175):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Logo.png")
    if not os.path.exists(path):
        return '<div style="font-size:1.55rem;font-weight:800;color:#F1E9CB;">PRO_LAW</div>'
    import base64
    with open(path,"rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return (f'<img src="data:image/png;base64,{b64}" '
            f'style="max-width:{w}px;max-height:52px;object-fit:contain;'
            f'filter:brightness(1.8) contrast(1.05);" />')


def _footer():
    return ('<div class="auth-footer">PRO_LAW Portfolio Tracking System'
            ' &nbsp;·&nbsp; © 2026 PRO_LAW<br>'
            '<a href="mailto:lawrenceowini17@gmail.com" '
            'style="color:rgba(241,233,203,0.40);text-decoration:none;">'
            'lawrenceowini17@gmail.com</a></div>')


def _qp(k):
    try:
        v = st.query_params.get(k)
    except Exception:
        v = (st.experimental_get_query_params() or {}).get(k)
    return (v[0] if isinstance(v,list) else v) or ""


def _clear_qp():
    try:
        st.query_params.clear()
    except Exception:
        try: st.experimental_set_query_params()
        except Exception: pass


def _log(event, details):
    try:
        import audit_trail as _a
        _a.append_entry(event, details)
    except Exception:
        pass


def _inject_ac(fields: dict):
    """Inject autocomplete attributes via JS."""
    parts = []
    for label, ac in fields.items():
        parts.append(f"""
        (function(){{
            var ls=document.querySelectorAll('label');
            for(var i=0;i<ls.length;i++){{
                if(ls[i].innerText.trim()==='{label}'){{
                    var box=ls[i].closest('[data-testid="stTextInput"]');
                    if(box){{var inp=box.querySelector('input');
                        if(inp){{inp.setAttribute('autocomplete','{ac}');
                                 inp.setAttribute('name','{ac}');}}}}
                }}
            }}
        }})();""")
    st.markdown(f"<script>{''.join(parts)}</script>", unsafe_allow_html=True)


def _col():
    _, c, _ = st.columns([1,2,1])
    return c


# ── Bootstrap ──────────────────────────────────────────────────────────────────

def _render_bootstrap():
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    with _col():
        st.markdown(
            f'''
                <div class="auth-card">
                <div class="auth-logo">{_logo()}</div>
                <div class="auth-title">Sign In</div>
                <div class="auth-subtitle">
                    PRO_LAW Portfolio Tracking System
                </div>
            ''',
            unsafe_allow_html=True
        )
        with st.form("bootstrap_form"):
            name  = st.text_input("Full Name",        placeholder="Lawrence Owini")
            email = st.text_input("Email",            placeholder="admin@example.com")
            pwd   = st.text_input("Password",         type="password")
            pwd2  = st.text_input("Confirm Password", type="password")
            if pwd:
                score, issues = _auth.check_password_strength(pwd)
                colours = ["#ef4444","#ef4444","#f59e0b","#22c55e","#22c55e"]
                labels  = ["Very weak","Weak","Fair","Strong","Very strong"]
                widths  = [15,35,55,80,100]
                c,w,l   = colours[score],widths[score],labels[score]
                st.markdown(
                    f'<div style="height:4px;border-radius:2px;background:rgba(241,233,203,0.12);margin:4px 0 2px;">'
                    f'<div style="height:4px;border-radius:2px;background:{c};width:{w}%;"></div></div>'
                    f'<div style="font-size:0.69rem;color:{c};margin-bottom:5px;">{l}</div>',
                    unsafe_allow_html=True,
                )
                for i in issues: st.caption(f"• {i}")
            ok = st.form_submit_button("Create Administrator Account")
        if ok:
            if not email or not pwd:
                st.error("Email and password are required.")
            elif pwd != pwd2:
                st.error("Passwords do not match.")
            else:
                s, msg = _auth.bootstrap_admin(email, pwd, name or "Administrator")
                if s:
                    st.success(f"✓ {msg} You can now sign in.")
                    st.rerun()
                else:
                    st.error(msg)
        st.markdown("</div>", unsafe_allow_html=True)
        _inject_ac({"Email":"email","Password":"new-password","Confirm Password":"new-password"})


# ── MFA ───────────────────────────────────────────────────────────────────────

def _render_mfa():
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    with _col():
        st.markdown(
            f'<div class="auth-card">'
            f'<div class="auth-logo">{_logo()}</div>'
            f'<div class="auth-title">Two-Factor Auth</div>'
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
            _auth.logout_user(); st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


# ── Forgot password (notify admin) ────────────────────────────────────────────

def _render_forgot():
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    with _col():
        st.markdown(
            f'<div class="auth-card">'
            f'<div class="auth-logo">{_logo()}</div>'
            f'<div class="auth-title">Forgot Password</div>'
            f'<div class="auth-subtitle">Enter your email and the administrator will be notified to verify your identity and reset your access.</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="info-notice">'
            '🔐 For security, password resets are handled by the administrator. '
            'They will verify your identity before resetting your password.'
            '</div>',
            unsafe_allow_html=True,
        )
        with st.form("forgot_form"):
            email = st.text_input("Your Email Address", placeholder="you@example.com")
            ok    = st.form_submit_button("Notify Administrator")
        if ok:
            if not email:
                st.error("Please enter your email address.")
            else:
                with st.spinner("Sending notification…"):
                    s, msg = _auth.forgot_password_notify_admin(email.strip().lower())
                if s:
                    st.markdown(
                        f'<div class="success-notice">✓ {msg}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.error(msg)
                    st.info(
                        "If email isn't configured, contact your administrator directly at "
                        "lawrenceowini17@gmail.com and request a password reset."
                    )
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← Back to Sign In", key="forgot_back"):
            st.session_state._auth_screen = "login"
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        _inject_ac({"Your Email Address":"email"})


# ── Invite password setup ──────────────────────────────────────────────────────

def _render_invite():
    token_hash   = _qp("token_hash") or _qp("token")
    invite_email = _qp("email")

    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    with _col():
        st.markdown(
            f'<div class="auth-card">'
            f'<div class="auth-logo">{_logo()}</div>'
            f'<div class="auth-title">Complete Your Invite</div>'
            f'<div class="auth-subtitle">Set a password to activate your PRO_LAW account.</div>',
            unsafe_allow_html=True,
        )
        if not token_hash:
            st.error("Invite link is missing its token. Ask your administrator to resend.")
            if st.button("Back to Sign In"):
                _clear_qp(); st.rerun()
            st.markdown(f'{_footer()}</div>', unsafe_allow_html=True)
            return
        with st.form("invite_form"):
            st.text_input("Email", value=invite_email, disabled=True)
            pwd  = st.text_input("New Password",      type="password")
            pwd2 = st.text_input("Confirm Password",  type="password")
            if pwd:
                score, _ = _auth.check_password_strength(pwd)
                colours  = ["#ef4444","#ef4444","#f59e0b","#22c55e","#22c55e"]
                widths   = [15,35,55,80,100]
                labels   = ["Very weak","Weak","Fair","Strong","Very strong"]
                c,w,l    = colours[score],widths[score],labels[score]
                st.markdown(
                    f'<div style="height:4px;border-radius:2px;background:rgba(241,233,203,0.12);margin:4px 0 2px;">'
                    f'<div style="height:4px;border-radius:2px;background:{c};width:{w}%;"></div></div>'
                    f'<div style="font-size:0.69rem;color:{c};margin-bottom:5px;">{l}</div>',
                    unsafe_allow_html=True,
                )
            ok = st.form_submit_button("Set Password and Sign In")
        if ok:
            if not pwd or not pwd2:
                st.error("Enter and confirm your password.")
            elif pwd != pwd2:
                st.error("Passwords do not match.")
            else:
                with st.spinner("Completing invite…"):
                    s, result = _auth.complete_supabase_invite(token_hash, pwd)
                if s:
                    _auth.login_user(result, "supabase")
                    _log("SESSION_START", {"email":result.get("email",""),"provider":"invite"})
                    _clear_qp()
                    st.success("Account activated. Signing you in…")
                    st.rerun()
                else:
                    st.error(str(result))
        st.markdown(f'{_footer()}</div>', unsafe_allow_html=True)
        _inject_ac({"New Password":"new-password","Confirm Password":"new-password"})


# ── Main sign-in form ──────────────────────────────────────────────────────────

def _render_signin(session_expired=False):
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    with _col():
        st.markdown(
            f'<div class="auth-card">'
            f'<div class="auth-logo">{_logo()}</div>'
            f'<div class="auth-title">Sign In</div>'
            f'<div class="auth-subtitle">PRO_LAW Portfolio Tracking System</div>',
            unsafe_allow_html=True,
        )

        if session_expired:
            st.markdown(
                f'<div class="session-notice">⏱ Your session expired after '
                f'{SESSION_TIMEOUT_M} minutes of inactivity. Please sign in again.</div>',
                unsafe_allow_html=True,
            )

        if st.session_state.get("login_attempts",0) >= _auth.MAX_LOGIN_ATTEMPTS:
            st.error(f"Too many failed attempts. Please wait {_auth.LOCKOUT_MINUTES} minutes.")
            st.markdown(f'{_footer()}</div>', unsafe_allow_html=True)
            return

        with st.form("login_form"):
            email    = st.text_input("Email",    placeholder="you@example.com", key="li_email")
            password = st.text_input("Password", type="password",               key="li_pwd")
            submitted = st.form_submit_button("Sign In")

        # Autocomplete for browser password manager
        _inject_ac({"Email":"email","Password":"current-password"})

        # Forgot password link (subtle, below form)
        if st.button("Forgot your password?", key="go_forgot"):
            st.session_state._auth_screen = "forgot"
            st.rerun()

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
                    st.session_state.login_attempts = (
                        st.session_state.get("login_attempts",0) + 1
                    )
                    if result == "EMAIL_NOT_CONFIRMED":
                        st.warning(
                            "Your email is not confirmed. "
                            "Check your inbox or contact your administrator."
                        )
                    else:
                        st.error(str(result))

        st.markdown(f'{_footer()}</div>', unsafe_allow_html=True)


# ── Public entry point ─────────────────────────────────────────────────────────

def render_login_gate(session_expired: bool = False) -> bool:
    """
    Called at the top of streamlit_dashboard.py before any content.
    Handles persistent sessions — if authenticated state is in session_state,
    the user stays logged in across refreshes without re-entering credentials.
    Returns True only when fully authenticated (and MFA verified if enabled).
    """
    _auth.init_session()

    supabase_ok  = bool(
        os.environ.get("SUPABASE_URL","").strip() and
        os.environ.get("SUPABASE_ANON_KEY","").strip()
    )
    admin_exists = _auth.ensure_admin_exists()

    # ── Detect special URL flows ───────────────────────────────────────────────
    qp_type    = _qp("type").lower()
    token      = _qp("token_hash") or _qp("token")
    have_token = bool(token) and not st.session_state.get("authenticated")

    if qp_type == "recovery" or (have_token and qp_type == "recovery"):
        _render_invite()   # reuse invite UI for recovery (same UX)
        st.stop(); return False

    if qp_type == "invite" or (have_token and not qp_type):
        _render_invite()
        st.stop(); return False

    # ── Already authenticated — persistent session ─────────────────────────────
    # st.session_state persists across page refreshes within the same browser tab.
    # If the user is marked authenticated and session hasn't timed out, skip login.
    if st.session_state.get("authenticated"):
        if _auth.check_session_timeout():
            # Session is valid — check MFA
            user = st.session_state.get("user", {})
            if user.get("mfa_enabled") and not st.session_state.get("mfa_verified"):
                _render_mfa()
                st.stop(); return False
            # Clear any stale screen state
            st.session_state.pop("_auth_screen", None)
            return True
        else:
            # Timed out — show login with expired notice
            session_expired = True

    # ── Routing for unauthenticated users ──────────────────────────────────────
    screen = st.session_state.get("_auth_screen", "login")

    if screen == "forgot":
        _render_forgot()
        st.stop(); return False

    # First run — no admin anywhere
    if not admin_exists and not supabase_ok:
        _render_bootstrap()
        st.stop(); return False

    # Show sign-in
    _render_signin(session_expired=session_expired)
    st.stop()
    return False
