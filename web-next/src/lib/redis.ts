import Redis from 'ioredis';

const redis = new Redis({
  host: process.env.REDIS_HOST || 'obelisk-sweet.exe.xyz',
  port: parseInt(process.env.REDIS_PORT || '6379'),
  db: 1, // Celery uses db 1
});

export default redis;
