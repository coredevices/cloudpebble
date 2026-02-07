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
