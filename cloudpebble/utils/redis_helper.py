__author__ = 'katharine'

import redis
from django.conf import settings

# socket_keepalive lets the OS reap connections whose peer has gone away, and
# health_check_interval makes redis-py ping idle connections so stale ones are
# recycled instead of accumulating. Defence in depth for long-lived SSE pubsub
# streams (ide.api.sse); the keepalive heartbeat there is the primary safeguard.
# Note: deliberately no global socket_timeout — blocking ops (e.g. brpop) use
# this client and a read timeout would break them.
redis_client = redis.from_url(
    settings.REDIS_URL,
    socket_keepalive=True,
    health_check_interval=30,
)
