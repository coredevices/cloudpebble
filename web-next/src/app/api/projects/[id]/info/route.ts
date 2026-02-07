import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { cookies } from 'next/headers';

const supabase = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_KEY!
);

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const cookieStore = await cookies();
  const sessionKey = cookieStore.get('session_key')?.value;

  if (!sessionKey) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  // Verify session
  const { data: session } = await supabase
    .from('cloudpebble_sessions')
    .select('user_id')
    .eq('session_key', sessionKey)
    .single();

  if (!session) {
    return NextResponse.json({ error: 'Invalid session' }, { status: 401 });
  }

  // Get project
  const { data: project, error: projectError } = await supabase
    .from('cloudpebble_projects')
    .select('*')
    .eq('id', id)
    .eq('owner_id', session.user_id)
    .single();

  if (projectError || !project) {
    return NextResponse.json({ error: 'Project not found' }, { status: 404 });
  }

  // Get source files
  const { data: sourceFiles } = await supabase
    .from('cloudpebble_source_files')
    .select('id, file_name, target, updated_at')
    .eq('project_id', id)
    .order('file_name');

  // Get resources
  const { data: resources } = await supabase
    .from('cloudpebble_resource_files')
    .select('id, file_name, kind')
    .eq('project_id', id)
    .order('file_name');

  // Get resource identifiers for each resource
  const resourcesWithIdentifiers = await Promise.all(
    (resources || []).map(async (resource) => {
      const { data: identifiers } = await supabase
        .from('cloudpebble_resource_identifiers')
        .select('resource_id')
        .eq('resource_file_id', resource.id);
      
      return {
        id: resource.id,
        file_name: resource.file_name,
        kind: resource.kind,
        identifiers: (identifiers || []).map(i => i.resource_id),
      };
    })
  );

  // Format response to match Django API
  return NextResponse.json({
    type: project.project_type,
    name: project.name,
    last_modified: project.last_modified || project.updated_at,
    app_uuid: project.app_uuid || '',
    app_company_name: project.app_company_name || '',
    app_short_name: project.app_short_name || '',
    app_long_name: project.app_long_name || '',
    app_version_label: project.app_version_label || '1.0',
    app_is_watchface: project.app_is_watchface || false,
    app_is_hidden: project.app_is_hidden || false,
    app_keys: project.app_keys ? JSON.parse(project.app_keys) : [],
    app_is_shown_on_communication: project.app_is_shown_on_communication || false,
    app_capabilities: project.app_capabilities || '',
    app_jshint: project.app_jshint !== false,
    sdk_version: project.sdk_version || '3',
    app_platforms: project.app_platforms || null,
    app_modern_multi_js: project.app_modern_multi_js !== false,
    menu_icon: null,
    source_files: (sourceFiles || []).map(f => ({
      name: f.file_name,
      id: f.id,
      target: f.target || 'app',
      file_path: getFilePath(project.project_type, f.target || 'app', f.file_name),
      lastModified: new Date(f.updated_at).getTime() / 1000,
    })),
    resources: resourcesWithIdentifiers,
    github: {
      repo: project.github_repo ? `github.com/${project.github_repo}` : null,
      branch: project.github_branch || null,
      last_sync: project.github_last_sync || null,
      last_commit: project.github_last_commit || null,
      auto_build: project.github_hook_build || false,
      auto_pull: !!project.github_hook_uuid,
    },
    supported_platforms: getSupportedPlatforms(project.sdk_version, project.project_type),
  });
}

function getFilePath(projectType: string, target: string, fileName: string): string {
  const dirMap: Record<string, Record<string, string[]>> = {
    native: {
      pkjs: ['src/pkjs', 'src/js'],
      worker: ['worker_src/c', 'worker_src'],
      app: ['src/c', 'src'],
    },
    pebblejs: {
      app: ['src/js'],
    },
    simplyjs: {
      app: ['src'],
    },
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

function getSupportedPlatforms(sdkVersion: string, projectType: string): string[] {
  const platforms = ['aplite'];
  if (sdkVersion !== '2') {
    platforms.push('basalt', 'chalk');
    if (projectType !== 'pebblejs') {
      platforms.push('diorite', 'emery');
    }
  }
  return platforms;
}
