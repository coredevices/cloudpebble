# encoding: utf-8
# Django settings for cloudpebble project.

import sys
import os
import socket
from urllib.parse import urlsplit, urlunsplit
import dj_database_url

_environ = os.environ

DEBUG = _environ.get('DEBUG', '') != ''
VERBOSE = DEBUG or (_environ.get('VERBOSE', '') != '')
TESTING = 'test' in sys.argv
TRAVIS = 'TRAVIS' in _environ and os.environ["TRAVIS"] == "true"

ADMINS = (
    ('Administrator', 'example@example.com'),
)

DEFAULT_FROM_EMAIL = _environ.get('FROM_EMAIL', 'CloudPebble <cloudpebble@example.com>')

ON_CLOUDFLARE = _environ.get('CLOUDFLARE') != ''
if ON_CLOUDFLARE:
    SECURE_PROXY_SSL_HEADER = ('HTTP_CF_VISITOR', '{"scheme":"https"}')
else:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

MANAGERS = ADMINS

if TRAVIS:
    DATABASES = {
        'default': {
            'ENGINE':   'django.db.backends.postgresql_psycopg2',
            'NAME':     'travisci',
            'USER':     'postgres',
            'PASSWORD': '',
            'HOST':     'localhost',
            'PORT':     '',
        }
    }
elif not _environ.get('DATABASE_URL'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql_psycopg2',
            'NAME': 'postgres',
            'USER': 'postgres',
            'HOST': 'postgres',
            'PORT': 5432,
        }
    }
else:
    DATABASES = {
        'default': dj_database_url.config()
    }
    # Required when DATABASE_URL points at a transaction-mode pooler (e.g.
    # Supabase/Supavisor on port 6543): named server-side cursors can't span a
    # per-transaction connection checkout, so disable them. Harmless on direct
    # connections, where it just keeps .iterator() results client-side.
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True
    # psycopg2 in async/green mode (psycogreen + gevent, see gunicorn.py) can't
    # issue `SHOW client_encoding` during connect, so it relies on the server's
    # ParameterStatus message — which Supavisor in transaction mode doesn't
    # reliably send, raising "server didn't return client encoding". Pin it
    # explicitly so psycopg2 never has to read it back.
    DATABASES['default'].setdefault('OPTIONS', {})['client_encoding'] = 'UTF8'

PROJECT_PATH = os.path.dirname(os.path.abspath(__file__)) + '/../'

LANGUAGE_COOKIE_NAME = 'cloudpebble_language'

TEMPLATE_CONTEXT_PROCESSORS = (
    "django.contrib.auth.context_processors.auth",
    "django.template.context_processors.debug",
    "django.template.context_processors.i18n",
    "django.template.context_processors.media",
    "django.template.context_processors.static",
    "django.template.context_processors.tz",
    "django.contrib.messages.context_processors.messages",
    "social_django.context_processors.backends",
    "social_django.context_processors.login_redirect",
)

# Hosts/domain names that are valid for this site; required if DEBUG is False
# See https://docs.djangoproject.com/en/1.5/ref/settings/#allowed-hosts
ALLOWED_HOSTS = ['*']

# Django 4.2+ requires CSRF_TRUSTED_ORIGINS for cross-origin requests.
# Configure additional origins via CSRF_TRUSTED_ORIGINS (comma-separated).
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://localhost:8080',
]
_public_url = os.environ.get('PUBLIC_URL', '').rstrip('/')
if _public_url:
    CSRF_TRUSTED_ORIGINS.append(_public_url)

_extra_csrf_origins = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
if _extra_csrf_origins:
    CSRF_TRUSTED_ORIGINS.extend(
        origin.strip().rstrip('/')
        for origin in _extra_csrf_origins.split(',')
        if origin.strip()
    )

# Keep insertion order while removing duplicates
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys(CSRF_TRUSTED_ORIGINS))

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# In a Windows environment this must be set to your system time zone.
TIME_ZONE = 'America/New_York'

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-gb'

LANGUAGES = (
    ('en', 'English'),
    ('es', 'Spanish'),
    ('fr', 'French'),
    ('de', 'German'),
    ('zh-cn', 'Chinese (simplified'),
    ('zh-tw', 'Chinese (traditional)'),
)

LOCALE_PATHS = (os.getcwd() + "/locale",)

