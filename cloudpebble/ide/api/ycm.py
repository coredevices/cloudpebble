from concurrent.futures import ThreadPoolExecutor
import json
import logging
import random

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from urllib.parse import urlparse

from ide.models.project import Project
from utils.jsonview import json_view

__author__ = 'katharine'

logger = logging.getLogger(__name__)


@login_required
@require_POST
@json_view
def init_autocomplete(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    source_files = [f for f in project.source_files.select_related('project') if f.is_editable_text]

    def read(f):
        content = f.get_contents()
        # Ensure content is string, not bytes
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        return f.project_path, content

    # One object-store GET per file; done one by one they added seconds to every
    # editor open. boto3 clients are thread-safe (and gevent-patched under gunicorn).
    with ThreadPoolExecutor(max_workers=8) as pool:
        file_contents = dict(pool.map(read, source_files))

    identifiers = [(f.kind, i.resource_id) for f in project.resources.prefetch_related('identifiers')
                   for i in f.identifiers.all()]

    appkey_names = [k for k, v in project.get_parsed_appkeys()]

    request = {
        'files': file_contents,
        'platforms': request.POST.get('platforms', 'aplite').split(','),
        'sdk': request.POST.get('sdk', '2'),
        'messagekeys': appkey_names,
        'resources': identifiers,
        'dependencies': project.get_dependencies()
    }
    # Let's go!
    return _spin_up_server(request)


def _choose_ycm_server():
    return random.choice(settings.YCM_URLS)


def _spin_up_server(request):
    servers = set(settings.YCM_URLS)
    while len(servers) > 0:
        server = random.choice(list(servers))
        servers.remove(server)
        try:
            result = requests.post('%sspinup' % server, json.dumps(request), headers={'Content-Type': 'application/json'})
            if result.ok:
                response = result.json()
                if response['success']:
                    # Use YCMD_PUBLIC_URL if set, otherwise derive from PUBLIC_URL
                    if getattr(settings, 'YCMD_PUBLIC_URL', None):
                        public_ycm = settings.YCMD_PUBLIC_URL.rstrip('/') + '/'
                    else:
                        public_url = getattr(settings, 'PUBLIC_URL', server)
                        public_ycm = public_url.rstrip('/') + '/ycmd/'
                    secure = public_ycm.startswith('https')
                    scheme = "wss" if secure else "ws"
                    ws_server = urlparse(public_ycm)._replace(scheme=scheme).geturl()
                    return {
                        'uuid': response['uuid'],
                        'server': ws_server,
                        'secure': secure,
                        'libraries': response.get('libraries', {}),
                        'npm_error': response.get('npm_error', None)
                    }

        except (requests.RequestException, ValueError):
            import traceback
            traceback.print_exc()
        logger.warning("Server %s failed; trying another.", server)
    # No servers responded — fail gracefully so the frontend can skip code completion.
    return {'success': False, 'error': 'No YCM servers available'}
