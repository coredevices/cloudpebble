import json

from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import TestCase, RequestFactory, override_settings

from ide.models.agent import AgentSession
from ide.models.project import Project
from utils import agent_token


class FakeRedis(object):
    """ Just enough redis for the token store: bytes out of get(), like the real thing. """

    def __init__(self):
        self.store = {}
        self.ttl = {}

    def set(self, key, value, ex=None):
        self.store[key] = value.encode('utf-8') if isinstance(value, str) else value
        self.ttl[key] = ex

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)
        self.ttl.pop(key, None)

    def incr(self, key):
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = value
        return value

    def expire(self, key, seconds):
        self.ttl[key] = seconds


@mock.patch.object(agent_token, 'redis_client', new_callable=FakeRedis)
class TestAgentToken(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='agentuser', password='x')
        self.other_user = User.objects.create_user(username='otheruser', password='x')
        self.project = Project.objects.create(owner=self.user, name='agentproject')
        self.other_project = Project.objects.create(owner=self.user, name='otherproject')
        self.session = AgentSession.objects.create(project=self.project, user=self.user)
        self.factory = RequestFactory()

    def _request(self, token):
        return self.factory.get('/', HTTP_AUTHORIZATION='Bearer %s' % token)

    @staticmethod
    def _view(request, project_id=None):
        return (request.user, request.agent_project, request.agent_session)

    def test_mint_resolve_roundtrip(self, redis):
        token = agent_token.mint(self.user, self.project, self.session)
        self.assertGreater(len(token), 20)
        user, project, session = agent_token.resolve(token)
        self.assertEqual(user, self.user)
        self.assertEqual(project, self.project)
        self.assertEqual(session, self.session)
        self.assertEqual(redis.ttl['agent-token-%s' % token], agent_token.TOKEN_TTL)
        self.assertEqual(json.loads(redis.store['agent-token-%s' % token])['project_id'], self.project.id)

    def test_expired_token_is_rejected(self, redis):
        token = agent_token.mint(self.user, self.project, self.session)
        redis.delete('agent-token-%s' % token)  # what the TTL does for us in prod
        self.assertIsNone(agent_token.resolve(token))
        with self.assertRaises(PermissionDenied):
            agent_token.agent_token_required(self._view)(self._request(token), project_id=str(self.project.id))

    def test_unknown_and_malformed_tokens_are_rejected(self, redis):
        self.assertIsNone(agent_token.resolve('never-minted'))
        self.assertIsNone(agent_token.resolve(''))
        self.assertIsNone(agent_token.resolve('has spaces and *'))
        with self.assertRaises(PermissionDenied):
            agent_token.agent_token_required(self._view)(self.factory.get('/'), project_id='1')

    def test_decorator_sets_user_and_project(self, redis):
        token = agent_token.mint(self.user, self.project, self.session)
        user, project, session = agent_token.agent_token_required(self._view)(
            self._request(token), project_id=str(self.project.id))
        self.assertEqual((user, project, session), (self.user, self.project, self.session))

    def test_wrong_project_is_rejected(self, redis):
        token = agent_token.mint(self.user, self.project, self.session)
        with self.assertRaises(PermissionDenied):
            agent_token.agent_token_required(self._view)(
                self._request(token), project_id=str(self.other_project.id))

    def test_scope_revalidated_against_db(self, redis):
        token = agent_token.mint(self.user, self.project, self.session)
        self.project.owner = self.other_user
        self.project.save()
        self.assertIsNone(agent_token.resolve(token))

    @override_settings(AGENT_MAX_TURNS_PER_DAY=3)
    def test_daily_turn_cap(self, redis):
        self.assertEqual([agent_token.consume_turn(self.user) for _ in range(4)],
                         [True, True, True, False])
        # Other users have their own allowance, and the counter expires on its own.
        self.assertTrue(agent_token.consume_turn(self.other_user))
        key = [k for k in redis.ttl if k.startswith('agent-turns-%s-' % self.user.id)][0]
        self.assertGreater(redis.ttl[key], 0)
        self.assertLessEqual(redis.ttl[key], 86460)
