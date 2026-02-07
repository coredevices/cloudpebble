import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { cookies } from 'next/headers';

const supabase = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_KEY!
);

async function getSession() {
  const cookieStore = await cookies();
  const sessionKey = cookieStore.get('session_key')?.value;
  
  if (!sessionKey) return null;
  
  const { data: session } = await supabase
    .from('cloudpebble_sessions')
    .select('user_id, cloudpebble_users(id, username)')
    .eq('session_key', sessionKey)
    .single();
  
  if (!session) return null;
  
  return {
    id: session.user_id,
    username: (session.cloudpebble_users as any)?.username || 'unknown',
  };
}

export async function GET() {
  const user = await getSession();
  
  if (!user) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  
  const { data: projects, error } = await supabase
    .from('cloudpebble_projects')
    .select('id, name, app_uuid, app_is_watchface, project_type, updated_at')
    .eq('owner_id', user.id)
    .order('updated_at', { ascending: false });
  
  if (error) {
    console.error('Failed to fetch projects:', error);
    return NextResponse.json({ error: 'Failed to fetch projects' }, { status: 500 });
  }
  
  return NextResponse.json({ projects });
}

export async function POST(request: NextRequest) {
  const user = await getSession();
  
  if (!user) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  
  try {
    const body = await request.json();
    const name = body.name;
    const project_type = body.type || body.project_type || 'native';
    const sdk_version = body.sdk || '3';
    const template_id = body.template || null;
    
    if (!name) {
      return NextResponse.json({ error: 'Project name is required' }, { status: 400 });
    }
    
    // Match Django's create_project exactly
    const app_keys = sdk_version === '2' ? '{}' : '[]';
    
    const { data: project, error } = await supabase
      .from('cloudpebble_projects')
      .insert({
        owner_id: user.id,
        name: name,
        app_company_name: user.username,
        app_short_name: name,
        app_long_name: name,
        app_version_label: '1.0',
        app_is_watchface: false,
        app_is_hidden: false,
        app_is_shown_on_communication: false,
        app_capabilities: '',
        app_keys: app_keys,
        project_type: project_type,
        sdk_version: sdk_version,
        app_jshint: true,
        app_modern_multi_js: sdk_version !== '2',
      })
      .select()
      .single();
    
    if (error) {
      console.error('Failed to create project:', error);
      return NextResponse.json({ error: error.message }, { status: 500 });
    }
    
    // Create default source file based on project type (like Django does)
    if (project_type === 'simplyjs') {
      await supabase
        .from('cloudpebble_source_files')
        .insert({
          project_id: project.id,
          file_name: 'app.js',
          target: 'app',
          content: getSimplyJsTemplate(),
        });
    } else if (project_type === 'pebblejs') {
      await supabase
        .from('cloudpebble_source_files')
        .insert({
          project_id: project.id,
          file_name: 'app.js',
          target: 'app',
          content: getPebbleJsTemplate(),
        });
    }
    // Note: native projects don't get default files in Django
    
    // Return same format as Django: { id: project.id }
    return NextResponse.json({ id: project.id });
  } catch (error) {
    console.error('Create project error:', error);
    return NextResponse.json({ error: 'Failed to create project' }, { status: 500 });
  }
}

function getSimplyJsTemplate(): string {
  return `// Welcome to Simply.js!
// 
// This is a basic Simply.js app that shows "Hello World"

simply.on('singleClick', function(e) {
  console.log('Single click on ' + e.button + ' button');
});

simply.text({
  title: 'Simply.js',
  body: 'Hello World!'
});
`;
}

function getPebbleJsTemplate(): string {
  return `// Welcome to Pebble.js!

var UI = require('ui');

var main = new UI.Card({
  title: 'Pebble.js',
  body: 'Hello World!'
});

main.show();
`;
}
