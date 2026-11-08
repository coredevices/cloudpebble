import datetime
import json
import threading
import time

from unittest import mock

import requests

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from ide.api.agent import (STALE_TURN_SECONDS, _append, _check_enabled, _emulator_spec,
                           _iter_sse, _keepalive, _superseded, heal_if_stale)
from ide.models.agent import AgentCredential, AgentMessage, AgentSession
from ide.models.project import Project
from utils import agent_token
from utils.jsonview import BadRequest, InternalServerError

from tests.test_agent_token import FakeRedis


class FakeResponse:
    """Just enough of requests.Response for _iter_sse."""

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)


class AgentGateTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='agentuser', password='x')

    @override_settings(AGENT_ENABLED_USERS=[])
    def test_empty_flag_allows_nobody(self):
        with self.assertRaises(PermissionDenied):
            _check_enabled(self.user)

    def test_accepts_the_settings_list_of_ints(self):
        with override_settings(AGENT_ENABLED_USERS=[self.user.id]):
            _check_enabled(self.user)
        with override_settings(AGENT_ENABLED_USERS=[self.user.id + 1]):
            with self.assertRaises(PermissionDenied):
                _check_enabled(self.user)

    @override_settings(AGENT_ENABLED_USERS='*')
    def test_star_allows_everybody(self):
        _check_enabled(self.user)

    def test_csv_matches_only_listed_ids(self):
        with override_settings(AGENT_ENABLED_USERS=' %d , 999 ' % self.user.id):
            _check_enabled(self.user)
        # A user id that is a substring of a listed one must not slip through.
        with override_settings(AGENT_ENABLED_USERS='%d0' % self.user.id):
            with self.assertRaises(PermissionDenied):
                _check_enabled(self.user)


class IterSSETest(TestCase):
    def test_parses_data_lines_and_skips_noise(self):
        events = list(_iter_sse(FakeResponse([
            ': keepalive',
            '',
            'event: message',
            'data: {"seq": 1, "role": "assistant", "type": "text", "data": {"text": "hi"}}',
            '',
            'data: not json',
            'data:',
            'data: {"seq": 2, "role": "system", "type": "done", "data": {"turn_count": 1}}',
        ])))
        assert [e['seq'] for e in events] == [1, 2], events
        assert events[0]['data']['text'] == 'hi'
        assert events[1]['type'] == 'done'


