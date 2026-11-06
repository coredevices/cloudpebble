"""Agent service: the Claude Agent SDK loop behind three endpoints.

Not public. CloudPebble calls it with a shared secret in the Authorization header,
exactly like it calls the qemu controller.

    POST /turn    {session_id, project_id, cp_token, cp_base_url, emulator, message,
                   sdk_session_id?}  -> SSE stream of agent events
    POST /cancel  {session_id}
    GET  /health
"""

import asyncio
import hmac
import json
import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent_loop import run_turn

logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO'),
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')
logger = logging.getLogger(__name__)

AUTH = os.environ.get('AGENT_AUTH_HEADER', '')

app = FastAPI()

# session_id -> asyncio.Event, set by /cancel, checked by the turn loop.
_cancels = {}


def _check_auth(request):
    if not AUTH:
        raise HTTPException(500, 'AGENT_AUTH_HEADER is not configured')
    if not hmac.compare_digest(request.headers.get('authorization', ''), AUTH):
        raise HTTPException(403, 'forbidden')


@app.get('/health')
async def health():
    return {'ok': True}


@app.post('/cancel')
async def cancel(request: Request):
    _check_auth(request)
    body = await request.json()
    event = _cancels.get(str(body.get('session_id')))
    if event is not None:
        event.set()
    return {'ok': True, 'cancelled': event is not None}


@app.post('/turn')
async def turn(request: Request):
    _check_auth(request)
    body = await request.json()
    for field in ('session_id', 'project_id', 'cp_token', 'cp_base_url', 'message'):
        if not body.get(field):
            raise HTTPException(400, 'missing %s' % field)

    session_id = str(body['session_id'])
    event = asyncio.Event()
    _cancels[session_id] = event

    async def stream():
        try:
            async for envelope in run_turn(
                project_id=body['project_id'],
                cp_token=body['cp_token'],
                cp_base_url=body['cp_base_url'],
                emulator=body.get('emulator'),
                message=body['message'],
                sdk_session_id=body.get('sdk_session_id'),
                # Keeps the CLI's config/transcript dir stable across turns, which
                # is what lets prefix-caching providers hit their cache.
                session_key=session_id,
                provider=body.get('provider'),
                cancel=event,
            ):
                yield 'data: %s\n\n' % json.dumps(envelope)
        finally:
            _cancels.pop(session_id, None)

    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache',
                                      'X-Accel-Buffering': 'no'})
