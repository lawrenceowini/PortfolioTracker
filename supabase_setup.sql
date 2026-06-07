-- supabase_setup.sql
-- PRO_LAW Portfolio Tracker — Supabase database setup
-- Run this in your Supabase project's SQL editor (supabase.com → SQL Editor)
-- ============================================================================

-- 1. User profiles table (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS public.pro_law_users (
    id                   BIGSERIAL PRIMARY KEY,
    user_id              UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    email                TEXT NOT NULL,
    full_name            TEXT,
    role                 TEXT NOT NULL DEFAULT 'viewer'
                             CHECK (role IN ('viewer', 'manager', 'admin')),
    assigned_portfolios  TEXT[] DEFAULT '{}',
    mfa_enabled          BOOLEAN DEFAULT FALSE,
    active               BOOLEAN DEFAULT TRUE,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    last_login           TIMESTAMPTZ,
    UNIQUE(user_id),
    UNIQUE(email)
);

-- 2. Row Level Security — users can only read their own row
ALTER TABLE public.pro_law_users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own profile"
    ON public.pro_law_users
    FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Admins can view all profiles"
    ON public.pro_law_users
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.pro_law_users
            WHERE user_id = auth.uid() AND role = 'admin'
        )
    );

CREATE POLICY "Admins can update all profiles"
    ON public.pro_law_users
    FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM public.pro_law_users
            WHERE user_id = auth.uid() AND role = 'admin'
        )
    );

CREATE POLICY "Admins can insert profiles"
    ON public.pro_law_users
    FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.pro_law_users
            WHERE user_id = auth.uid() AND role = 'admin'
        )
    );

CREATE POLICY "Admins can delete profiles"
    ON public.pro_law_users
    FOR DELETE
    USING (
        EXISTS (
            SELECT 1 FROM public.pro_law_users
            WHERE user_id = auth.uid() AND role = 'admin'
        )
    );

-- 3. Auto-create profile on new Supabase Auth signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.pro_law_users (user_id, email, full_name, role)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1)),
        COALESCE(NEW.raw_user_meta_data->>'role', 'viewer')
    )
    ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 4. Audit log table (mirrors local audit_trail.json in the database)
CREATE TABLE IF NOT EXISTS public.pro_law_audit_log (
    id           BIGSERIAL PRIMARY KEY,
    user_id      UUID REFERENCES auth.users(id),
    email        TEXT,
    event_type   TEXT NOT NULL,
    description  TEXT,
    details      JSONB,
    entry_hash   TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.pro_law_audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Admins can view audit log"
    ON public.pro_law_audit_log
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.pro_law_users
            WHERE user_id = auth.uid() AND role = 'admin'
        )
    );

CREATE POLICY "Authenticated users can insert audit entries"
    ON public.pro_law_audit_log
    FOR INSERT
    WITH CHECK (auth.uid() IS NOT NULL);

-- 5. Login attempt tracking
CREATE TABLE IF NOT EXISTS public.pro_law_login_attempts (
    id           BIGSERIAL PRIMARY KEY,
    email        TEXT NOT NULL,
    ip_address   TEXT,
    success      BOOLEAN NOT NULL,
    attempted_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_email
    ON public.pro_law_login_attempts(email, attempted_at DESC);

-- 6. Helper view: user summary (for admin dashboard)
CREATE OR REPLACE VIEW public.pro_law_user_summary AS
SELECT
    u.email,
    u.full_name,
    u.role,
    u.active,
    u.mfa_enabled,
    u.last_login,
    array_length(u.assigned_portfolios, 1) AS portfolio_count,
    u.created_at
FROM public.pro_law_users u
ORDER BY u.created_at DESC;

-- ============================================================================
-- SETUP COMPLETE
-- Next steps:
--   1. Copy your project URL and anon key from:
--      Supabase dashboard → Settings → API
--   2. Add to your .env file:
--      SUPABASE_URL=https://xxxx.supabase.co
--      SUPABASE_ANON_KEY=eyJ...
--   3. Create your first admin user via the Supabase Auth dashboard:
--      Authentication → Users → Add User
--      Then update their role in the pro_law_users table:
--      UPDATE pro_law_users SET role = 'admin' WHERE email = 'you@example.com';
-- ============================================================================

-- ============================================================================
-- ADDITIONAL POLICIES (run these if users can't log in or profiles aren't created)
-- ============================================================================

-- Allow any authenticated user to insert their OWN profile row
-- (needed so the dashboard can auto-create a profile on first login)
CREATE POLICY "Users can insert own profile"
    ON public.pro_law_users
    FOR INSERT
    WITH CHECK (auth.uid()::text = user_id::text);

-- Allow any authenticated user to update their OWN profile row
-- (needed for last_login updates)
CREATE POLICY "Users can update own profile"
    ON public.pro_law_users
    FOR UPDATE
    USING (auth.uid()::text = user_id::text);

-- Allow users to select their own profile (simpler version without recursion)
-- Drop the old recursive policy first if it causes infinite loops:
-- DROP POLICY IF EXISTS "Admins can view all profiles" ON public.pro_law_users;
-- DROP POLICY IF EXISTS "Users can view own profile" ON public.pro_law_users;

-- Simpler non-recursive select policy:
CREATE POLICY "All authenticated users can read profiles"
    ON public.pro_law_users
    FOR SELECT
    USING (auth.uid() IS NOT NULL);