class EmulatorSpecTest(TestCase):
    """The agent VM dials whatever descriptor it is handed, so this is a trust boundary."""

    GOOD = json.dumps({'uuid': 'deadbeefdeadbeefdeadbeefdeadbeef', 'token': 'abc123!'})

    @override_settings(QEMU_PUBLIC_URL='https://cloudpebble-dev.exe.xyz/')
    def test_builds_the_url_itself(self):
        spec = _emulator_spec(self.GOOD)
        self.assertEqual(spec, {
            'uuid': 'deadbeefdeadbeefdeadbeefdeadbeef',
            'token': 'abc123!',
            'platform': '',
            'ws_url': 'wss://cloudpebble-dev.exe.xyz/qemu/deadbeefdeadbeefdeadbeefdeadbeef/ws/phone',
        })

    @override_settings(QEMU_PUBLIC_URL='https://cloudpebble-dev.exe.xyz/')
    def test_the_platform_is_passed_through_but_only_if_it_is_real(self):
        # It reaches the model's context and decides the layout it designs for,
        # so a made-up watch is worse than no watch at all.
        def platform_of(value):
            return _emulator_spec(json.dumps({
                'uuid': 'deadbeefdeadbeefdeadbeefdeadbeef', 'token': 'x',
                'platform': value}))['platform']

        self.assertEqual(platform_of('emery'), 'emery')
        self.assertEqual(platform_of('pretendo'), '')
        self.assertEqual(platform_of('<script>'), '')
        self.assertEqual(platform_of(None), '')

    @override_settings(QEMU_PUBLIC_URL='https://cloudpebble-dev.exe.xyz/')
    def test_a_caller_supplied_url_is_dropped(self):
        # The SSRF shape: ws_url/base_url/url pointing at the loop box's own network.
        spec = _emulator_spec(json.dumps({
            'uuid': 'deadbeefdeadbeefdeadbeefdeadbeef', 'token': 'x',
            'ws_url': 'ws://169.254.169.254/latest/meta-data/',
            'base_url': 'http://127.0.0.1:8300/',
            'url': 'ws://127.0.0.1:8300/',
        }))
        self.assertEqual(spec['ws_url'],
                         'wss://cloudpebble-dev.exe.xyz/qemu/deadbeefdeadbeefdeadbeefdeadbeef/ws/phone')

    @override_settings(QEMU_PUBLIC_URL='https://cloudpebble-dev.exe.xyz/')
    def test_rejects_junk(self):
        for raw in ['not json', '[]', '"x"',
                    json.dumps({'uuid': '../../etc', 'token': 'x'}),
                    json.dumps({'uuid': 'deadbeefdeadbeefdeadbeefdeadbeef', 'token': ''}),
                    json.dumps({'uuid': 'deadbeefdeadbeefdeadbeefdeadbeef', 'token': 'a b'}),
                    json.dumps({'uuid': 'deadbeefdeadbeefdeadbeefdeadbeef', 'token': 'x' * 129})]:
            with self.assertRaises(BadRequest, msg=raw):
                _emulator_spec(raw)

    def test_no_emulator_is_not_an_error(self):
        self.assertIsNone(_emulator_spec(None))
        self.assertIsNone(_emulator_spec(''))


