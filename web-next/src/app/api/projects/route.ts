import { NextRequest, NextResponse } from 'next/server';
import { getSession } from '@/lib/auth';
import { supabase } from '@/lib/supabase';

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
    const { name, project_type = 'native', template_id } = await request.json();
    
    if (!name) {
      return NextResponse.json({ error: 'Project name is required' }, { status: 400 });
    }
    
    const { data: project, error } = await supabase
      .from('cloudpebble_projects')
      .insert({
        owner_id: user.id,
        name,
        project_type,
        app_short_name: name.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 32),
        app_long_name: name,
        app_company_name: user.username,
      })
      .select()
      .single();
    
    if (error) {
      console.error('Failed to create project:', error);
      return NextResponse.json({ error: 'Failed to create project' }, { status: 500 });
    }
    
    // If template_id provided, copy template files (TODO)
    if (template_id) {
      // Copy template source files to the new project
    }
    
    return NextResponse.json({ project });
  } catch (error) {
    console.error('Create project error:', error);
    return NextResponse.json({ error: 'Failed to create project' }, { status: 500 });
  }
}