SITE_ID = 1

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# If you set this to False, Django will not format dates, numbers and
# calendars according to the current locale.
USE_L10N = True

# If you set this to False, Django will not use timezone-aware datetimes.
USE_TZ = True

# Absolute filesystem path to the directory that will hold user-uploaded files.
# Example: "/var/www/example.com/media/"
MEDIA_ROOT = os.getcwd() + '/user_data/build_results/'

SIMPLYJS_ROOT = os.getcwd() + '/ext/simplyjs/'
PEBBLEJS_ROOT = os.getcwd() + '/ext/pebblejs/'
C_PRELOAD_ROOT = os.getcwd() + '/c-preload/'
MODDABLE_EXAMPLES_ROOT = '/opt/pebble-examples'
C_WATCHFACE_TUTORIAL_ROOT = '/opt/c-watchface-tutorial'

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash.
# Examples: "http://example.com/media/", "http://media.example.com/"
MEDIA_URL = _environ.get('MEDIA_URL', 'http://localhost:8001/builds/')

# Absolute path to the directory static files should be collected to.
# Don't put anything in this directory yourself; store your static files
# in apps' "static/" subdirectories and in STATICFILES_DIRS.
# Example: "/var/www/example.com/static/"
STATIC_ROOT = 'staticfiles'

# URL prefix for static files.
# Example: "http://example.com/static/", "http://static.example.com/"
STATIC_URL = '/static/'

PUBLIC_URL = _environ.get('PUBLIC_URL', 'http://localhost:8000/') # This default is completely useless.

# Additional locations of static files
STATICFILES_DIRS = (
    # Put strings here, like "/home/html/static" or "C:/www/django/static".
    # Always use forward slashes, even on Windows.
    # Don't forget to use absolute paths, not relative paths.
)

# List of finder classes that know how to find static files in
# various locations.
STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'djangobower.finders.BowerFinder',
#    'django.contrib.staticfiles.finders.DefaultStorageFinder',
)

BOWER_INSTALLED_APPS = (
    'https://github.com/krisk/Fuse.git#2ec2f2c40059e135cabf2b01c8c3f96f808b8809',
    'jquery#~2.1.3',
    'underscore',
    'backbone',
    'text-encoding',
    'jshint/jshint',
    'html.sortable#~0.3.1',
    'alexgorbatchev/jquery-textext',
    'codemirror#4.2.0',
    'bluebird#3.3.4',
    'kanaka/noVNC#v0.5',
)

# Make this unique, and don't share it with anybody.
_secret_key_path = os.environ.get('SECRET_KEY_FILE', '/data/secret_key.txt')

if _environ.get('SECRET_KEY'):
    SECRET_KEY = _environ['SECRET_KEY']
elif os.path.exists(_secret_key_path):
    with open(_secret_key_path, 'r') as _f:
        SECRET_KEY = _f.read().strip()
else:
    import secrets
    SECRET_KEY = secrets.token_urlsafe(50)
    with open(_secret_key_path, 'w') as _f:
        _f.write(SECRET_KEY)
    os.chmod(_secret_key_path, 0o600)

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
#     'django.template.loaders.eggs.Loader',
)

# dj-static/Cling serves static files directly from STATIC_ROOT, no hashing needed
# if not DEBUG:
#     STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'


MIDDLEWARE = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'auth.middleware.CrossDomainSessionMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    # Uncomment the next line for simple clickjacking protection:
    # 'django.middleware.clickjacking.XFrameOptionsMiddleware',
)

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
)

SOCIAL_AUTH_PIPELINE = (
    'social_core.pipeline.social_auth.social_details',
    'social_core.pipeline.social_auth.social_uid',
    'social_core.pipeline.social_auth.auth_allowed',
    'auth.pebble.merge_user', # formerly social_core.pipeline.social_auth.social_user
    'social_core.pipeline.user.get_username',
    'social_core.pipeline.user.create_user',
    'social_core.pipeline.social_auth.associate_user',
    'auth.pebble.clear_old_login',
    'social_core.pipeline.social_auth.load_extra_data',
    'social_core.pipeline.user.user_details'
)

SOCIAL_AUTH_PEBBLE_KEY = _environ.get('PEBBLE_AUTH_KEY', 'bab3e760ede6e592517682837a054beff83c8a80725d8e13fa122e8e87e99c20')
SOCIAL_AUTH_PEBBLE_SECRET = _environ.get('PEBBLE_AUTH_SECRET', '7bf8b96fd736f3a2ac12d472b0703d44503441913626deed86180c0f47dcbb08')