@mock.patch.object(agent_token, 'redis_client', new_callable=FakeRedis)
class AgentTokenScopeTest(TestCase):
    """The scoped token is the security boundary of the whole feature: it must open
    exactly the views in AGENT_PLAN §3.3 and nothing next to them."""

    def setUp(self):
        self.user = User.objects.create_user(username='agentuser', password='x')
        self.project = Project.objects.create(owner=self.user, name='agentproject')
        self.other_project = Project.objects.create(owner=self.user, name='otherproject')
        self.session = AgentSession.objects.create(project=self.project, user=self.user)
        # enforce_csrf_checks so the CSRF assertions below mean something.
        self.client = Client(enforce_csrf_checks=True)

    def _bearer(self, redis):
        return {'HTTP_AUTHORIZATION': 'Bearer %s' % agent_token.mint(
            self.user, self.project, self.session)}

    def test_allowed_view_accepts_the_token(self, redis):
        r = self.client.get(reverse('ide:get_last_build', args=[self.project.id]),
                            **self._bearer(redis))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(json.loads(r.content)['build'])

    def test_allowed_post_is_csrf_exempt_for_the_token(self, redis):
        # 404 rather than 403: it got past CSRF and auth and only then failed to find
        # the file, which is what proves the bearer path works for POSTs.
        r = self.client.post(reverse('ide:save_source_file', args=[self.project.id, 999999]),
                             {'content': 'x', 'folded_lines': '[]', 'modified': '0'},
                             **self._bearer(redis))
        self.assertEqual(r.status_code, 404)

    def test_cookie_posts_still_need_a_csrf_token(self, redis):
        self.client.force_login(self.user)
        r = self.client.post(reverse('ide:save_source_file', args=[self.project.id, 999999]),
                             {'content': 'x', 'folded_lines': '[]', 'modified': '0'})
        self.assertEqual(r.status_code, 403)

    def test_siblings_reject_the_token(self, redis):
        # CSRF off, so a rejection here is the *auth* boundary refusing the token and
        # not the CSRF middleware happening to catch it first.
        self.client = Client(enforce_csrf_checks=False)
        # Everything in the same two modules that the token must NOT open.
        for name, args, method in [
            ('get_build_history', [self.project.id], 'get'),
            ('source_file_is_safe', [self.project.id, 999999], 'get'),
            ('rename_source_file', [self.project.id, 999999], 'post'),
            ('save_project_settings', [self.project.id], 'post'),
            ('save_env_vars', [self.project.id], 'post'),
            ('delete_project', [self.project.id], 'post'),
            ('begin_export', [self.project.id], 'post'),
        ]:
            r = getattr(self.client, method)(reverse('ide:%s' % name, args=args),
                                             **self._bearer(redis))
            # Either a 403 or a redirect to the login page — never the view's own answer.
            self.assertIn(r.status_code, (302, 403), '%s let an agent token through' % name)

    def test_the_token_reaches_resources_and_binary_files(self, redis):
        # Parity with the IDE: anything the Resources pane can do to *this*
        # project, the agent can do too. A 404 is the view answering.
        for name, args, method in [
            ('create_resource', [self.project.id], 'post'),
            ('resource_info', [self.project.id, 999999], 'get'),
            ('update_resource', [self.project.id, 999999], 'post'),
            ('delete_resource', [self.project.id, 999999], 'post'),
            ('create_binary_source_file', [self.project.id], 'post'),
            ('download_source_file', [self.project.id, 999999], 'get'),
        ]:
            r = getattr(self.client, method)(reverse('ide:%s' % name, args=args),
                                             **self._bearer(redis))
            self.assertNotIn(r.status_code, (302, 403),
                             '%s refused an agent token' % name)

    def test_a_resource_id_alone_does_not_open_another_project(self, redis):
        # resource_info and show_resource used to look a resource up by pk (or by
        # owner), so an id from a sibling project answered through this project's
        # URL -- which a token minted for one project must never do.
        from ide.models.files import ResourceFile
        other = ResourceFile.objects.create(project=self.other_project,
                                            file_name='secret.png', kind='png')
        r = self.client.get(reverse('ide:resource_info', args=[self.project.id, other.id]),
                            **self._bearer(redis))
        self.assertEqual(r.status_code, 404)
        r = self.client.get(reverse('ide:show_resource',
                                    args=[self.project.id, other.id, '0']),
                            **self._bearer(redis))
        self.assertEqual(r.status_code, 404)

    def test_token_is_scoped_to_its_own_project(self, redis):
        r = self.client.get(reverse('ide:get_last_build', args=[self.other_project.id]),
                            **self._bearer(redis))
        self.assertEqual(r.status_code, 403)

    def test_no_token_and_no_cookie_is_still_rejected(self, redis):
        r = self.client.get(reverse('ide:get_last_build', args=[self.project.id]))
        self.assertIn(r.status_code, (302, 403))


