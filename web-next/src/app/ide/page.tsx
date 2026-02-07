import { redirect } from 'next/navigation';
import { getSession } from '@/lib/auth';
import { supabase } from '@/lib/supabase';
import ProjectListClient from './ProjectListClient';

interface Project {
  id: number;
  name: string;
  updated_at: string;
  last_build?: string | null;
}

async function getProjects(userId: number): Promise<Project[]> {
  const { data, error } = await supabase
    .from('cloudpebble_projects')
    .select('id, name, updated_at')
    .eq('owner_id', userId)
    .order('updated_at', { ascending: false });

  if (error) {
    console.error('Failed to fetch projects:', error);
    return [];
  }

  return data || [];
}

export default async function IDEPage() {
  const user = await getSession();

  if (!user) {
    redirect('/accounts/login');
  }

  const projects = await getProjects(user.id);

  return <ProjectListClient projects={projects} />;
}
