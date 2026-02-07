import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { cookies } from 'next/headers';

const supabase = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_KEY!
);

async function verifyAccess(projectId: string, sessionKey: string | undefined) {
  if (!sessionKey) {
    return { error: 'Not authenticated', status: 401 };
  }

  const { data: session } = await supabase
    .from('cloudpebble_sessions')
    .select('user_id')
    .eq('session_key', sessionKey)
    .single();

  if (!session) {
    return { error: 'Invalid session', status: 401 };
  }

  const { data: project } = await supabase
    .from('cloudpebble_projects')
    .select('id')
    .eq('id', projectId)
    .eq('owner_id', session.user_id)
    .single();

  if (!project) {
    return { error: 'Project not found', status: 404 };
  }

  return { userId: session.user_id };
}

// Load source file content
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; fileId: string }> }
) {
  const { id: projectId, fileId } = await params;
  const cookieStore = await cookies();
  const sessionKey = cookieStore.get('session_key')?.value;

  const access = await verifyAccess(projectId, sessionKey);
  if ('error' in access) {
    return NextResponse.json({ error: access.error }, { status: access.status });
  }

  const { data: file, error } = await supabase
    .from('cloudpebble_source_files')
    .select('*')
    .eq('id', fileId)
    .eq('project_id', projectId)
    .single();

  if (error || !file) {
    return NextResponse.json({ error: 'File not found' }, { status: 404 });
  }

  return NextResponse.json({
    source: file.content || '',
    modified: new Date(file.updated_at).getTime() / 1000,
    folded_lines: [],
  });
}

// Save source file content
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; fileId: string }> }
) {
  const { id: projectId, fileId } = await params;
  const cookieStore = await cookies();
  const sessionKey = cookieStore.get('session_key')?.value;

  const access = await verifyAccess(projectId, sessionKey);
  if ('error' in access) {
    return NextResponse.json({ error: access.error }, { status: access.status });
  }

  const body = await request.json();
  const { content } = body;

  const { data: file, error } = await supabase
    .from('cloudpebble_source_files')
    .update({
      content,
      updated_at: new Date().toISOString(),
    })
    .eq('id', fileId)
    .eq('project_id', projectId)
    .select()
    .single();

  if (error || !file) {
    return NextResponse.json({ error: 'Failed to save file' }, { status: 400 });
  }

  // Update project last_modified
  await supabase
    .from('cloudpebble_projects')
    .update({ last_modified: new Date().toISOString() })
    .eq('id', projectId);

  return NextResponse.json({
    modified: new Date(file.updated_at).getTime() / 1000,
  });
}

// Delete source file
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; fileId: string }> }
) {
  const { id: projectId, fileId } = await params;
  const cookieStore = await cookies();
  const sessionKey = cookieStore.get('session_key')?.value;

  const access = await verifyAccess(projectId, sessionKey);
  if ('error' in access) {
    return NextResponse.json({ error: access.error }, { status: access.status });
  }

  const { error } = await supabase
    .from('cloudpebble_source_files')
    .delete()
    .eq('id', fileId)
    .eq('project_id', projectId);

  if (error) {
    return NextResponse.json({ error: 'Failed to delete file' }, { status: 400 });
  }

  return NextResponse.json({ success: true });
}
