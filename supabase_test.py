"""
supabase_test.py — Run this to verify your Supabase connection
Usage: python supabase_test.py
"""
import os
from dotenv import load_dotenv
load_dotenv()
import streamlit as st
SUPABASE_URL=st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY=st.secrets["SUPABASE_ANON_KEY"]


URL = os.environ.get("SUPABASE_URL","").strip()
KEY = os.environ.get("SUPABASE_ANON_KEY","").strip()

print(f"URL: {URL}")
print(f"KEY: {KEY[:30]}...{KEY[-10:]}")
print()

if not URL or not KEY:
    print("ERROR: Missing SUPABASE_URL or SUPABASE_ANON_KEY in .env")
    exit(1)

try:
    from supabase import create_client
    sb = create_client(URL, KEY)
    print("✓ Supabase client created")
except ImportError:
    print("ERROR: supabase not installed. Run: pip install supabase --break-system-packages")
    exit(1)
except Exception as e:
    print(f"ERROR creating client: {e}")
    exit(1)

# Test 1: Auth endpoint
print("\nTest 1: Auth endpoint...")
try:
    # Try to get the current session (should return None if not logged in)
    session = sb.auth.get_session()
    print(f"  ✓ Auth endpoint reachable. Session: {session}")
except Exception as e:
    print(f"  ✗ Auth error: {e}")

# Test 2: Database — check if pro_law_users table exists
print("\nTest 2: pro_law_users table...")
try:
    resp = sb.table("pro_law_users").select("id").limit(1).execute()
    print(f"  ✓ Table exists. Rows returned: {len(resp.data)}")
    print(f"  Data: {resp.data}")
except Exception as e:
    print(f"  ✗ Table error: {e}")
    print("  → Run supabase_setup.sql in your Supabase SQL editor")

# Test 3: Try signing in (will fail with wrong creds but tells us endpoint works)
print("\nTest 3: Auth sign-in endpoint...")
try:
    sb.auth.sign_in_with_password({"email": "test@test.com", "password": "wrongpassword123"})
    print("  Unexpected success")
except Exception as e:
    err = str(e)
    if "Invalid login credentials" in err or "invalid_credentials" in err:
        print(f"  ✓ Auth working correctly (got expected 'invalid credentials' for test account)")
    elif "Email not confirmed" in err:
        print(f"  ✓ Auth working (email confirmation required)")
    else:
        print(f"  Response: {err}")

# Test 4: Check email confirmation setting impact
print("\nTest 4: Signup test...")
import random, string
test_email = f"test_{''.join(random.choices(string.ascii_lowercase, k=6))}@prolaw-test.com"
try:
    resp = sb.auth.sign_up({"email": test_email, "password": "TestPass123!"})
    user = getattr(resp, "user", None)
    identities = getattr(user, "identities", None) if user else None
    print(f"  ✓ Signup endpoint works")
    print(f"  User ID: {getattr(user, 'id', None)}")
    print(f"  Identities: {identities}")
    if identities is not None and len(identities) == 0:
        print("  → Email confirmation is ON (user created but needs confirmation)")
    elif user:
        print("  → Email confirmation appears to be OFF (user created and active)")
    # Clean up test user
    try:
        if user:
            sb.auth.admin.delete_user(str(user.id))
            print(f"  Cleaned up test user")
    except Exception:
        print(f"  Note: Could not clean up test user {test_email} — delete it manually in Supabase")
except Exception as e:
    print(f"  Signup error: {e}")

print("\n--- Test complete ---")
