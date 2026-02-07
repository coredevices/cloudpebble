import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { cookies } from 'next/headers';

const supabase = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_KEY!
);

// Create new source file
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: projectId } = await params;
  const cookieStore = await cookies();
  const sessionKey = cookieStore.get('session_key')?.value;

  if (!sessionKey) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  // Verify session and project ownership
  const { data: session } = await supabase
    .from('cloudpebble_sessions')
    .select('user_id')
    .eq('session_key', sessionKey)
    .single();

  if (!session) {
    return NextResponse.json({ error: 'Invalid session' }, { status: 401 });
  }

  const { data: project } = await supabase
    .from('cloudpebble_projects')
    .select('id, project_type')
    .eq('id', projectId)
    .eq('owner_id', session.user_id)
    .single();

  if (!project) {
    return NextResponse.json({ error: 'Project not found' }, { status: 404 });
  }

  const body = await request.json();
  const { name, target = 'app', content = '' } = body;

  if (!name) {
    return NextResponse.json({ error: 'Name is required' }, { status: 400 });
  }

  // Create file
  const { data: file, error } = await supabase
    .from('cloudpebble_source_files')
    .insert({
      project_id: projectId,
      file_name: name,
      target,
      content,
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 400 });
  }

  return NextResponse.json({
    file: {
      id: file.id,
      name: file.file_name,
      target: file.target,
      file_path: getFilePath(project.project_type, file.target, file.file_name),
    },
  });
}

function getFilePath(projectType: string, target: string, fileName: string): string {
  const dirMap: Record<string, Record<string, string[]>> = {
    native: {
      pkjs: ['src/pkjs'],
      worker: ['worker_src/c'],
      app: ['src/c'],
    },
    pebblejs: { app: ['src/js'] },
    simplyjs: { app: ['src'] },
    rocky: {
      app: ['src/rocky'],
      pkjs: ['src/pkjs'],
      common: ['src/common'],
    },
    package: {
      app: ['src/c'],
      public: ['include'],
      pkjs: ['src/js'],
    },
  };

  const dirs = dirMap[projectType]?.[target] || ['src'];
  return `${dirs[0]}/${fileName}`;
}