SOCIAL_AUTH_PEBBLE_ROOT_URL = _environ.get('PEBBLE_AUTH_URL', None)
PEBBLE_AUTH_ADMIN_TOKEN = _environ.get('PEBBLE_AUTH_ADMIN_TOKEN', None)

SHOULD_BE_SECURE = _environ.get('EXPECT_SSL', '') != ''

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = SHOULD_BE_SECURE
CSRF_COOKIE_SECURE = SHOULD_BE_SECURE

SOCIAL_AUTH_PEBBLE_REQUIRED = 'PEBBLE_AUTH_REQUIRED' in _environ

ROOT_URLCONF = 'cloudpebble.urls'

# Python dotted path to the WSGI application used by Django's runserver.
WSGI_APPLICATION = 'cloudpebble.wsgi.application'

# Templates configuration (Django 1.8+)
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.i18n',
                'django.template.context_processors.media',
                'django.template.context_processors.static',
                'django.template.context_processors.tz',
                'social_django.context_processors.backends',
                'social_django.context_processors.login_redirect',
            ],
        },
    },
]

# Default auto field (Django 3.2+)
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'


TEMPLATE_DIRS = (
    # Put strings here, like "/home/html/django_templates" or "C:/www/django/templates".
    # Always use forward slashes, even on Windows.
    # Don't forget to use absolute paths, not relative paths.
)

INSTALLED_APPS = (
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Uncomment the next line to enable the admin:
    #'django.contrib.admin',
    # Uncomment the next line to enable admin documentation:
    # 'django.contrib.admindocs',
    'social_django',
    'ide',
    'auth.apps.CloudPebbleAuthConfig',
    'root',
    'qr',
    # 'south',  # Removed for Django 4.2
    # 'djcelery',  # Removed for Django 4.2
    'registration',
    'djangobower',
)

# This logging config prints:
# INFO logs from django
# INFO or DEBUG logs from 'ide', depending on whether DEBUG=True
# all WARNING logs from any sources
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)s] %(message)s",
            'datefmt': "%d/%b/%Y %H:%M:%S"
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose'
        }
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True
        },
        'ide': {
            'handlers': ['console'],
            'level': 'DEBUG' if VERBOSE else 'INFO',
            'propagate': True
        },
        'root': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': True
        },
        '': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False
        }
    }
}

if TESTING:
    # Many tests make deliberately broken requests. If this line is not present,
    # the log output during tests gets flooded with 'expected' exceptions.
    LOGGING['loggers']['django.request'] = {'level': 'CRITICAL'}

REDIS_URL = _environ.get('REDIS_URL', None) or _environ.get('REDISCLOUD_URL', 'redis://redis:6379')


def _redis_db_url(redis_url, db_index):
    parsed_url = urlsplit(redis_url)
    if parsed_url.scheme != 'redis':
        return redis_url.rstrip('/') + '/' + str(db_index)
    return urlunsplit(parsed_url._replace(path='/' + str(db_index)))


# Celery 5.x configuration
if REDIS_URL.startswith('rediss://'):
    CELERY_BROKER_URL = REDIS_URL
else:
    CELERY_BROKER_URL = _redis_db_url(REDIS_URL, 1)
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ['pickle']
CELERY_TASK_SERIALIZER = 'pickle'
CELERY_RESULT_SERIALIZER = 'pickle'

if REDIS_URL.startswith('rediss://'):
    import ssl
    CELERY_BROKER_USE_SSL = {'ssl_cert_reqs': ssl.CERT_REQUIRED}
    CELERY_REDIS_BACKEND_USE_SSL = {'ssl_cert_reqs': ssl.CERT_REQUIRED}

CELERY_TASK_TIME_LIMIT = int(_environ.get('CELERYD_TASK_TIME_LIMIT', 620))
CELERY_TASK_SOFT_TIME_LIMIT = int(_environ.get('CELERYD_TASK_SOFT_TIME_LIMIT', 600))

CELERY_BROKER_POOL_LIMIT = int(_environ.get('BROKER_POOL_LIMIT', 10))

LOGIN_REDIRECT_URL = '/ide/'

LOGIN_URL = '/#login'

FILE_STORAGE = os.getcwd() + '/user_data/'

