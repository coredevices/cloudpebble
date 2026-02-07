-- Migration: 002_seed_testuser
-- Description: Create test user for development
-- Created: 2026-02-07
-- Password: testpass123 (Django PBKDF2 format)

INSERT INTO cloudpebble_users (username, email, password, is_active)
VALUES (
    'testuser',
    'test@example.com',
    'pbkdf2_sha256$260000$testsalt$CBL3eLJPhCnruKLGFhBLTdU+J7E+t8fXzSjP7C0V3gg=',
    true
)
ON CONFLICT (username) DO NOTHING;

-- Create default user settings
INSERT INTO cloudpebble_user_settings (user_id, autocomplete, keybinds, theme, use_spaces, tab_width)
SELECT id, 1, 'default', 'cloudpebble', true, 2
FROM cloudpebble_users WHERE username = 'testuser'
ON CONFLICT (user_id) DO NOTHING;

-- Create a sample project
INSERT INTO cloudpebble_projects (
    owner_id, name, project_type, sdk_version,
    app_company_name, app_short_name, app_long_name, app_version_label
)
SELECT 
    id, 'My First App', 'native', '3',
    'testuser', 'My First App', 'My First App', '1.0'
FROM cloudpebble_users WHERE username = 'testuser'
ON CONFLICT (owner_id, name) DO NOTHING;
