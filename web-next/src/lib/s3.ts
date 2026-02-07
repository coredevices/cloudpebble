import { S3Client, GetObjectCommand, PutObjectCommand, DeleteObjectCommand } from '@aws-sdk/client-s3';

const s3Client = new S3Client({
  endpoint: process.env.S3_ENDPOINT || 'http://obelisk-sweet.exe.xyz:8003',
  region: 'us-east-1',
  credentials: {
    accessKeyId: process.env.S3_ACCESS_KEY || 'fake',
    secretAccessKey: process.env.S3_SECRET_KEY || 'fake',
  },
  forcePathStyle: true, // Required for fake-s3
});

export const BUCKETS = {
  SOURCE: 'source.cloudpebble.net',
  BUILDS: 'builds.cloudpebble.net',
  EXPORT: 'export.cloudpebble.net',
};

export async function getObject(bucket: string, key: string): Promise<string> {
  const command = new GetObjectCommand({ Bucket: bucket, Key: key });
  const response = await s3Client.send(command);
  return await response.Body?.transformToString() || '';
}

export async function putObject(bucket: string, key: string, body: string | Buffer): Promise<void> {
  const command = new PutObjectCommand({ Bucket: bucket, Key: key, Body: body });
  await s3Client.send(command);
}

export async function deleteObject(bucket: string, key: string): Promise<void> {
  const command = new DeleteObjectCommand({ Bucket: bucket, Key: key });
  await s3Client.send(command);
}

export default s3Client;