@mock.patch.object(agent_token, 'redis_client', new_callable=FakeRedis)
class TranscriptWireFormatTest(TestCase):
    """The SessionStore contract with cloudpebble-agent/session_store.py."""

    SDK_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'

    def setUp(self):
        self.user = User.objects.create_user(username='agentuser', password='x')
        self.project = Project.objects.create(owner=self.user, name='agentproject')
        self.session = AgentSession.objects.create(project=self.project, user=self.user)
        self.url = reverse('ide:agent_transcript', args=[self.SDK_ID])

    def _bearer(self):
        return {'HTTP_AUTHORIZATION': 'Bearer %s' % agent_token.mint(
            self.user, self.project, self.session)}

    def _append(self, entries, subpath=None):
        body = {'project_key': 'p', 'entries': entries}
        if subpath is not None:
            body['subpath'] = subpath
        return self.client.post(self.url, json.dumps(body),
                                content_type='application/json', **self._bearer())

    def test_batches_accumulate_and_load_back_as_json(self, redis):
        self.assertEqual(self.client.get(self.url, **self._bearer()).status_code, 404)
        self.assertEqual(self._append([{'type': 'user', 'uuid': '1'}]).status_code, 204)
        self.assertEqual(self._append([{'type': 'assistant', 'uuid': '2'},
                                       {'type': 'result', 'uuid': '3'}]).status_code, 204)

        r = self.client.get(self.url, **self._bearer())
        self.assertEqual(r.status_code, 200)
        self.assertEqual([e['uuid'] for e in json.loads(r.content)['entries']], ['1', '2', '3'])

        # The first mirror is how the session learns its resume id.
        self.session.refresh_from_db()
        self.assertEqual(self.session.sdk_session_id, self.SDK_ID)

    def test_subpaths_do_not_overwrite_each_other(self, redis):
        self._append([{'type': 'main', 'uuid': 'm'}])
        self._append([{'type': 'sub', 'uuid': 's'}], subpath='subagents/agent-1')

        main = self.client.get(self.url, **self._bearer())
        sub = self.client.get(self.url, {'subpath': 'subagents/agent-1'}, **self._bearer())
        self.assertEqual([e['uuid'] for e in json.loads(main.content)['entries']], ['m'])
        self.assertEqual([e['uuid'] for e in json.loads(sub.content)['entries']], ['s'])

    def test_oversized_mirror_is_refused(self, redis):
        # A real ceiling is megabytes; shrink it rather than posting megabytes, which
        # DATA_UPLOAD_MAX_MEMORY_SIZE would reject first for the wrong reason.
        from ide.models.agent import AgentTranscript
        with mock.patch.object(AgentTranscript, 'MAX_BYTES', 200):
            big = 'x' * 150
            self.assertEqual(self._append([{'type': 'user', 'text': big}]).status_code, 204)
            self.assertEqual(self._append([{'type': 'user', 'text': big}]).status_code, 413)
        # The refusal does not corrupt what was already stored.
        r = self.client.get(self.url, **self._bearer())
        self.assertEqual(len(json.loads(r.content)['entries']), 1)

    def test_a_malformed_body_is_a_400_not_a_500(self, redis):
        r = self.client.post(self.url, 'not json', content_type='application/json',
                             **self._bearer())
        self.assertEqual(r.status_code, 400)

    def test_the_transcript_routes_need_the_token(self, redis):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)


@override_settings(AGENT_ENABLED_USERS='*')
class CredentialSaveTest(TestCase):
    """The secret is write-only, so the browser cannot send it back. A blank one on
    save must therefore mean 'keep it' -- otherwise changing the model would silently
    require re-pasting a key the user no longer has to hand."""

    def setUp(self):
        self.user = User.objects.create_user(username='creduser', password='x')
        self.client = Client()
        self.client.force_login(self.user)
        self.url = reverse('ide:agent_credentials_save')

    def _save(self, **kwargs):
        return self.client.post(self.url, kwargs)

    def test_model_changes_without_re_entering_the_secret(self):
        self.assertEqual(self._save(provider='anthropic', secret_kind='oauth',
                                    secret='sk-ant-oat01-abc', model='').status_code, 200)
        r = self._save(provider='anthropic', secret_kind='oauth', secret='',
                       model='claude-opus-5')
        self.assertEqual(r.status_code, 200)
        credential = AgentCredential.objects.get(user=self.user)
        self.assertEqual(credential.model, 'claude-opus-5')
        self.assertEqual(credential.secret(), 'sk-ant-oat01-abc')

    def test_first_save_still_needs_a_secret(self):
        self.assertEqual(self._save(provider='anthropic', secret_kind='api_key',
                                    secret='', model='').status_code, 400)

    def test_switching_provider_needs_the_new_secret(self):
        self._save(provider='anthropic', secret_kind='api_key', secret='sk-ant-key')
        self.assertEqual(self._save(provider='openrouter', secret_kind='api_key',
                                    secret='').status_code, 400)

    def test_switching_credential_kind_needs_the_new_secret(self):
        # An API key is not an OAuth token: keeping it would send the wrong header.
        self._save(provider='anthropic', secret_kind='api_key', secret='sk-ant-key')
        self.assertEqual(self._save(provider='anthropic', secret_kind='oauth',
                                    secret='').status_code, 400)


