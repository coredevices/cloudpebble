import { NextRequest, NextResponse } from 'next/server';
import { getSession } from '@/lib/auth';
import { supabase } from '@/lib/supabase';

// GET /api/projects/[id]/source/[fileId] - Load source file
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; fileId: string }> }
) {
  const { id, fileId } = await params;
  const user = await getSession();

  if (!user) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const projectId = parseInt(id, 10);
  const sourceFileId = parseInt(fileId, 10);

  if (isNaN(projectId) || isNaN(sourceFileId)) {
    return NextResponse.json({ error: 'Invalid ID' }, { status: 400 });
  }

  // Verify project ownership and get file
  const { data: project } = await supabase
    .from('cloudpebble_projects')
    .select('id')
    .eq('id', projectId)
    .eq('owner_id', user.id)
    .single();

  if (!project) {
    return NextResponse.json({ error: 'Project not found' }, { status: 404 });
  }

  const { data: file, error } = await supabase
    .from('cloudpebble_source_files')
    .select('*')
    .eq('id', sourceFileId)
    .eq('project_id', projectId)
    .single();

  if (error || !file) {
    return NextResponse.json({ error: 'File not found' }, { status: 404 });
  }

  return NextResponse.json({ file });
}

// PUT /api/projects/[id]/source/[fileId] - Save source file
export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; fileId: string }> }
) {
  const { id, fileId } = await params;
  const user = await getSession();

  if (!user) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const projectId = parseInt(id, 10);
  const sourceFileId = parseInt(fileId, 10);

  if (isNaN(projectId) || isNaN(sourceFileId)) {
    return NextResponse.json({ error: 'Invalid ID' }, { status: 400 });
  }

  const body = await request.json();
  const { content } = body;

  if (content === undefined) {
    return NextResponse.json({ error: 'Content required' }, { status: 400 });
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

  // Update file content
  const { data: file, error } = await supabase
    .from('cloudpebble_source_files')
    .update({
      content,
      updated_at: new Date().toISOString(),
    })
    .eq('id', sourceFileId)
    .eq('project_id', projectId)
    .select()
    .single();

  if (error) {
    console.error('Failed to save file:', error);
    return NextResponse.json({ error: 'Failed to save file' }, { status: 500 });
  }

  if (!file) {
    return NextResponse.json({ error: 'File not found' }, { status: 404 });
  }

  // Update project modified time
  await supabase
    .from('cloudpebble_projects')
    .update({ updated_at: new Date().toISOString() })
    .eq('id', projectId);

  return NextResponse.json({ file });
}

// DELETE /api/projects/[id]/source/[fileId] - Delete source file
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; fileId: string }> }
) {
  const { id, fileId } = await params;
  const user = await getSession();

  if (!user) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const projectId = parseInt(id, 10);
  const sourceFileId = parseInt(fileId, 10);

  if (isNaN(projectId) || isNaN(sourceFileId)) {
    return NextResponse.json({ error: 'Invalid ID' }, { status: 400 });
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

  // Delete file
  const { error } = await supabase
    .from('cloudpebble_source_files')
    .delete()
    .eq('id', sourceFileId)
    .eq('project_id', projectId);

  if (error) {
    console.error('Failed to delete file:', error);
    return NextResponse.json({ error: 'Failed to delete file' }, { status: 500 });
  }

  return NextResponse.json({ success: true });
}
