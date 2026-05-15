import json
import logging

from utils.redis_helper import redis_client

logger = logging.getLogger(__name__)


def publish_event(project_id, event_type, **kwargs):
    data = {'type': event_type}
    data.update(kwargs)
    channel = 'project_events:{}'.format(project_id)
    redis_client.publish(channel, json.dumps(data))
    logger.debug("Published %s to %s", event_type, channel)