class SupersededTurnTest(TestCase):
    """Stopping in order to say something else starts the next turn while the old
    one is still winding down on the agent VM. The old relay must go quiet."""

    def setUp(self):
        self.user = User.objects.create_user(username='stopuser', password='x')
        self.project = Project.objects.create(owner=self.user, name='stopproject')
        self.session = AgentSession.objects.create(project=self.project, user=self.user,
                                                   status='running', turn_count=3)

    def test_its_own_turn_is_not_superseded(self):
        self.assertFalse(_superseded(self.session.id, 3))

    def test_a_newer_turn_supersedes_it(self):
        AgentSession.objects.filter(pk=self.session.id).update(turn_count=4)
        self.assertTrue(_superseded(self.session.id, 4 - 1))

    def test_stopping_retires_the_turn_number(self):
        # Otherwise the stopped turn's late 'done' resets the session to idle
        # underneath whatever the user asked for next.
        client = Client()
        client.force_login(self.user)
        with override_settings(AGENT_ENABLED_USERS='*', AGENT_URL='', AGENT_AUTH_HEADER=''):
            r = client.post(reverse('ide:agent_cancel', args=[self.project.id]))
        self.assertEqual(r.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'cancelled')
        self.assertTrue(_superseded(self.session.id, 3))

    def test_a_vanished_session_counts_as_superseded(self):
        self.assertTrue(_superseded(self.session.id + 9999, 1))

    def test_a_relay_with_no_turn_number_still_writes(self):
        # Belt and braces for any caller that has not been updated.
        self.assertFalse(_superseded(self.session.id, None))


class EmulatorKeepaliveTest(TestCase):
    """A phone freezes the browser tab's timers when the screen locks, so the
    only thing pinging the qemu controller stops. The controller reaps at 300s
    and the turn -- minutes long -- loses the watch it was about to install to."""

    @override_settings(QEMU_URLS=['http://qemu/', 'http://qemu2/'],
                       AGENT_EMULATOR_PING_SECONDS=0.01)
    def test_it_pings_every_server_until_told_to_stop(self):
        stop = threading.Event()
        calls = []
        with mock.patch('ide.api.agent.requests.post', side_effect=lambda url, **kw: calls.append(url)):
            with mock.patch('ide.api.agent.EMULATOR_PING_SECONDS', 0.01):
                thread = threading.Thread(target=_keepalive, args=('an-emulator-uuid', stop))
                thread.start()
                for _ in range(200):
                    if len(calls) >= 4:
                        break
                    time.sleep(0.01)
                stop.set()
                thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertIn('http://qemu/qemu/an-emulator-uuid/ping', calls)
        self.assertIn('http://qemu2/qemu/an-emulator-uuid/ping', calls)

    @override_settings(QEMU_URLS=['http://qemu/'])
    def test_an_unreachable_controller_does_not_kill_the_turn(self):
        stop = threading.Event()
        with mock.patch('ide.api.agent.requests.post',
                        side_effect=requests.RequestException('boom')):
            with mock.patch('ide.api.agent.EMULATOR_PING_SECONDS', 0.01):
                thread = threading.Thread(target=_keepalive, args=('u', stop))
                thread.start()
                time.sleep(0.05)
                stop.set()
                thread.join(timeout=5)
        self.assertFalse(thread.is_alive())


