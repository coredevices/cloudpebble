import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse
from django.views.decorators.http import require_GET

from utils.redis_helper import redis_client

logger = logging.getLogger(__name__)


class SSEEventStream:
    def __init__(self, project_id):
        self.channel = 'project_events:{}'.format(project_id)
        self.pubsub = redis_client.pubsub()
        self.pubsub.subscribe(self.channel)

    def __iter__(self):
        try:
            for message in self.pubsub.listen():
                if message['type'] == 'message':
                    data = message['data']
                    if isinstance(data, bytes):
                        data = data.decode('utf-8')
                    parsed = json.loads(data)
                    event_type = parsed.pop('type', 'message')
                    yield 'event: {}\ndata: {}\n\n'.format(event_type, json.dumps(parsed))
        except GeneratorExit:
            pass
        finally:
            try:
                self.pubsub.unsubscribe(self.channel)
                self.pubsub.close()
            except Exception:
                pass


@login_required
@require_GET
def project_events(request, project_id):
    from ide.models.project import Project
    project = Project.objects.filter(pk=project_id, owner=request.user)
    if not project.exists():
        from django.http import HttpResponseNotFound
        return HttpResponseNotFound()

    response = StreamingHttpResponse(
        SSEEventStream(project_id),
        content_type='text/event-stream',
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response