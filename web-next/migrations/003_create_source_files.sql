-- Migration: Create source files table
-- Run this in Supabase SQL editor

CREATE TABLE IF NOT EXISTS cloudpebble_source_files (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES cloudpebble_projects(id) ON DELETE CASCADE,
    file_name VARCHAR(100) NOT NULL,
    target VARCHAR(10) NOT NULL DEFAULT 'app',
    content TEXT DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(project_id, file_name)
);

-- Enable RLS
ALTER TABLE cloudpebble_source_files ENABLE ROW LEVEL SECURITY;

-- Create policy for authenticated access
CREATE POLICY "Users can manage their project source files" ON cloudpebble_source_files
    FOR ALL USING (
        project_id IN (
            SELECT id FROM cloudpebble_projects WHERE owner_id = (
                SELECT id FROM cloudpebble_users WHERE id = current_setting('app.current_user_id')::int
            )
        )
    );

-- Index for fast lookup
CREATE INDEX idx_source_files_project ON cloudpebble_source_files(project_id);
