"""SessionStore backed by the CloudPebble transcript routes.

The agent box keeps nothing between turns: the transcript lives in CloudPebble's
AgentTranscript table and is hydrated at the start of each turn.

Wire contract with ide/api/agent.py:
    POST /ide/agent/transcript/<sdk_session_id>   {project_key, subpath, entries: [...]}
    GET  /ide/agent/transcript/<sdk_session_id>?subpath=...   -> {entries: [...]}
                                                              -> 404 if never written
Both authenticate with the scoped agent bearer token.

Only append() and load() are implemented; the rest of the SessionStore protocol is
optional and we never list, fork or delete sessions from here.
"""

import asyncio
import logging

import requests

logger = logging.getLogger(__name__)

TIMEOUT = 30


class CloudPebbleSessionStore(object):
    def __init__(self, base_url, token):
        self.base = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers['Authorization'] = 'Bearer %s' % token

    def _url(self, key):
        return '%s/ide/agent/transcript/%s' % (self.base, key['session_id'])

    async def append(self, key, entries):
        def _post():
            r = self.session.post(self._url(key), json={
                'project_key': key['project_key'],
                'subpath': key.get('subpath') or '',
                'entries': entries,
            }, timeout=TIMEOUT)
            r.raise_for_status()

        await asyncio.to_thread(_post)

    async def load(self, key):
        def _get():
            r = self.session.get(self._url(key),
                                 params={'subpath': key.get('subpath') or ''},
                                 timeout=TIMEOUT)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json().get('entries') or None

        return await asyncio.to_thread(_get)
