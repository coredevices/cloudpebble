-- Migration: 001_initial_schema
-- Description: Create initial tables for CloudPebble
-- Created: 2026-02-07

-- Users table
CREATE TABLE IF NOT EXISTS cloudpebble_users (
  id SERIAL PRIMARY KEY,
  username VARCHAR(150) UNIQUE NOT NULL,
  email VARCHAR(254),
  password VARCHAR(128) NOT NULL,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW(),
  last_login TIMESTAMP
);

-- Sessions table for auth
CREATE TABLE IF NOT EXISTS cloudpebble_sessions (
  session_key VARCHAR(64) PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES cloudpebble_users(id) ON DELETE CASCADE,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cp_sessions_user_id ON cloudpebble_sessions(user_id);

-- Projects table
CREATE TABLE IF NOT EXISTS cloudpebble_projects (
  id SERIAL PRIMARY KEY,
  owner_id INTEGER NOT NULL REFERENCES cloudpebble_users(id) ON DELETE CASCADE,
  name VARCHAR(100) NOT NULL,
  app_uuid UUID DEFAULT gen_random_uuid(),
  app_short_name VARCHAR(32) DEFAULT '',
  app_long_name VARCHAR(100) DEFAULT '',
  app_company_name VARCHAR(100) DEFAULT '',
  app_version_label VARCHAR(16) DEFAULT '1.0',
  sdk_version VARCHAR(10) DEFAULT '3',
  app_is_watchface BOOLEAN DEFAULT false,
  app_is_hidden BOOLEAN DEFAULT false,
  app_is_shown_on_communication BOOLEAN DEFAULT false,
  app_capabilities TEXT DEFAULT '',
  app_keys TEXT DEFAULT '',
  project_type VARCHAR(10) DEFAULT 'native',
  app_modern_multi_js BOOLEAN DEFAULT false,
  github_repo VARCHAR(100),
  github_branch VARCHAR(100),
  github_last_sync TIMESTAMP,
  github_last_commit VARCHAR(40),
  github_hook_uuid UUID,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cp_projects_owner ON cloudpebble_projects(owner_id);

-- Source files table
CREATE TABLE IF NOT EXISTS cloudpebble_source_files (
  id SERIAL PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES cloudpebble_projects(id) ON DELETE CASCADE,
  file_name VARCHAR(100) NOT NULL,
  content TEXT DEFAULT '',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(project_id, file_name)
);

CREATE INDEX IF NOT EXISTS idx_cp_sourcefiles_project ON cloudpebble_source_files(project_id);

-- Resource files table
CREATE TABLE IF NOT EXISTS cloudpebble_resource_files (
  id SERIAL PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES cloudpebble_projects(id) ON DELETE CASCADE,
  file_name VARCHAR(100) NOT NULL,
  kind VARCHAR(20) DEFAULT 'raw',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cp_resourcefiles_project ON cloudpebble_resource_files(project_id);

-- Resource identifiers table
CREATE TABLE IF NOT EXISTS cloudpebble_resource_identifiers (
  id SERIAL PRIMARY KEY,
  resource_file_id INTEGER NOT NULL REFERENCES cloudpebble_resource_files(id) ON DELETE CASCADE,
  resource_id VARCHAR(100) NOT NULL,
  character_regex VARCHAR(100),
  tracking INTEGER,
  compatibility VARCHAR(20),
  target_platforms TEXT
);

-- Build results table
CREATE TABLE IF NOT EXISTS cloudpebble_builds (
  id SERIAL PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES cloudpebble_projects(id) ON DELETE CASCADE,
  uuid UUID DEFAULT gen_random_uuid(),
  state INTEGER DEFAULT 0,
  started_at TIMESTAMP DEFAULT NOW(),
  finished_at TIMESTAMP,
  build_log TEXT,
  pbw_url VARCHAR(500),
  build_dir VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_cp_builds_project ON cloudpebble_builds(project_id);
CREATE INDEX IF NOT EXISTS idx_cp_builds_uuid ON cloudpebble_builds(uuid);
