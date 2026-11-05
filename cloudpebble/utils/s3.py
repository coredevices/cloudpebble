import logging
import threading

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)


def _ensure_bucket_exists(s3_client, bucket):
    try:
        s3_client.create_bucket(Bucket=bucket)
        logger.info("Created bucket %s" % bucket)
    except ClientError as e:
        if e.response['Error']['Code'] != 'BucketAlreadyOwnedByYou':
            # Bucket exists, that's fine
            pass


class BucketHolder(object):
    """ The bucket holder configures s3 when it is first accessed. This cannot be done on module import due to quirks in Django's settings system.
    See: https://docs.djangoproject.com/en/dev/internals/contributing/writing-code/coding-style/#use-of-django-conf-settings """

    def __init__(self):
        self.bucket_names = {}
        self.configured = False
        self.s3 = None
        self.s3_resource = None
        self.supports_acl = True

    def configure(self):
        if settings.AWS_ENABLED:
            endpoint_url = getattr(settings, 'AWS_S3_ENDPOINT_URL', None)
            s3v4_config = Config(signature_version='s3v4')
            s3v4_path_config = Config(signature_version='s3v4', s3={'addressing_style': 'path'})
            if settings.AWS_S3_FAKE_S3 is not None:
                # Fake S3 (e.g., minio, fake-s3) — local dev
                host, port = (settings.AWS_S3_FAKE_S3.split(':', 2) + ['80'])[:2]
                port = int(port)
                fake_endpoint = 'http://%s:%d' % (host, port)

                self.s3 = boto3.client(
                    's3',
                    aws_access_key_id='key_id',
                    aws_secret_access_key='secret_key',
                    endpoint_url=fake_endpoint,
                    config=s3v4_path_config,
                )
                self.s3_resource = boto3.resource(
                    's3',
                    aws_access_key_id='key_id',
                    aws_secret_access_key='secret_key',
                    endpoint_url=fake_endpoint,
                    config=s3v4_path_config,
                )
                self.supports_acl = True

                _ensure_bucket_exists(self.s3, settings.AWS_S3_SOURCE_BUCKET)
                _ensure_bucket_exists(self.s3, settings.AWS_S3_EXPORT_BUCKET)
                _ensure_bucket_exists(self.s3, settings.AWS_S3_BUILDS_BUCKET)
            elif endpoint_url:
                # S3-compatible service (Cloudflare R2, MinIO, etc.)
                self.s3 = boto3.client(
                    's3',
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    endpoint_url=endpoint_url,
                    config=s3v4_path_config,
                )
                self.s3_resource = boto3.resource(
                    's3',
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    endpoint_url=endpoint_url,
                    config=s3v4_path_config,
                )
                self.supports_acl = False
            else:
                # Real AWS S3
                self.s3 = boto3.client(
                    's3',
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=getattr(settings, 'AWS_S3_REGION', 'us-east-1'),
                    config=s3v4_config,
                )
                self.s3_resource = boto3.resource(
                    's3',
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=getattr(settings, 'AWS_S3_REGION', 'us-east-1'),
                    config=s3v4_config,
                )
                self.supports_acl = True

            self.bucket_names = {
                'source': settings.AWS_S3_SOURCE_BUCKET,
                'export': settings.AWS_S3_EXPORT_BUCKET,
                'builds': settings.AWS_S3_BUILDS_BUCKET,
            }
            self.configured = True
        else:
            self.s3 = None
            self.s3_resource = None
            self.bucket_names = None

    # boto3's default session isn't safe for concurrent client creation, and
    # autocomplete init reads files from several threads at once.
    _configure_lock = threading.Lock()

    def _ensure_configured(self):
        if not self.configured:
            with self._configure_lock:
                if not self.configured:
                    self.configure()

    def __getitem__(self, item):
        if settings.TESTING:
            raise Exception("S3 not mocked in test!")
        self._ensure_configured()
        return self.bucket_names[item]

    def get_bucket(self, item):
        self._ensure_configured()
        return self.s3_resource.Bucket(self.bucket_names[item])


_buckets = BucketHolder()


def _requires_aws(fn):
    if settings.AWS_ENABLED:
        return fn
    else:
        def complain(*args, **kwargs):
            raise Exception("AWS_ENABLED must be True to call %s" % fn.__name__)

        return complain


@_requires_aws
def read_file(bucket_name, path):
    bucket_n = _buckets[bucket_name]
    response = _buckets.s3.get_object(Bucket=bucket_n, Key=path)
    return response['Body'].read()


@_requires_aws
def read_file_to_filesystem(bucket_name, path, destination):
    bucket_n = _buckets[bucket_name]
    _buckets.s3.download_file(bucket_n, path, destination)


@_requires_aws
def delete_file(bucket_name, path):
    bucket_n = _buckets[bucket_name]
    _buckets.s3.delete_object(Bucket=bucket_n, Key=path)


@_requires_aws
def save_file(bucket_name, path, value, public=False, content_type='application/octet-stream'):
    bucket_n = _buckets[bucket_name]

    extra_args = {'ContentType': content_type}
    if public and _buckets.supports_acl:
        extra_args['ACL'] = 'public-read'
    
    if isinstance(value, str):
        value = value.encode('utf-8')
    
    _buckets.s3.put_object(
        Bucket=bucket_n,
        Key=path,
        Body=value,
        **extra_args
    )


@_requires_aws
def upload_file(bucket_name, dest_path, src_path, public=False, content_type='application/octet-stream',
                download_filename=None):
    bucket_n = _buckets[bucket_name]

    extra_args = {'ContentType': content_type}
    if public and _buckets.supports_acl:
        extra_args['ACL'] = 'public-read'
    
    if download_filename is not None:
        extra_args['ContentDisposition'] = 'attachment;filename="%s"' % download_filename.replace(' ', '_')
    
    _buckets.s3.upload_file(src_path, bucket_n, dest_path, ExtraArgs=extra_args)


@_requires_aws
def get_signed_url(bucket_name, path, headers=None):
    bucket_n = _buckets[bucket_name]
    
    params = {
        'Bucket': bucket_n,
        'Key': path,
    }
    
    if headers:
        params['ResponseContentType'] = headers.get('Content-Type', headers.get('response-content-type'))
        if 'Content-Disposition' in headers or 'response-content-disposition' in headers:
            params['ResponseContentDisposition'] = headers.get('Content-Disposition', headers.get('response-content-disposition'))
    
    url = _buckets.s3.generate_presigned_url(
        'get_object',
        Params=params,
        ExpiresIn=3600
    )
    
    # hack to avoid invalid SSL certs.
    if '.cloudpebble.' in url:
        url = url.replace('.s3.amazonaws.com', '')
    
    return url
