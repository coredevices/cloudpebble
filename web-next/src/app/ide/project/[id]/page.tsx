import { redirect } from 'next/navigation';
import { getSession } from '@/lib/auth';
import { supabase } from '@/lib/supabase';
import IDEClient from './IDEClient';

interface Project {
  id: number;
  name: string;
  project_type: string;
  app_uuid: string;
  owner_id: number;
}

async function getProject(projectId: number, userId: number): Promise<Project | null> {
  const { data, error } = await supabase
    .from('cloudpebble_projects')
    .select('*')
    .eq('id', projectId)
    .eq('owner_id', userId)
    .single();

  if (error) {
    console.error('Failed to fetch project:', error);
    return null;
  }

  return data;
}

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function ProjectPage({ params }: PageProps) {
  const { id } = await params;
  const user = await getSession();

  if (!user) {
    redirect('/accounts/login');
  }

  const projectId = parseInt(id, 10);
  if (isNaN(projectId)) {
    redirect('/ide/');
  }

  const project = await getProject(projectId, user.id);

  if (!project) {
    redirect('/ide/');
  }

  return <IDEClient project={project} />;
}
