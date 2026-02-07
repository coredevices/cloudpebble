import { NextRequest, NextResponse } from 'next/server';
import { getSession } from '@/lib/auth';
import { supabase } from '@/lib/supabase';

// GET /api/projects/[id]/source - List source files
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const user = await getSession();

  if (!user) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const projectId = parseInt(id, 10);
  if (isNaN(projectId)) {
    return NextResponse.json({ error: 'Invalid project ID' }, { status: 400 });
  }

  // Verify project ownership
  const { data: project } = await supabase
    .from('cloudpebble_projects')
    .select('id')
    .eq('id', projectId)
    .eq('owner_id', user.id)
    .single();

  if (!project) {
    return NextResponse.json({ error: 'Project not found' }, { status: 404 });
  }

  // Get source files
  const { data: files, error } = await supabase
    .from('cloudpebble_source_files')
    .select('id, file_name, target, created_at, updated_at')
    .eq('project_id', projectId)
    .order('file_name');

  if (error) {
    console.error('Failed to fetch source files:', error);
    return NextResponse.json({ error: 'Failed to fetch files' }, { status: 500 });
  }

  return NextResponse.json({ files: files || [] });
}

// POST /api/projects/[id]/source - Create source file
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const user = await getSession();

  if (!user) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const projectId = parseInt(id, 10);
  if (isNaN(projectId)) {
    return NextResponse.json({ error: 'Invalid project ID' }, { status: 400 });
  }

  const body = await request.json();
  const { file_name, target = 'app', content = '' } = body;

  if (!file_name) {
    return NextResponse.json({ error: 'File name required' }, { status: 400 });
  }

  // Verify project ownership
  const { data: project } = await supabase
    .from('cloudpebble_projects')
    .select('id')
    .eq('id', projectId)
    .eq('owner_id', user.id)
    .single();

  if (!project) {
    return NextResponse.json({ error: 'Project not found' }, { status: 404 });
  }

  // Create source file
  const { data: file, error } = await supabase
    .from('cloudpebble_source_files')
    .insert({
      project_id: projectId,
      file_name,
      target,
      content,
    })
    .select()
    .single();

  if (error) {
    console.error('Failed to create source file:', error);
    if (error.code === '23505') {
      return NextResponse.json({ error: 'File already exists' }, { status: 409 });
    }
    return NextResponse.json({ error: 'Failed to create file' }, { status: 500 });
  }

  return NextResponse.json({ file }, { status: 201 });
}
