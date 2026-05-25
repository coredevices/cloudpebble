import json
import logging

import redis as redis_lib
from utils.redis_helper import redis_client

logger = logging.getLogger(__name__)


def publish_event(project_id, event_type, **kwargs):
    data = {'type': event_type}
    data.update(kwargs)
    channel = 'project_events:{}'.format(project_id)
    try:
        redis_client.publish(channel, json.dumps(data))
    except (redis_lib.RedisError, redis_lib.ConnectionError, ConnectionError):
        logger.warning("Failed to publish %s to %s (Redis unavailable)", event_type, channel, exc_info=True)
        return
    logger.debug("Published %s to %s", event_type, channel)