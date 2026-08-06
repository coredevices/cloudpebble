import json
import logging
import re
from urllib.parse import quote as http_quote

import requests as http_requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_safe

from ide.utils.github_urls import parse_github_source

logger = logging.getLogger(__name__)

PLATFORM_DISPLAY_NAMES = {
    'aplite': 'OG Pebble/Steel',
    'basalt': 'Time/Time Steel',
    'chalk': 'Time Round',
    'diorite': '2/2HR',
    'emery': 'Time 2',
    'flint': '2 Duo',
    'gabbro': 'Round 2',
}

# Default platform preference (first match wins)
PLATFORM_PREFERENCE = ['emery', 'basalt', 'chalk', 'diorite', 'aplite', 'gabbro', 'flint']


def _fetch_app_info(app_id):
    """Fetch app metadata from the App Store API."""
    url = '%s/api/v1/apps/id/%s?hardware=basalt' % (settings.APPSTORE_API_BASE, app_id)
    resp = http_requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json().get('data', [])
    if not data:
        return None
    return data[0]


def _get_supported_platforms(app_info):
    """Extract list of supported platform names from compatibility object."""
    compatibility = app_info.get('compatibility', {})
    supported = []
    for platform in PLATFORM_PREFERENCE:
        if compatibility.get(platform, {}).get('supported'):
            supported.append(platform)
    return supported


def _get_pbw_url(app_info):
    """Get the PBW file URL from the latest release."""
    latest = app_info.get('latest_release', {})
    pbw_file = latest.get('pbw_file', '')
    if not pbw_file:
        return None
    if pbw_file.startswith('http'):
        return pbw_file
    return '%s%s' % (settings.APPSTORE_API_BASE, pbw_file)


def _github_import_url(source):
    """Best import deep link for an appstore 'source' field, or ''.

    The field may be prose, so the token containing github.com is picked out
    and handed to the import URL parser — the single authority on which
    shapes the importer accepts (tree/blob/commit deep links included).
    Anything it rejects (ports, /releases/, unrecognized casing) degrades to
    a plain repository link when a user/repo pair is discernible, rather
    than a deep link that would fail to import."""
    if not source or 'github.com' not in source.lower():
        return ''
    token = next((tok.strip('\'"<>(),.;:') for tok in source.split()
                  if 'github.com' in tok.lower()), '')
    parsed = parse_github_source(token)
    if parsed:
        pieces = [parsed.user, parsed.project]
        if parsed.kind:
            pieces += [parsed.kind, parsed.refpath]
        return '/ide/import/github/%s' % http_quote('/'.join(pieces), safe='/')
    gh_match = re.search(r"github\.com/([\w.-]+/[\w.-]+)", token)
    if gh_match:
        return '/ide/import/github/%s' % gh_match.group(1).removesuffix('.git')
    return ''


@require_safe
@ensure_csrf_cookie
def run_app(request, app_id):
    if not request.user.is_authenticated:
        return render(request, 'ide/run_login.html', {
            'app_id': app_id,
            'next_url': request.get_full_path(),
        })

    app_info = _fetch_app_info(app_id)
    if not app_info:
        raise Http404("App not found")

    supported_platforms = _get_supported_platforms(app_info)
    if not supported_platforms:
        raise Http404("App has no supported platforms")

    # Default to emery if supported, else first in preference order
    default_platform = supported_platforms[0]

    # Build platform list with display names, sorted alphabetically by platform codename
    platform_choices = sorted(
        [{'id': p, 'name': PLATFORM_DISPLAY_NAMES.get(p, p)} for p in supported_platforms],
        key=lambda x: x['id']
    )

    try:
        token = request.user.social_auth.get(provider='pebble').extra_data['access_token']
    except Exception:
        token = ''
    firebase_token = request.session.get('firebase_id_token', '')
    firebase_token_exp = request.session.get('firebase_id_token_exp', '')

    app_title = app_info.get('title', 'Unknown App')
    slug = re.sub(r'[^a-z0-9]+', '-', app_title.lower()).strip('-')
    app_store_url = 'https://apps.repebble.com/%s_%s' % (slug, app_id)

    app_type = app_info.get('type', 'watchapp')
    app_hearts = app_info.get('hearts', 0)
    app_uuid = app_info.get('uuid', '')

    github_import_url = _github_import_url(app_info.get('source') or '')

    return render(request, 'ide/run.html', {
        'app_id': app_id,
        'app_title': app_title,
        'app_author': app_info.get('author', 'Unknown'),
        'app_store_url': app_store_url,
        'app_type': app_type,
        'app_hearts': app_hearts,
        'app_uuid': app_uuid,
        'github_import_url': github_import_url,
        'platform_choices': platform_choices,
        'platform_choices_json': json.dumps(platform_choices),
        'supported_platforms_json': json.dumps(supported_platforms),
        'default_platform': default_platform,
        'token': token,
        'firebase_token': firebase_token,
        'firebase_token_exp': firebase_token_exp,
        'libpebble_proxy': json.dumps(settings.LIBPEBBLE_PROXY),
        'cloudpebble_proxy': json.dumps(settings.CLOUDPEBBLE_PROXY),
        'phone_shorturl': settings.PHONE_SHORTURL,
    })


@require_safe
@login_required
def run_app_pbw(request, app_id):
    """Proxy the PBW download from the App Store API to avoid CORS issues."""
    app_info = _fetch_app_info(app_id)
    if not app_info:
        raise Http404("App not found")

    pbw_url = _get_pbw_url(app_info)
    if not pbw_url:
        raise Http404("No PBW available for this app")

    resp = http_requests.get(pbw_url, timeout=30, stream=True)
    resp.raise_for_status()

    response = HttpResponse(
        resp.iter_content(chunk_size=8192),
        content_type='application/octet-stream',
    )
    response['Content-Disposition'] = 'attachment; filename="%s.pbw"' % app_id
    if resp.headers.get('Content-Length'):
        response['Content-Length'] = resp.headers['Content-Length']
    return response


@login_required
def run_app_users_me(request, app_id):
    """Proxy GET /api/v1/users/me to appstore API (for voted_ids)."""
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header:
        return JsonResponse({'error': 'No authorization'}, status=401)

    url = '%s/api/v1/users/me' % settings.APPSTORE_API_BASE
    headers = {'Authorization': auth_header, 'Content-Type': 'application/json'}
    resp = http_requests.get(url, headers=headers, timeout=10)
    return HttpResponse(resp.content, status=resp.status_code, content_type='application/json')


@csrf_exempt
@login_required
def run_app_heart(request, app_id):
    """Proxy heart GET/POST/DELETE to appstore API (avoids CORS)."""
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header:
        return JsonResponse({'error': 'No authorization'}, status=401)

    url = '%s/api/v1/apps/id/%s/heart' % (settings.APPSTORE_API_BASE, app_id)
    headers = {'Authorization': auth_header, 'Content-Type': 'application/json'}

    if request.method == 'POST':
        resp = http_requests.post(url, headers=headers, timeout=10)
    elif request.method == 'DELETE':
        resp = http_requests.delete(url, headers=headers, timeout=10)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    return HttpResponse(resp.content, status=resp.status_code, content_type='application/json')
