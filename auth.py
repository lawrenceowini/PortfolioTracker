"""
auth.py — Phase A: Authentication & Session Management
=======================================================
Handles all authentication for PRO_LAW Portfolio Tracker.

Primary provider: Supabase Auth (JWT-based)
Fallback:         Local bcrypt-hashed user store (auth_users.json)
                  Use this during development before Supabase is configured.

Setup:
  1. Create a free Supabase project at https://supabase.com
  2. Copy your project URL and anon key into .env:
       SUPABASE_URL=https://xxxx.supabase.co
       SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
  3. Run the SQL in supabase_setup.sql in your Supabase SQL editor
  4. Create your first Admin user via create_local_user() or the
     Supabase dashboard

Install dependencies:
  pip install supabase bcrypt pyjwt python-dotenv --break-system-packages
"""

import os
import json
import time
import hashlib
import secrets
import datetime
from typing import Optional

import streamlit as st

# ── Optional dependencies ──────────────────────────────────────────────────────
try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Constants ──────────────────────────────────────────────────────────────────
LOCAL_USERS_FILE   = "auth_users.json"
SESSION_TIMEOUT_M  = 30        # auto-logout after 30 min inactivity
MAX_LOGIN_ATTEMPTS = 5         # per IP / session
LOCKOUT_MINUTES    = 15
JWT_ALGORITHM      = "HS256"

# Roles hierarchy (higher index = more permissions)
ROLES = ["viewer", "manager", "admin"]

# ── Supabase client ────────────────────────────────────────────────────────────

