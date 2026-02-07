import { supabase } from './supabase';
import { cookies } from 'next/headers';
import crypto from 'crypto';

// Django password format: algorithm$iterations$salt$hash
function verifyDjangoPassword(password: string, encoded: string): boolean {
  const parts = encoded.split('$');
  if (parts.length !== 4) return false;
  
  const [algorithm, iterations, salt, storedHash] = parts;
  
  if (algorithm !== 'pbkdf2_sha256') {
    console.error('Unsupported algorithm:', algorithm);
    return false;
  }
  
  const hash = crypto.pbkdf2Sync(
    password,
    salt,
    parseInt(iterations),
    32,
    'sha256'
  ).toString('base64');
  
  return hash === storedHash;
}

export interface User {
  id: number;
  username: string;
  email: string;
  is_active: boolean;
}

export async function authenticateUser(username: string, password: string): Promise<User | null> {
  const { data, error } = await supabase
    .from('cloudpebble_users')
    .select('id, username, email, password, is_active')
    .eq('username', username)
    .single();
  
  if (error || !data) {
    return null;
  }
  
  if (!data.is_active) {
    return null;
  }
  
  if (!verifyDjangoPassword(password, data.password)) {
    return null;
  }
  
  return {
    id: data.id,
    username: data.username,
    email: data.email,
    is_active: data.is_active,
  };
}

export const SESSION_COOKIE = 'cloudpebble_session';

export async function createSession(userId: number): Promise<string> {
  const sessionId = crypto.randomBytes(32).toString('hex');
  
  const { error } = await supabase
    .from('cloudpebble_sessions')
    .upsert({
      session_key: sessionId,
      user_id: userId,
      created_at: new Date().toISOString(),
    });
  
  if (error) {
    console.error('Failed to create session:', error);
    throw new Error('Failed to create session');
  }
  
  return sessionId;
}

export async function getSession(): Promise<User | null> {
  const cookieStore = await cookies();
  const sessionId = cookieStore.get(SESSION_COOKIE)?.value;
  
  if (!sessionId) {
    return null;
  }
  
  try {
    const { data: session, error: sessionError } = await supabase
      .from('cloudpebble_sessions')
      .select('user_id')
      .eq('session_key', sessionId)
      .single();
    
    if (sessionError || !session) {
      return null;
    }
    
    const { data: user, error: userError } = await supabase
      .from('cloudpebble_users')
      .select('id, username, email, is_active')
      .eq('id', session.user_id)
      .single();
    
    if (userError || !user) {
      return null;
    }
    
    return user;
  } catch {
    return null;
  }
}

export async function destroySession(): Promise<void> {
  const cookieStore = await cookies();
  const sessionId = cookieStore.get(SESSION_COOKIE)?.value;
  
  if (sessionId) {
    await supabase
      .from('cloudpebble_sessions')
      .delete()
      .eq('session_key', sessionId);
  }
}
