-- Migration: 001_complete_schema
-- Description: Complete CloudPebble database schema from Django models
-- Created: 2026-02-07
-- Source: cloudpebble/ide/models/*.py

-- ============================================
-- Drop existing tables (if re-running)
-- ============================================
-- DROP TABLE IF EXISTS cloudpebble_project_dependencies CASCADE;
-- DROP TABLE IF EXISTS cloudpebble_dependencies CASCADE;
-- DROP TABLE IF EXISTS cloudpebble_build_sizes CASCADE;
-- DROP TABLE IF EXISTS cloudpebble_builds CASCADE;
-- DROP TABLE IF EXISTS cloudpebble_source_files CASCADE;
-- DROP TABLE IF EXISTS cloudpebble_resource_identifiers CASCADE;
-- DROP TABLE IF EXISTS cloudpebble_resource_variants CASCADE;
-- DROP TABLE IF EXISTS cloudpebble_resource_files CASCADE;
-- DROP TABLE IF EXISTS cloudpebble_user_github CASCADE;
-- DROP TABLE IF EXISTS cloudpebble_user_settings CASCADE;
-- DROP TABLE IF EXISTS cloudpebble_sessions CASCADE;
-- DROP TABLE IF EXISTS cloudpebble_projects CASCADE;
-- DROP TABLE IF EXISTS cloudpebble_users CASCADE;

-- ============================================
-- 1. USERS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(150) UNIQUE NOT NULL,
    email VARCHAR(254),
    password VARCHAR(128) NOT NULL,
    first_name VARCHAR(30) DEFAULT '',
    last_name VARCHAR(30) DEFAULT '',
    is_active BOOLEAN DEFAULT true,
    is_staff BOOLEAN DEFAULT false,
    is_superuser BOOLEAN DEFAULT false,
    date_joined TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login TIMESTAMP WITH TIME ZONE
);

-- ============================================
-- 2. USER SETTINGS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_user_settings (
    user_id INTEGER PRIMARY KEY REFERENCES cloudpebble_users(id) ON DELETE CASCADE,
    autocomplete INTEGER DEFAULT 1, -- 1=always, 2=explicit, 3=never
    keybinds VARCHAR(20) DEFAULT 'default', -- default, vim, emacs
    theme VARCHAR(50) DEFAULT 'cloudpebble',
    use_spaces BOOLEAN DEFAULT true,
    tab_width SMALLINT DEFAULT 2,
    accepted_terms BOOLEAN DEFAULT true,
    whats_new INTEGER DEFAULT 0
);

-- ============================================
-- 3. USER GITHUB TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_user_github (
    user_id INTEGER PRIMARY KEY REFERENCES cloudpebble_users(id) ON DELETE CASCADE,
    token VARCHAR(50),
    nonce VARCHAR(36),
    username VARCHAR(50),
    avatar VARCHAR(255)
);

-- ============================================
-- 4. SESSIONS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_sessions (
    session_key VARCHAR(64) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES cloudpebble_users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON cloudpebble_sessions(user_id);

-- ============================================
-- 5. PROJECTS TABLE (from project.py - Project model)
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_projects (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES cloudpebble_users(id) ON DELETE CASCADE,
    name VARCHAR(50) NOT NULL,
    last_modified TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Project type: native, simplyjs, pebblejs, package, rocky
    project_type VARCHAR(10) DEFAULT 'native',
    
    -- SDK version: 2 or 3
    sdk_version VARCHAR(6) DEFAULT '3',
    
    -- App metadata
    app_uuid UUID DEFAULT gen_random_uuid(),
    app_company_name VARCHAR(100),
    app_short_name VARCHAR(100),
    app_long_name VARCHAR(100),
    app_version_label VARCHAR(40) DEFAULT '1.0',
    app_is_watchface BOOLEAN DEFAULT false,
    app_is_hidden BOOLEAN DEFAULT false,
    app_is_shown_on_communication BOOLEAN DEFAULT false,
    app_capabilities VARCHAR(255) DEFAULT '',
    app_keys TEXT DEFAULT '[]',
    app_jshint BOOLEAN DEFAULT true,
    app_platforms TEXT,
    app_modern_multi_js BOOLEAN DEFAULT true,
    app_keywords TEXT DEFAULT '[]',
    
    -- Optimisation: 0, 1, s, 2, 3
    optimisation VARCHAR(1) DEFAULT 's',
    
    -- GitHub integration
    github_repo VARCHAR(100),
    github_branch VARCHAR(100),
    github_last_sync TIMESTAMP WITH TIME ZONE,
    github_last_commit VARCHAR(40),
    github_hook_uuid VARCHAR(36),
    github_hook_build BOOLEAN DEFAULT false,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(owner_id, name)
);

CREATE INDEX IF NOT EXISTS idx_projects_owner ON cloudpebble_projects(owner_id);

-- ============================================
-- 6. PROJECT DEPENDENCIES (M2M for packages)
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_project_dependencies (
    id SERIAL PRIMARY KEY,
    from_project_id INTEGER NOT NULL REFERENCES cloudpebble_projects(id) ON DELETE CASCADE,
    to_project_id INTEGER NOT NULL REFERENCES cloudpebble_projects(id) ON DELETE CASCADE,
    UNIQUE(from_project_id, to_project_id)
);

CREATE INDEX IF NOT EXISTS idx_proj_deps_from ON cloudpebble_project_dependencies(from_project_id);
CREATE INDEX IF NOT EXISTS idx_proj_deps_to ON cloudpebble_project_dependencies(to_project_id);

-- ============================================
-- 7. NPM DEPENDENCIES TABLE (from dependency.py)
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_dependencies (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES cloudpebble_projects(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    version VARCHAR(2000) NOT NULL,
    UNIQUE(project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_deps_project ON cloudpebble_dependencies(project_id);

-- ============================================
-- 8. SOURCE FILES TABLE (from files.py - SourceFile)
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_source_files (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES cloudpebble_projects(id) ON DELETE CASCADE,
    file_name VARCHAR(100) NOT NULL,
    target VARCHAR(10) DEFAULT 'app', -- app, pkjs, worker, public, common
    
    -- Content stored inline for Supabase (not S3)
    content TEXT DEFAULT '',
    
    -- TextFile fields
    last_modified TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    folded_lines TEXT DEFAULT '[]',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(project_id, file_name, target)
);

CREATE INDEX IF NOT EXISTS idx_source_files_project ON cloudpebble_source_files(project_id);

-- ============================================
-- 9. RESOURCE FILES TABLE (from files.py - ResourceFile)
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_resource_files (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES cloudpebble_projects(id) ON DELETE CASCADE,
    file_name VARCHAR(100) NOT NULL,
    kind VARCHAR(9) NOT NULL, -- raw, bitmap, png, png-trans, font, pbi
    is_menu_icon BOOLEAN DEFAULT false,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(project_id, file_name)
);

CREATE INDEX IF NOT EXISTS idx_resource_files_project ON cloudpebble_resource_files(project_id);

-- ============================================
-- 10. RESOURCE VARIANTS TABLE (from files.py - ResourceVariant)
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_resource_variants (
    id SERIAL PRIMARY KEY,
    resource_file_id INTEGER NOT NULL REFERENCES cloudpebble_resource_files(id) ON DELETE CASCADE,
    tags VARCHAR(50) DEFAULT '', -- comma-separated integers
    is_legacy BOOLEAN DEFAULT false,
    
    -- S3 path or inline content
    s3_path VARCHAR(500),
    content BYTEA, -- for inline storage
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(resource_file_id, tags)
);

CREATE INDEX IF NOT EXISTS idx_resource_variants_file ON cloudpebble_resource_variants(resource_file_id);

-- ============================================
-- 11. RESOURCE IDENTIFIERS TABLE (from files.py - ResourceIdentifier)
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_resource_identifiers (
    id SERIAL PRIMARY KEY,
    resource_file_id INTEGER NOT NULL REFERENCES cloudpebble_resource_files(id) ON DELETE CASCADE,
    resource_id VARCHAR(100) NOT NULL,
    
    -- Font options
    character_regex VARCHAR(100),
    tracking INTEGER,
    compatibility VARCHAR(10),
    
    -- Platform targeting
    target_platforms VARCHAR(100),
    
    -- Bitmap options
    memory_format VARCHAR(15), -- Smallest, SmallestPalette, 1Bit, 8Bit, etc.
    storage_format VARCHAR(3), -- pbi, png
    space_optimisation VARCHAR(7), -- storage, memory
    
    UNIQUE(resource_file_id, resource_id)
);

CREATE INDEX IF NOT EXISTS idx_resource_ids_file ON cloudpebble_resource_identifiers(resource_file_id);

-- ============================================
-- 12. BUILDS TABLE (from build.py - BuildResult)
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_builds (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES cloudpebble_projects(id) ON DELETE CASCADE,
    uuid UUID DEFAULT gen_random_uuid(),
    state INTEGER DEFAULT 1, -- 1=waiting, 2=failed, 3=succeeded
    started TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    finished TIMESTAMP WITH TIME ZONE,
    
    -- Build output URLs (S3 paths)
    pbw_url VARCHAR(500),
    build_log_url VARCHAR(500),
    build_dir VARCHAR(500)
);

CREATE INDEX IF NOT EXISTS idx_builds_project ON cloudpebble_builds(project_id);
CREATE INDEX IF NOT EXISTS idx_builds_uuid ON cloudpebble_builds(uuid);
CREATE INDEX IF NOT EXISTS idx_builds_started ON cloudpebble_builds(started);

-- ============================================
-- 13. BUILD SIZES TABLE (from build.py - BuildSize)
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_build_sizes (
    id SERIAL PRIMARY KEY,
    build_id INTEGER NOT NULL REFERENCES cloudpebble_builds(id) ON DELETE CASCADE,
    platform VARCHAR(20) NOT NULL, -- aplite, basalt, chalk, diorite, emery
    
    total_size INTEGER,
    binary_size INTEGER,
    resource_size INTEGER,
    worker_size INTEGER
);

CREATE INDEX IF NOT EXISTS idx_build_sizes_build ON cloudpebble_build_sizes(build_id);

-- ============================================
-- 14. TEMPLATE PROJECTS TABLE (optional, for SDK demos)
-- ============================================
CREATE TABLE IF NOT EXISTS cloudpebble_template_projects (
    project_id INTEGER PRIMARY KEY REFERENCES cloudpebble_projects(id) ON DELETE CASCADE,
    template_kind INTEGER NOT NULL -- 1=template, 2=sdk_demo
);

CREATE INDEX IF NOT EXISTS idx_template_kind ON cloudpebble_template_projects(template_kind);