class TurnFencingTest(TestCase):
    """The relay reads its session when the turn starts and writes it when the turn
    ends. Anything that changed in between belongs to somebody else."""

    def setUp(self):
        self.user = User.objects.create_user(username='fenceuser', password='x')
        self.project = Project.objects.create(owner=self.user, name='fenceproject')
        self.session = AgentSession.objects.create(project=self.project, user=self.user,
                                                   status='running', turn_count=3)

    def test_a_finished_turn_does_not_roll_back_a_newer_turns_number(self):
        # The relay's stale in-memory copy, as it would be mid-turn.
        stale = AgentSession.objects.get(pk=self.session.id)
        # Meanwhile: Stop, then a new message. Both bump turn_count.
        AgentSession.objects.filter(pk=self.session.id).update(turn_count=5)

        stale.status = 'idle'
        stale.save(update_fields=['status'])

        self.session.refresh_from_db()
        self.assertEqual(self.session.turn_count, 5)
        # ...so the old relay is still fenced out.
        self.assertTrue(_superseded(self.session.id, 3))

    def test_append_survives_a_seq_collision(self):
        # Two writers computing max(seq)+1 at the same moment: the loser retries
        # rather than raising into the relay's blanket except.
        first = _append(self.session, 'system', 'text', {'text': 'a'})
        duplicate = AgentMessage(session=self.session, seq=first['seq'],
                                 role='system', content={'type': 'text', 'data': {}})
        # IdeModel full_cleans on pre_save, so the collision surfaces as a
        # ValidationError rather than an IntegrityError. _append handles both.
        with self.assertRaises(ValidationError):
            duplicate.save()
        second = _append(self.session, 'system', 'text', {'text': 'b'})
        self.assertEqual(second['seq'], first['seq'] + 1)


@override_settings(AGENT_ENABLED_USERS='*', AGENT_URL='', AGENT_AUTH_HEADER='')
class HealStopsTheAgentTest(TestCase):
    """Healing a wedged session used to only flip the status, leaving the agent VM
    working on a session the user could immediately start a second turn on."""

    def setUp(self):
        self.user = User.objects.create_user(username='healuser', password='x')
        self.project = Project.objects.create(owner=self.user, name='healproject')
        self.session = AgentSession.objects.create(project=self.project, user=self.user,
                                                   status='running', turn_count=2)

    def test_healing_retires_the_turn_and_calls_cancel(self):
        old = timezone.now() - datetime.timedelta(seconds=STALE_TURN_SECONDS + 60)
        AgentSession.objects.filter(pk=self.session.id).update(last_active=old)
        self.session.refresh_from_db()

        with override_settings(AGENT_URL='http://agent/', AGENT_AUTH_HEADER='secret'):
            with mock.patch('ide.api.agent.requests.post') as post:
                self.assertTrue(heal_if_stale(self.session))

        self.assertEqual(post.call_args[0][0], 'http://agent/cancel')
        self.assertEqual(post.call_args[1]['json'], {'session_id': self.session.id})
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'error')
        self.assertTrue(_superseded(self.session.id, 2))

    def test_a_live_turn_is_not_healed(self):
        # Silence is not death: a model generating a whole file goes quiet for
        # minutes, and healing it would kill a working turn.
        recent = timezone.now() - datetime.timedelta(seconds=300)
        AgentSession.objects.filter(pk=self.session.id).update(last_active=recent)
        self.session.refresh_from_db()
        self.assertFalse(heal_if_stale(self.session))
        self.assertEqual(self.session.status, 'running')


@override_settings(AGENT_ENABLED_USERS='*', AGENT_URL='http://agent/',
                   AGENT_AUTH_HEADER='secret')
class MessageValidationOrderTest(TestCase):
    """A refused turn must cost nothing: no daily turn, no locked composer."""

    def setUp(self):
        self.user = User.objects.create_user(username='orderuser', password='x')
        self.project = Project.objects.create(owner=self.user, name='orderproject')
        AgentSession.objects.create(project=self.project, user=self.user, status='idle')
        self.client = Client()
        self.client.force_login(self.user)

    def test_an_unconfigured_model_leaves_the_session_idle(self):
        with mock.patch('ide.api.agent.config_for', return_value=None):
            with self.assertRaises(InternalServerError):
                self.client.post(reverse('ide:agent_message', args=[self.project.id]),
                                 {'message': 'build me a watchface'})
        session = AgentSession.objects.get(project=self.project)
        self.assertEqual(session.status, 'idle')
        self.assertEqual(session.turn_count, 0)
        self.assertFalse(AgentMessage.objects.filter(session=session).exists())