def _get_supabase() -> Optional[object]:
    """Return Supabase client if configured, else None."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not url or not key or not HAS_SUPABASE:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


# ── Local user store (fallback / development) ──────────────────────────────────

def _load_local_users() -> dict:
    if not os.path.exists(LOCAL_USERS_FILE):
        return {}
    try:
        with open(LOCAL_USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_local_users(users: dict) -> None:
    with open(LOCAL_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, default=str)


def _hash_password(password: str) -> str:
    if HAS_BCRYPT:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    # Fallback: SHA-256 with salt (weaker — install bcrypt in production)
    salt = secrets.token_hex(16)
    h    = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"sha256${salt}${h}"


def _verify_password(password: str, hashed: str) -> bool:
    if HAS_BCRYPT and not hashed.startswith("sha256$"):
        try:
            return bcrypt.checkpw(password.encode(), hashed.encode())
        except Exception:
            return False
    # SHA-256 fallback
    if hashed.startswith("sha256$"):
        parts = hashed.split("$")
        if len(parts) != 3:
            return False
        _, salt, stored_hash = parts
        return hashlib.sha256((salt + password).encode()).hexdigest() == stored_hash
    return False


def create_local_user(
    email: str,
    password: str,
    role: str = "viewer",
    full_name: str = "",
    assigned_portfolios: Optional[list] = None,
) -> dict:
    """
    Create a user in the local auth store.
    Use this for the initial Admin account or development.
    """
    if role not in ROLES:
        raise ValueError(f"Role must be one of {ROLES}")

    users = _load_local_users()
    email = email.strip().lower()

    if email in users:
        raise ValueError(f"User {email} already exists")

    user = {
        "email"               : email,
        "full_name"           : full_name or email.split("@")[0].title(),
        "role"                : role,
        "password_hash"       : _hash_password(password),
        "assigned_portfolios" : assigned_portfolios or [],
        "mfa_enabled"         : False,
        "mfa_secret"          : None,
        "created_at"          : datetime.datetime.now().isoformat(),
        "last_login"          : None,
        "failed_attempts"     : 0,
        "locked_until"        : None,
        "active"              : True,
    }
    users[email] = user
    _save_local_users(users)
    return {k: v for k, v in user.items() if k != "password_hash"}


def update_local_user(email: str, **kwargs) -> bool:
    """Update user fields. Cannot update password_hash directly."""
    users = _load_local_users()
    email = email.strip().lower()
    if email not in users:
        return False
    for k, v in kwargs.items():
        if k not in ("password_hash",):
            users[email][k] = v
    _save_local_users(users)
    return True


def change_password(email: str, new_password: str) -> bool:
    users = _load_local_users()
    email = email.strip().lower()
    if email not in users:
        return False
    users[email]["password_hash"] = _hash_password(new_password)
    _save_local_users(users)
    return True


def delete_local_user(email: str) -> bool:
    users = _load_local_users()
    email = email.strip().lower()
    if email not in users:
        return False
    del users[email]
    _save_local_users(users)
    return True


def list_local_users() -> list:
    users = _load_local_users()
    return [
        {k: v for k, v in u.items() if k != "password_hash"}
        for u in users.values()
    ]


# ── Rate limiting ──────────────────────────────────────────────────────────────

def _is_locked(user: dict) -> bool:
    locked_until = user.get("locked_until")
    if not locked_until:
        return False
    try:
        unlock_time = datetime.datetime.fromisoformat(locked_until)
        return datetime.datetime.now() < unlock_time
    except Exception:
        return False


def _lock_user(email: str, users: dict) -> None:
    unlock = datetime.datetime.now() + datetime.timedelta(minutes=LOCKOUT_MINUTES)
    users[email]["locked_until"]    = unlock.isoformat()
    users[email]["failed_attempts"] = 0
    _save_local_users(users)


def _record_failed_attempt(email: str, users: dict) -> int:
    users[email]["failed_attempts"] = users[email].get("failed_attempts", 0) + 1
    attempts = users[email]["failed_attempts"]
    if attempts >= MAX_LOGIN_ATTEMPTS:
        _lock_user(email, users)
    else:
        _save_local_users(users)
    return attempts


def _clear_failed_attempts(email: str, users: dict) -> None:
    users[email]["failed_attempts"] = 0
    users[email]["locked_until"]    = None
    users[email]["last_login"]      = datetime.datetime.now().isoformat()
    _save_local_users(users)


# ── Core authentication ────────────────────────────────────────────────────────

def authenticate_local(email: str, password: str) -> tuple:
    """
    Authenticate against the local user store.
    Returns (success: bool, user_dict or error_message: str)
    """
    email = email.strip().lower()
    users = _load_local_users()

    if email not in users:
        time.sleep(0.5)   # prevent timing attacks
        return False, "Invalid email or password."

    user = users[email]

    if not user.get("active", True):
        return False, "This account has been deactivated. Contact your administrator."

    if _is_locked(user):
        unlock = datetime.datetime.fromisoformat(user["locked_until"])
        mins   = int((unlock - datetime.datetime.now()).total_seconds() / 60) + 1
        return False, f"Account temporarily locked after too many failed attempts. Try again in {mins} minute(s)."

    if not _verify_password(password, user.get("password_hash", "")):
        remaining = MAX_LOGIN_ATTEMPTS - _record_failed_attempt(email, users) - 1
        if remaining <= 0:
            return False, f"Too many failed attempts. Account locked for {LOCKOUT_MINUTES} minutes."
        return False, f"Invalid email or password. {remaining} attempt(s) remaining."

    _clear_failed_attempts(email, users)
    safe_user = {k: v for k, v in user.items() if k != "password_hash"}
    return True, safe_user


def authenticate_supabase(email: str, password: str) -> tuple:
    """
    Authenticate via Supabase Auth.
    Returns (success: bool, user_dict or error_message: str)
    """
    sb = _get_supabase()
    if not sb:
        return False, "Supabase not configured."
    try:
        # supabase-py v2 API
        response = sb.auth.sign_in_with_password({
            "email"   : email.strip().lower(),
            "password": password,
        })

        # Handle both old and new response formats
        user = getattr(response, "user", None)
        if user is None and hasattr(response, "data"):
            user = getattr(response.data, "user", None)

        if not user:
            return False, "Invalid email or password."

        user_id    = getattr(user, "id", None)
        user_email = getattr(user, "email", email)

        # Try to fetch extended profile from pro_law_users table
        role      = "viewer"
        full_name = user_email.split("@")[0].title()
        assigned_portfolios = []
        mfa_enabled = False

        try:
            profile_resp = sb.table("pro_law_users").select("*").eq(
                "user_id", str(user_id)
            ).execute()
            if profile_resp.data:
                p         = profile_resp.data[0]
                role      = p.get("role", "viewer")
                full_name = p.get("full_name", full_name)
                assigned_portfolios = p.get("assigned_portfolios", []) or []
                mfa_enabled = p.get("mfa_enabled", False)
            else:
                # Profile doesn't exist yet — create it now
                sb.table("pro_law_users").insert({
                    "user_id"             : str(user_id),
                    "email"               : user_email,
                    "full_name"           : full_name,
                    "role"                : "admin",   # first Supabase user = admin
                    "assigned_portfolios" : [],
                    "mfa_enabled"         : False,
                    "active"              : True,
                }).execute()
                role = "admin"
        except Exception as profile_err:
            # Profile table not set up yet — still allow login as admin
            print(f"Warning: could not fetch profile: {profile_err}")
            role = "admin"

        # Update last login
        try:
            sb.table("pro_law_users").update({
                "last_login": datetime.datetime.now().isoformat()
            }).eq("user_id", str(user_id)).execute()
        except Exception:
            pass

        user_data = {
            "email"               : user_email,
            "user_id"             : str(user_id),
            "full_name"           : full_name,
            "role"                : role,
            "assigned_portfolios" : assigned_portfolios,
            "mfa_enabled"         : mfa_enabled,
            "active"              : True,
        }
        return True, user_data

    except Exception as e:
        err = str(e)
        # Make error messages user-friendly
        if "Invalid login credentials" in err or "invalid_credentials" in err:
            return False, "Invalid email or password."
        if "Email not confirmed" in err:
            return False, "Please confirm your email address first. Check your inbox."
        if "Too many requests" in err:
            return False, "Too many login attempts. Please wait a moment and try again."
        return False, f"Login failed: {err}"


def authenticate(email: str, password: str) -> tuple:
    """
    Master authenticate function — tries Supabase first, falls back to local.
    Returns (success: bool, user_dict or error_message: str, provider: str)
    """
    sb = _get_supabase()
    if sb:
        ok, result = authenticate_supabase(email, password)
        return ok, result, "supabase"
    else:
        ok, result = authenticate_local(email, password)
        return ok, result, "local"


# ── Session management ─────────────────────────────────────────────────────────

def init_session() -> None:
    """Initialise session state keys."""
    defaults = {
        "authenticated"  : False,
        "user"           : None,
        "user_role"      : None,
        "user_email"     : None,
        "user_name"      : None,
        "last_activity"  : None,
        "auth_provider"  : None,
        "login_attempts" : 0,
        "mfa_verified"   : False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def login_user(user: dict, provider: str = "local") -> None:
    """Set session state after successful authentication."""
    st.session_state.authenticated = True
    st.session_state.user          = user
    st.session_state.user_role     = user.get("role", "viewer")
    st.session_state.user_email    = user.get("email", "")
    st.session_state.user_name     = user.get("full_name", user.get("email", ""))
    st.session_state.last_activity = time.time()
    st.session_state.auth_provider = provider
    st.session_state.mfa_verified  = not user.get("mfa_enabled", False)


def logout_user() -> None:
    """Clear all session state."""
    keys_to_clear = [
        "authenticated", "user", "user_role", "user_email",
        "user_name", "last_activity", "auth_provider", "mfa_verified",
        "active_page", "audit_session_started", "fx_rates",
        "alert_results", "smtp_config", "bm_nse20_current",
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]


def check_session_timeout() -> bool:
    """
    Returns True if session is valid, False if timed out.
    Updates last_activity on valid check.
    """
    if not st.session_state.get("authenticated"):
        return False
    last = st.session_state.get("last_activity")
    if not last:
        return False
    elapsed_mins = (time.time() - last) / 60
    if elapsed_mins > SESSION_TIMEOUT_M:
        logout_user()
        return False
    st.session_state.last_activity = time.time()
    return True


def is_authenticated() -> bool:
    """Single check combining session validity and timeout."""
    init_session()
    if not st.session_state.get("authenticated"):
        return False
    return check_session_timeout()


# ── MFA (TOTP) ────────────────────────────────────────────────────────────────

def setup_mfa(email: str) -> tuple:
    """
    Generate a TOTP secret for the user.
    Returns (secret: str, provisioning_uri: str)
    Requires: pip install pyotp qrcode --break-system-packages
    """
    try:
        import pyotp
        secret = pyotp.random_base32()
        totp   = pyotp.TOTP(secret)
        uri    = totp.provisioning_uri(name=email, issuer_name="PRO_LAW Portfolio Tracker")
        return secret, uri
    except ImportError:
        return None, None


def verify_totp(secret: str, token: str) -> bool:
    """Verify a 6-digit TOTP token."""
    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        return totp.verify(token, valid_window=1)
    except ImportError:
        return False


def enable_mfa(email: str, secret: str) -> bool:
    """Save MFA secret and mark MFA as enabled for a local user."""
    users = _load_local_users()
    email = email.strip().lower()
    if email not in users:
        return False
    users[email]["mfa_enabled"] = True
    users[email]["mfa_secret"]  = secret
    _save_local_users(users)
    return True


def get_mfa_secret(email: str) -> Optional[str]:
    users = _load_local_users()
    return users.get(email.strip().lower(), {}).get("mfa_secret")


# ── Password strength ──────────────────────────────────────────────────────────

def check_password_strength(password: str) -> tuple:
    """
    Returns (score: int 0-4, issues: list of strings)
    Score 4 = strong, 0 = very weak
    """
    issues = []
    score  = 0

    if len(password) >= 8:
        score += 1
    else:
        issues.append("At least 8 characters required")

    if any(c.isupper() for c in password):
        score += 1
    else:
        issues.append("Add at least one uppercase letter")

    if any(c.isdigit() for c in password):
        score += 1
    else:
        issues.append("Add at least one number")

    if any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password):
        score += 1
    else:
        issues.append("Add at least one special character")

    return score, issues


# ── Bootstrap: ensure at least one admin exists ────────────────────────────────

def ensure_admin_exists() -> bool:
    """
    Returns True if at least one admin user exists locally.
    Call this on startup to detect first-run.
    """
    users = _load_local_users()
    return any(u.get("role") == "admin" for u in users.values())


def bootstrap_admin(email: str, password: str, full_name: str = "Administrator") -> tuple:
    """
    Create the first admin user. Only works if no admin exists yet.
    Returns (success: bool, message: str)
    """
    if ensure_admin_exists():
        return False, "An administrator account already exists."
    score, issues = check_password_strength(password)
    if score < 3:
        return False, "Password too weak: " + "; ".join(issues)
    try:
        create_local_user(email, password, role="admin", full_name=full_name)
        return True, f"Administrator account created for {email}."
    except Exception as e:
        return False, str(e)