CHROOT_ROOT = None

DEFAULT_TEMPLATE = None

EXPORT_DIRECTORY = os.getcwd() + '/user_data/export/'

EXPORT_ROOT = _environ.get('EXPORT_ROOT', PUBLIC_URL.rstrip('/') + '/export/')

# Cloud Dev Connection / legacy GitHub auth app
GITHUB_DEV_CLIENT_ID = _environ.get('GITHUB_DEV_CLIENT_ID', _environ.get('GITHUB_ID', ''))
GITHUB_DEV_CLIENT_SECRET = _environ.get('GITHUB_DEV_CLIENT_SECRET', _environ.get('GITHUB_SECRET', ''))

# GitHub Repo Sync auth app
GITHUB_SYNC_CLIENT_ID = _environ.get('GITHUB_SYNC_CLIENT_ID', '')
GITHUB_SYNC_CLIENT_SECRET = _environ.get('GITHUB_SYNC_CLIENT_SECRET', '')

GITHUB_HOOK_BASE_URL = _environ.get('GITHUB_HOOK_URL', '')
GITHUB_HOOK_TEMPLATE = (GITHUB_HOOK_BASE_URL.rstrip('/') if GITHUB_HOOK_BASE_URL else PUBLIC_URL.rstrip('/')) + '/ide/project/%(project)d/github/push_hook?key=%(key)s'

SDK2_PEBBLE_WAF = _environ.get('SDK2_PEBBLE_WAF', '/sdk2/pebble/waf')
SDK3_PEBBLE_WAF = _environ.get('SDK3_PEBBLE_WAF', '/sdk3/pebble/waf')

NPM_BINARY = _environ.get('NPM_BINARY', 'npm')

# Toolchain now comes from pebble-tool SDK, available in PATH
ARM_CS_TOOLS = _environ.get('ARM_CS_TOOLS', '')

TD_URL = _environ.get('TD_URL', None)
TD_ENABLED = _environ.get('TD_ENABLED', False)

MAILCHIMP_API_KEY = _environ.get('MAILCHIMP_API_KEY', None)
MAILCHIMP_LIST_ID = _environ.get('MAILCHIMP_LIST_ID', None)

AWS_ENABLED = 'AWS_ENABLED' in _environ
AWS_ACCESS_KEY_ID = _environ.get('AWS_ACCESS_KEY_ID', None)
AWS_SECRET_ACCESS_KEY = _environ.get('AWS_SECRET_ACCESS_KEY', None)

AWS_S3_SOURCE_BUCKET = _environ.get('AWS_S3_SOURCE_BUCKET', 'source.cloudpebble.net')
AWS_S3_BUILDS_BUCKET = _environ.get('AWS_S3_BUILDS_BUCKET', 'builds.cloudpebble.net')
AWS_S3_EXPORT_BUCKET = _environ.get('AWS_S3_EXPORT_BUCKET', 'export.cloudpebble.net')
AWS_S3_HOST = _environ.get('AWS_S3_HOST', None)
AWS_S3_FAKE_S3 = _environ.get('AWS_S3_FAKE_S3', None) or None
AWS_S3_ENDPOINT_URL = _environ.get('AWS_S3_ENDPOINT_URL', None) or None

TYPOGRAPHY_CSS = _environ.get('TYPOGRAPHY_CSS', None)

LIBPEBBLE_PROXY = _environ.get('LIBPEBBLE_PROXY', 'wss://cloudpebble-proxy.repebble.com/tool')

CLOUDPEBBLE_PROXY = _environ.get('CLOUDPEBBLE_PROXY', 'wss://cloudpebble-proxy.repebble.com/tool')

YCM_URLS = _environ.get('YCM_URLS', 'http://localhost:8002/').split(',')
YCMD_PUBLIC_URL = _environ.get('YCMD_PUBLIC_URL', None) or None
COMPLETION_CERTS = _environ.get('COMPLETION_CERTS', os.getcwd() + '/completion-certs.crt')

QEMU_URLS = _environ.get('QEMU_URLS', 'http://qemu/').split(',')
QEMU_PUBLIC_URL = _environ.get('QEMU_PUBLIC_URL', None) or _public_url or None
QEMU_LAUNCH_AUTH_HEADER = _environ.get('QEMU_LAUNCH_AUTH_HEADER', 'secret')
QEMU_LAUNCH_TIMEOUT = int(_environ.get('QEMU_LAUNCH_TIMEOUT', 25))

