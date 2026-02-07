#!/usr/bin/env npx tsx

import { createClient } from '@supabase/supabase-js';
import { readFileSync } from 'fs';
import { resolve } from 'path';

// Read .env.local manually
const envPath = resolve(process.cwd(), '.env.local');
const envContent = readFileSync(envPath, 'utf-8');
const env: Record<string, string> = {};
for (const line of envContent.split('\n')) {
  const match = line.match(/^([^=]+)=(.*)$/);
  if (match) {
    env[match[1].trim()] = match[2].trim();
  }
}

const supabaseUrl = env['SUPABASE_URL'] || env['NEXT_PUBLIC_SUPABASE_URL'];
const supabaseKey = env['SUPABASE_SERVICE_KEY'] || env['SUPABASE_SERVICE_ROLE_KEY'];

console.log(`Connecting to: ${supabaseUrl}\n`);

const supabase = createClient(supabaseUrl, supabaseKey);

async function checkTablesDirectly() {
  console.log('🔍 Checking CloudPebble database schema...\n');

  const tables = [
    'cloudpebble_users',
    'cloudpebble_sessions', 
    'cloudpebble_projects',
    'cloudpebble_source_files',
    'cloudpebble_resource_files',
    'cloudpebble_resource_identifiers',
    'cloudpebble_resource_variants',
    'cloudpebble_builds',
    'cloudpebble_build_sizes',
    'cloudpebble_dependencies',
    'cloudpebble_project_dependencies'
  ];

  for (const table of tables) {
    const { error, count } = await supabase
      .from(table)
      .select('*', { count: 'exact', head: true });
    
    if (error) {
      console.log(`❌ ${table}: NOT FOUND`);
      console.log(`   ${error.message}`);
    } else {
      console.log(`✅ ${table}: EXISTS (${count ?? 0} rows)`);
    }
  }

  console.log('\n📊 Checking new columns in cloudpebble_projects...');
  const { data: project, error: projErr } = await supabase
    .from('cloudpebble_projects')
    .select('id, name, app_jshint, app_platforms, app_keywords, optimisation, github_hook_build, last_modified')
    .limit(1);
  
  if (projErr) {
    console.log(`❌ Error querying projects: ${projErr.message}`);
  } else {
    console.log('✅ All new project columns present');
  }

  console.log('\n📊 Checking target column in cloudpebble_source_files...');
  const { error: sfError } = await supabase
    .from('cloudpebble_source_files')
    .select('id, file_name, target')
    .limit(1);
  
  if (sfError) {
    console.log(`❌ Error: ${sfError.message}`);
  } else {
    console.log('✅ target column present in source_files');
  }

  console.log('\n✨ Schema check complete!');
}

checkTablesDirectly().catch(console.error);
