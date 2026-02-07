import { Pool } from 'pg';

const pool = new Pool({
  host: process.env.DATABASE_HOST || 'obelisk-sweet.exe.xyz',
  port: parseInt(process.env.DATABASE_PORT || '5432'),
  database: process.env.DATABASE_NAME || 'postgres',
  user: process.env.DATABASE_USER || 'postgres',
  password: process.env.DATABASE_PASSWORD || '',
  ssl: false,
});

export async function query(text: string, params?: unknown[]) {
  const client = await pool.connect();
  try {
    const result = await client.query(text, params);
    return result;
  } finally {
    client.release();
  }
}

export default pool;
