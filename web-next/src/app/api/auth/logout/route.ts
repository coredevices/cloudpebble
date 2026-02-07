import { NextResponse } from 'next/server';
import { destroySession, SESSION_COOKIE } from '@/lib/auth';

export async function POST() {
  try {
    await destroySession();

    const response = NextResponse.json({ success: true });
    response.cookies.delete(SESSION_COOKIE);

    return response;
  } catch (error) {
    console.error('Logout error:', error);
    return NextResponse.json(
      { error: 'An error occurred during logout' },
      { status: 500 }
    );
  }
}