AGENT_URL = _environ.get('AGENT_URL', '')
# No default: an empty shared secret fails closed on both sides rather than letting a
# guessable one ('secret') authenticate a public, quota-spending endpoint.
# Generate with `openssl rand -hex 32`.
AGENT_AUTH_HEADER = _environ.get('AGENT_AUTH_HEADER', '')
# Feature flag: comma-separated user ids allowed to use the AI agent panel, or '*' for
# everybody. Kept as raw strings -- ide.api.agent._check_enabled stringifies both sides,
# and int() here would blow up at import time on the documented wildcard.
AGENT_ENABLED_USERS = _environ.get('AGENT_ENABLED_USERS', '').replace(',', ' ').split()
AGENT_MAX_TURNS_PER_DAY = int(_environ.get('AGENT_MAX_TURNS_PER_DAY', 50))
# Gap timeout on the agent VM's event stream. Slow models go quiet for minutes
# mid-generation; 900s cut a real turn off and reported it as a service outage.
AGENT_TURN_READ_TIMEOUT = int(_environ.get('AGENT_TURN_READ_TIMEOUT', 1800))
# How long a session may sit in 'running' with no new events before it is treated
# as abandoned and healed. See ide.api.agent.heal_if_stale. Must stay above the
# read timeout: below it this measures a model thinking, not a relay dying, and
# at 240s it killed live turns.
AGENT_STALE_TURN_SECONDS = int(_environ.get('AGENT_STALE_TURN_SECONDS',
                                            AGENT_TURN_READ_TIMEOUT + 120))

# Free tier: what a user gets before they bring their own provider. Deliberately
# a cheap text-only model plus a vision describer -- a model that cannot see is
# told so and stays honest, where a weak vision model invents what it "saw".
AGENT_FREE_MODEL = _environ.get('AGENT_FREE_MODEL', 'deepseek-v4-flash')
AGENT_FREE_API_BASE = _environ.get('AGENT_FREE_API_BASE', 'https://api.deepseek.com/anthropic')
AGENT_FREE_API_KEY = _environ.get('AGENT_FREE_API_KEY', '')
# Describer, used whenever the acting model has no vision of its own.
AGENT_VISION_API_BASE = _environ.get('AGENT_VISION_API_BASE', 'https://openrouter.ai/api')
AGENT_VISION_API_KEY = _environ.get('AGENT_VISION_API_KEY', '')
AGENT_VISION_MODEL = _environ.get('AGENT_VISION_MODEL', 'mistralai/mistral-small-3.2-24b-instruct')
# Anthropic sign-in. Empty disables it, which is the correct production value:
# Anthropic offers no self-serve OAuth client registration, so the only id that
# works belongs to Claude Code, and the consent screen would name that instead of
# this app. Set it only for local testing.
AGENT_ANTHROPIC_OAUTH_CLIENT_ID = _environ.get('AGENT_ANTHROPIC_OAUTH_CLIENT_ID', '')

PHONE_SHORTURL = _environ.get('PHONE_SHORTURL', 'pbl.zip/sensors')

FIREBASE_PROJECT_ID = _environ.get('FIREBASE_PROJECT_ID', 'coreapp-ce061')

APPSTORE_API_BASE = _environ.get('APPSTORE_API_BASE', 'https://appstore-api.repebble.com')

REPEBBLE_SESSION_SECRET = _environ.get('REPEBBLE_SESSION_SECRET', _environ.get('DASHBOARD_SESSION_SECRET', ''))

WAF_NODE_PATH = _environ.get('WAF_NODE_PATH', None)

# import djcelery  # Removed for Django 4.2
# djcelery.setup_loader()  # Removed for Django 4.2

# import local settings
try:
    from settings_local import *
except ImportError:
    print("No local settings overrides.")
    pass

socket.setdefaulttimeout(int(_environ.get("DEFAULT_SOCKET_TIMEOUT", 10)))

# Don't keep these hanging around in the environment.
if not DEBUG:
    for key in _environ.keys():
        # We need these ones to run.
        if key in {'PATH', 'TZ', 'RUN_MAIN', 'CELERY_LOADER', 'DJANGO_SETTINGS_MODULE', 'DEBUG', 'C_FORCE_ROOT'}:
            continue
        del _environ[key]
