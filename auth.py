"""
auth.py — Phase A: Authentication & Session Management
=======================================================
Handles all authentication for PRO_LAW Portfolio Tracker.
Primary provider: Supabase Auth (JWT-based)
Fallback:         Local bcrypt-hashed user store (auth_users.json)
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
    from supabase import create_client
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
SESSION_TIMEOUT_M  = 30
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES    = 15
ROLES              = ["viewer", "manager", "admin"]

# ── Supabase client (cached per session) ──────────────────────────────────────

def _get_supabase():
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not url or not key or not HAS_SUPABASE:
        return None
    try:
        return create_client(url, key)
    except Exception as e:
        print(f"Supabase client error: {e}")
        return None


# ── Profile helpers ────────────────────────────────────────────────────────────

def _get_or_create_profile(sb, user_id: str, email: str) -> dict:
    """Fetch profile from pro_law_users, create if missing."""
    _default = {
        "user_id"            : user_id,
        "email"              : email,
        "full_name"          : email.split("@")[0].title(),
        "role"               : "viewer",
        "assigned_portfolios": [],
        "mfa_enabled"        : False,
        "active"             : True,
    }
    try:
        resp = sb.table("pro_law_users").select("*").eq("user_id", user_id).execute()
        if resp.data:
            return resp.data[0]
    except Exception as e:
        print(f"Profile fetch error: {e}")
        return _default

    # Profile missing — try to create it
    # Use upsert to avoid duplicate key errors
    try:
        new_profile = dict(_default)
        upsert_resp = sb.table("pro_law_users").upsert(
            new_profile, on_conflict="user_id"
        ).execute()
        if upsert_resp.data:
            return upsert_resp.data[0]
    except Exception as e:
        print(f"Profile upsert error (likely RLS): {e}")
        # RLS is blocking the insert — return default so login still works
        # The admin should run the SQL fix below in Supabase SQL editor:
        # CREATE POLICY "Users can insert own profile"
        #   ON public.pro_law_users FOR INSERT
        #   WITH CHECK (auth.uid()::text = user_id::text);

    return _default


def _update_last_login(sb, user_id: str) -> None:
    try:
        sb.table("pro_law_users").update({
            "last_login": datetime.datetime.now().isoformat()
        }).eq("user_id", user_id).execute()
    except Exception:
        pass


def _build_user_dict(profile: dict, user_id: str, email: str) -> dict:
    return {
        "email"              : profile.get("email", email),
        "user_id"            : user_id,
        "full_name"          : profile.get("full_name", email.split("@")[0].title()),
        "role"               : profile.get("role", "viewer"),
        "assigned_portfolios": profile.get("assigned_portfolios", []) or [],
        "mfa_enabled"        : profile.get("mfa_enabled", False),
        "active"             : profile.get("active", True),
    }


# ── Supabase auth functions ────────────────────────────────────────────────────

def authenticate_supabase(email: str, password: str) -> tuple:
    """Sign in with email + password via Supabase."""
    sb = _get_supabase()
    if not sb:
        return False, "Supabase not configured."
    try:
        resp = sb.auth.sign_in_with_password({"email": email, "password": password})
        # supabase-py v2: resp.user / resp.session
        user = getattr(resp, "user", None)
        if user is None:
            # Try .data.user path (some versions)
            data = getattr(resp, "data", None)
            user = getattr(data, "user", None) if data else None
        if not user:
            return False, "Invalid email or password."

        user_id = str(getattr(user, "id", ""))
        uemail  = getattr(user, "email", email)
        profile = _get_or_create_profile(sb, user_id, uemail)

        if not profile.get("active", True):
            return False, "This account has been deactivated."

        _update_last_login(sb, user_id)
        return True, _build_user_dict(profile, user_id, uemail)

    except Exception as e:
        err = str(e)
        if "Invalid login credentials" in err or "invalid_credentials" in err:
            return False, "Invalid email or password."
        if "Email not confirmed" in err or "not confirmed" in err.lower():
            return False, "EMAIL_NOT_CONFIRMED"
        if "Too many requests" in err:
            return False, "Too many attempts. Please wait and try again."
        return False, f"Login error: {err}"


def signup_supabase(email: str, password: str, full_name: str = "") -> tuple:
    """Register a new user via Supabase Auth."""
    sb = _get_supabase()
    if not sb:
        return False, "Supabase not configured."
    try:
        resp = sb.auth.sign_up({
            "email"   : email,
            "password": password,
            "options" : {"data": {"full_name": full_name or email.split("@")[0].title()}},
        })
        user = getattr(resp, "user", None)
        if user is None:
            data = getattr(resp, "data", None)
            user = getattr(data, "user", None) if data else None
        if not user:
            return False, "Signup failed. Please try again."

        user_id = str(getattr(user, "id", ""))
        uemail  = getattr(user, "email", email)

        # Identities being empty means email already exists
        identities = getattr(user, "identities", None)
        if identities is not None and len(identities) == 0:
            return False, "An account with this email already exists."

        return True, {
            "email"    : uemail,
            "user_id"  : user_id,
            "full_name": full_name or uemail.split("@")[0].title(),
            "role"     : "viewer",
        }
    except Exception as e:
        err = str(e)
        if "already registered" in err.lower() or "already exists" in err.lower():
            return False, "An account with this email already exists."
        if "Password should" in err or "weak" in err.lower():
            return False, "Password is too weak. Use at least 6 characters."
        return False, f"Signup error: {err}"


def complete_supabase_invite(token_hash: str, password: str) -> tuple:
    """Accept a Supabase invite link and set password."""
    sb = _get_supabase()
    if not sb:
        return False, "Supabase not configured."
    try:
        resp = sb.auth.verify_otp({"token_hash": token_hash.strip(), "type": "invite"})
        user = getattr(resp, "user", None)
        if user is None:
            data = getattr(resp, "data", None)
            user = getattr(data, "user", None) if data else None
        if not user:
            return False, "Invite verification failed. Request a new invite."
        # Set password
        sb.auth.update_user({"password": password})
        user_id = str(getattr(user, "id", ""))
        uemail  = getattr(user, "email", "")
        profile = _get_or_create_profile(sb, user_id, uemail)
        _update_last_login(sb, user_id)
        return True, _build_user_dict(profile, user_id, uemail)
    except Exception as e:
        err = str(e)
        if "expired" in err.lower():
            return False, "Invite link expired. Request a new one."
        return False, f"Could not complete invite: {err}"


# ── Local auth (fallback) ──────────────────────────────────────────────────────

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
    salt = secrets.token_hex(16)
    h    = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"sha256${salt}${h}"


def _verify_password(password: str, hashed: str) -> bool:
    if HAS_BCRYPT and not hashed.startswith("sha256$"):
        try:
            return bcrypt.checkpw(password.encode(), hashed.encode())
        except Exception:
            return False
    if hashed.startswith("sha256$"):
        parts = hashed.split("$")
        if len(parts) != 3:
            return False
        _, salt, stored = parts
        return hashlib.sha256((salt + password).encode()).hexdigest() == stored
    return False


def _is_locked(user: dict) -> bool:
    lu = user.get("locked_until")
    if not lu:
        return False
    try:
        return datetime.datetime.now() < datetime.datetime.fromisoformat(lu)
    except Exception:
        return False


def authenticate_local(email: str, password: str) -> tuple:
    email = email.strip().lower()
    users = _load_local_users()
    if email not in users:
        time.sleep(0.4)
        return False, "Invalid email or password."
    user = users[email]
    if not user.get("active", True):
        return False, "Account deactivated."
    if _is_locked(user):
        unlock = datetime.datetime.fromisoformat(user["locked_until"])
        mins   = int((unlock - datetime.datetime.now()).total_seconds() / 60) + 1
        return False, f"Account locked. Try again in {mins} min."
    if not _verify_password(password, user.get("password_hash", "")):
        user["failed_attempts"] = user.get("failed_attempts", 0) + 1
        if user["failed_attempts"] >= MAX_LOGIN_ATTEMPTS:
            user["locked_until"] = (
                datetime.datetime.now() + datetime.timedelta(minutes=LOCKOUT_MINUTES)
            ).isoformat()
            user["failed_attempts"] = 0
        _save_local_users(users)
        return False, "Invalid email or password."
    user["failed_attempts"] = 0
    user["locked_until"]    = None
    user["last_login"]      = datetime.datetime.now().isoformat()
    _save_local_users(users)
    return True, {k: v for k, v in user.items() if k != "password_hash"}


def authenticate(email: str, password: str) -> tuple:
    """Try Supabase first, fall back to local."""
    sb = _get_supabase()
    if sb:
        ok, result = authenticate_supabase(email, password)
        return ok, result, "supabase"
    ok, result = authenticate_local(email, password)
    return ok, result, "local"


# ── User management (local) ────────────────────────────────────────────────────

def create_local_user(email, password, role="viewer", full_name="", assigned_portfolios=None):
    if role not in ROLES:
        raise ValueError(f"Role must be one of {ROLES}")
    users = _load_local_users()
    email = email.strip().lower()
    if email in users:
        raise ValueError(f"User {email} already exists")
    users[email] = {
        "email"              : email,
        "full_name"          : full_name or email.split("@")[0].title(),
        "role"               : role,
        "password_hash"      : _hash_password(password),
        "assigned_portfolios": assigned_portfolios or [],
        "mfa_enabled"        : False,
        "mfa_secret"         : None,
        "created_at"         : datetime.datetime.now().isoformat(),
        "last_login"         : None,
        "failed_attempts"    : 0,
        "locked_until"       : None,
        "active"             : True,
    }
    _save_local_users(users)
    return {k: v for k, v in users[email].items() if k != "password_hash"}


def update_local_user(email: str, **kwargs) -> bool:
    users = _load_local_users()
    email = email.strip().lower()
    if email not in users:
        return False
    for k, v in kwargs.items():
        if k != "password_hash":
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
    return [{k: v for k, v in u.items() if k != "password_hash"} for u in users.values()]


def ensure_admin_exists() -> bool:
    users = _load_local_users()
    return any(u.get("role") == "admin" for u in users.values())


def bootstrap_admin(email: str, password: str, full_name: str = "Administrator") -> tuple:
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


# ── Session management ─────────────────────────────────────────────────────────

def init_session() -> None:
    defaults = {
        "authenticated" : False,
        "user"          : None,
        "user_role"     : None,
        "user_email"    : None,
        "user_name"     : None,
        "last_activity" : None,
        "auth_provider" : None,
        "login_attempts": 0,
        "mfa_verified"  : False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def login_user(user: dict, provider: str = "local") -> None:
    st.session_state.authenticated = True
    st.session_state.user          = user
    st.session_state.user_role     = user.get("role", "viewer")
    st.session_state.user_email    = user.get("email", "")
    st.session_state.user_name     = user.get("full_name", user.get("email", ""))
    st.session_state.last_activity = time.time()
    st.session_state.auth_provider = provider
    st.session_state.mfa_verified  = not user.get("mfa_enabled", False)


def logout_user() -> None:
    for key in [
        "authenticated","user","user_role","user_email","user_name",
        "last_activity","auth_provider","mfa_verified","active_page",
        "audit_session_started","fx_rates","alert_results","smtp_config",
        "bm_nse20_current",
    ]:
        if key in st.session_state:
            del st.session_state[key]


def check_session_timeout() -> bool:
    if not st.session_state.get("authenticated"):
        return False
    last = st.session_state.get("last_activity")
    if not last:
        return False
    if (time.time() - last) / 60 > SESSION_TIMEOUT_M:
        logout_user()
        return False
    st.session_state.last_activity = time.time()
    return True


def is_authenticated() -> bool:
    init_session()
    return st.session_state.get("authenticated") and check_session_timeout()


# ── MFA ───────────────────────────────────────────────────────────────────────

def setup_mfa(email: str) -> tuple:
    try:
        import pyotp
        secret = pyotp.random_base32()
        uri    = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="PRO_LAW Portfolio Tracker")
        return secret, uri
    except ImportError:
        return None, None


def verify_totp(secret: str, token: str) -> bool:
    try:
        import pyotp
        return pyotp.TOTP(secret).verify(token, valid_window=1)
    except ImportError:
        return False


def enable_mfa(email: str, secret: str) -> bool:
    users = _load_local_users()
    email = email.strip().lower()
    if email not in users:
        return False
    users[email]["mfa_enabled"] = True
    users[email]["mfa_secret"]  = secret
    _save_local_users(users)
    return True


def get_mfa_secret(email: str) -> Optional[str]:
    return _load_local_users().get(email.strip().lower(), {}).get("mfa_secret")


# ── Password strength ──────────────────────────────────────────────────────────

def check_password_strength(password: str) -> tuple:
    issues, score = [], 0
    if len(password) >= 8: score += 1
    else: issues.append("At least 8 characters required")
    if any(c.isupper() for c in password): score += 1
    else: issues.append("Add at least one uppercase letter")
    if any(c.isdigit() for c in password): score += 1
    else: issues.append("Add at least one number")
    if any(c in "!@#$%^&*()_+-=[]{}|;:\',./<>?" for c in password): score += 1
    else: issues.append("Add at least one special character")
    return score, issues
