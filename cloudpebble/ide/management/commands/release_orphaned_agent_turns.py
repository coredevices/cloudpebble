"""Release agent turns whose relay died with the process that owned it.

A turn is relayed by a thread inside a web worker, so a deploy, a restart or a
crash takes it with no terminal event: the session stays 'running', the composer
stays disabled, every new message is refused with "the agent is already working",
and nothing recovers it until heal_if_stale's timeout -- over half an hour.

Nothing relayed by *this* process can survive its restart, so at startup every
session still marked running is by definition orphaned. Run from docker_start.sh
before the server binds.
"""
from django.core.management.base import BaseCommand

from ide.api.agent import _append
from ide.models.agent import AgentSession


class Command(BaseCommand):
    help = "Mark agent sessions left 'running' by a dead relay as failed."

    def handle(self, *args, **options):
        orphans = list(AgentSession.objects.filter(status='running'))
        for session in orphans:
            session.status = 'error'
            session.save(update_fields=['status'])
            # A terminal event, so an open browser re-enables its composer rather
            # than sitting on a spinner that will never resolve.
            _append(session, 'system', 'error', {
                'message': "The agent was interrupted by a server restart. "
                           "Say continue and it will pick up where it left off.",
                'kind': 'relay',
            })
        self.stdout.write("released %d orphaned agent turn(s)" % len(orphans))
