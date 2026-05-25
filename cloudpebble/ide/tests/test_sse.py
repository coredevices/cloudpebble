import json
from io import BytesIO
from unittest import mock

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User

from utils.events import publish_event
from ide.api.sse import SSEEventStream, project_events
from ide.tasks.git import hooked_commit, do_github_pull
from ide.tasks.build import run_compile


class FakePubSub:
    def __init__(self):
        self.messages = []
        self.subscribed = False

    def subscribe(self, channel):
        self.subscribed = True

    def listen(self):
        for msg in self.messages:
            yield msg

    def unsubscribe(self, channel):
        self.subscribed = False

    def close(self):
        pass


class FakeRedisClient:
    def __init__(self):
        self.published = []
        self._pubsub = FakePubSub()

    def publish(self, channel, message):
        self.published.append((channel, message))

    def pubsub(self):
        return self._pubsub


class TestPublishEvent(TestCase):
    @mock.patch('utils.events.redis_client')
    def test_publish_event_sends_json(self, mock_redis):
        publish_event(42, 'pull_start')
        mock_redis.publish.assert_called_once_with(
            'project_events:42',
            json.dumps({'type': 'pull_start'})
        )

    @mock.patch('utils.events.redis_client')
    def test_publish_event_includes_kwargs(self, mock_redis):
        publish_event(7, 'build_complete', build_id=99, state='succeeded')
        channel, message = mock_redis.publish.call_args[0]
        self.assertEqual(channel, 'project_events:7')
        data = json.loads(message)
        self.assertEqual(data['type'], 'build_complete')
        self.assertEqual(data['build_id'], 99)
        self.assertEqual(data['state'], 'succeeded')


class TestSSEEventStream(TestCase):
    def test_stream_yields_formatted_messages(self):
        stream = SSEEventStream.__new__(SSEEventStream)
        stream.channel = 'project_events:1'
        stream.pubsub = FakePubSub()
        stream.pubsub.messages = [
            {'type': 'subscribe', 'data': b''},
            {'type': 'message', 'data': b'{"type":"pull_start"}'},
            {'type': 'message', 'data': b'{"type":"pull_complete","github_last_commit":"abc123"}'},
        ]
        results = []
        for item in stream:
            results.append(item)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], 'event: pull_start\ndata: {}\n\n')
        self.assertEqual(results[1], 'event: pull_complete\ndata: {"github_last_commit": "abc123"}\n\n')

    def test_stream_skips_non_message_types(self):
        stream = SSEEventStream.__new__(SSEEventStream)
        stream.channel = 'project_events:1'
        stream.pubsub = FakePubSub()
        stream.pubsub.messages = [
            {'type': 'subscribe', 'data': b''},
            {'type': 'message', 'data': b'{"type":"build_start","build_id":1}'},
        ]
        results = []
        for item in stream:
            results.append(item)
        self.assertEqual(len(results), 1)
        self.assertIn('event:', results[0])
        self.assertIn('build_start', results[0])

    def test_stream_decodes_bytes_data(self):
        stream = SSEEventStream.__new__(SSEEventStream)
        stream.channel = 'project_events:1'
        stream.pubsub = FakePubSub()
        stream.pubsub.messages = [
            {'type': 'message', 'data': b'{"type":"pull_start"}'},
        ]
        results = list(stream)
        self.assertEqual(results[0], 'event: pull_start\ndata: {}\n\n')

    def test_stream_handles_string_data(self):
        stream = SSEEventStream.__new__(SSEEventStream)
        stream.channel = 'project_events:1'
        stream.pubsub = FakePubSub()
        stream.pubsub.messages = [
            {'type': 'message', 'data': '{"type":"pull_start"}'},
        ]
        results = list(stream)
        self.assertEqual(results[0], 'event: pull_start\ndata: {}\n\n')

    def test_stream_cleans_up_on_generator_exit(self):
        stream = SSEEventStream.__new__(SSEEventStream)
        stream.channel = 'project_events:1'
        fake_pubsub = FakePubSub()
        stream.pubsub = fake_pubsub
        gen = iter(stream)
        next(gen, None)
        gen.close()
        self.assertFalse(fake_pubsub.subscribed)


class TestProjectEventsEndpoint(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user('testuser', 'test@test.test', 'testpass')

    def test_requires_login(self):
        from django.test import Client
        client = Client()
        response = client.get('/ide/project/1/events')
        self.assertIn(response.status_code, [301, 302, 403])

    def test_nonexistent_project_returns_404(self):
        request = self.factory.get('/ide/project/99999/events')
        request.user = self.user
        with mock.patch('ide.api.sse.redis_client') as mock_redis:
            mock_redis.pubsub.return_value = FakePubSub()
            response = project_events(request, 99999)
            self.assertEqual(response.status_code, 404)

    @mock.patch('ide.api.sse.redis_client')
    def test_response_headers(self, mock_redis):
        from ide.models.project import Project
        project = Project.objects.create(owner=self.user, name='testproject')
        mock_redis.pubsub.return_value = FakePubSub()
        request = self.factory.get('/ide/project/%d/events' % project.id)
        request.user = self.user
        response = project_events(request, project.id)
        self.assertEqual(response['Content-Type'], 'text/event-stream')
        self.assertEqual(response['Cache-Control'], 'no-cache')
        self.assertEqual(response['X-Accel-Buffering'], 'no')


class TestHookedCommitEvents(TestCase):
    @mock.patch('ide.tasks.git.publish_event')
    @mock.patch('ide.tasks.git.run_compile')
    @mock.patch('ide.tasks.git.github_pull')
    def test_publishes_pull_start_and_complete(self, mock_pull, mock_compile, mock_publish):
        from ide.models.project import Project
        user = User.objects.create_user('hooktest', 'hook@test.test', 'testpass')
        project = Project.objects.create(
            owner=user, name='hookproj',
            github_repo='owner/repo', github_branch='main',
            github_last_commit='oldsha', github_hook_build=False,
        )
        mock_pull.return_value = True
        hooked_commit(project.id, 'newsha')
        publish_calls = mock_publish.call_args_list
        self.assertEqual(publish_calls[0][0], (project.id, 'pull_start'))
        self.assertEqual(publish_calls[1][0][0], project.id)
        self.assertEqual(publish_calls[1][0][1], 'pull_complete')
        self.assertIn('github_last_commit', publish_calls[1][1])

    @mock.patch('ide.tasks.git.publish_event')
    @mock.patch('ide.tasks.git.run_compile')
    @mock.patch('ide.tasks.git.github_pull')
    def test_publishes_build_start_when_auto_build(self, mock_pull, mock_compile, mock_publish):
        from ide.models.project import Project
        from ide.models.build import BuildResult
        user = User.objects.create_user('hooktest2', 'hook2@test.test', 'testpass')
        project = Project.objects.create(
            owner=user, name='hookproj2',
            github_repo='owner/repo', github_branch='main',
            github_last_commit='oldsha', github_hook_build=True,
        )
        mock_pull.return_value = True
        hooked_commit(project.id, 'newsha')
        build_start_call = None
        for call in mock_publish.call_args_list:
            if call[0][1] == 'build_start':
                build_start_call = call
                break
        self.assertIsNotNone(build_start_call)
        self.assertEqual(build_start_call[0][0], project.id)
        self.assertIn('build_id', build_start_call[1])
        self.assertIsInstance(build_start_call[1]['build_id'], int)

    @mock.patch('ide.tasks.git.publish_event')
    @mock.patch('ide.tasks.git.github_pull')
    def test_publishes_pull_failed_on_exception(self, mock_pull, mock_publish):
        from ide.models.project import Project
        user = User.objects.create_user('hooktest3', 'hook3@test.test', 'testpass')
        project = Project.objects.create(
            owner=user, name='hookproj3',
            github_repo='owner/repo', github_branch='main',
            github_last_commit='oldsha', github_hook_build=False,
        )
        mock_pull.side_effect = Exception('pull failed')
        with self.assertRaises(Exception) as ctx:
            hooked_commit(project.id, 'newsha')
        self.assertEqual(str(ctx.exception), 'pull failed')
        types = [call[0][1] for call in mock_publish.call_args_list]
        self.assertEqual(types, ['pull_start', 'pull_failed'])

    @mock.patch('ide.tasks.git.publish_event')
    @mock.patch('ide.tasks.git.run_compile')
    @mock.patch('ide.tasks.git.github_pull')
    def test_no_pull_events_when_commit_unchanged(self, mock_pull, mock_compile, mock_publish):
        from ide.models.project import Project
        user = User.objects.create_user('hooknoch', 'hooknoch@test.test', 'testpass')
        project = Project.objects.create(
            owner=user, name='hooknoch',
            github_repo='owner/repo', github_branch='main',
            github_last_commit='samesha', github_hook_build=False,
        )
        result = hooked_commit(project.id, 'samesha')
        self.assertFalse(result)
        mock_publish.assert_not_called()
        mock_pull.assert_not_called()

    @mock.patch('ide.tasks.git.publish_event')
    @mock.patch('ide.tasks.git.run_compile')
    @mock.patch('ide.tasks.git.github_pull')
    def test_skip_build_when_auto_build_disabled(self, mock_pull, mock_compile, mock_publish):
        from ide.models.project import Project
        user = User.objects.create_user('hooknobuild', 'hooknobuild@test.test', 'testpass')
        project = Project.objects.create(
            owner=user, name='hooknobuild',
            github_repo='owner/repo', github_branch='main',
            github_last_commit='oldsha', github_hook_build=False,
        )
        mock_pull.return_value = True
        hooked_commit(project.id, 'newsha')
        types = [call[0][1] for call in mock_publish.call_args_list]
        self.assertNotIn('build_start', types)
        mock_compile.assert_not_called()


class TestDoGithubPullEvents(TestCase):
    @mock.patch('ide.tasks.git.publish_event')
    @mock.patch('ide.tasks.git.run_compile')
    @mock.patch('ide.tasks.git.github_pull')
    def test_publishes_pull_events(self, mock_pull, mock_compile, mock_publish):
        from ide.models.project import Project
        user = User.objects.create_user('pulltest1', 'pull1@test.test', 'testpass')
        project = Project.objects.create(
            owner=user, name='pullproj1',
            github_repo='owner/repo', github_branch='main',
            github_last_commit='oldsha', github_hook_build=False,
        )
        mock_pull.return_value = True
        do_github_pull(project.id)
        types = [call[0][1] for call in mock_publish.call_args_list]
        self.assertEqual(types[0], 'pull_start')
        self.assertEqual(types[1], 'pull_complete')

    @mock.patch('ide.tasks.git.publish_event')
    @mock.patch('ide.tasks.git.run_compile')
    @mock.patch('ide.tasks.git.github_pull')
    def test_auto_builds_when_hook_build_enabled(self, mock_pull, mock_compile, mock_publish):
        from ide.models.project import Project
        user = User.objects.create_user('pulltest2', 'pull2@test.test', 'testpass')
        project = Project.objects.create(
            owner=user, name='pullproj2',
            github_repo='owner/repo', github_branch='main',
            github_last_commit='oldsha', github_hook_build=True,
        )
        mock_pull.return_value = True
        do_github_pull(project.id)
        types = [call[0][1] for call in mock_publish.call_args_list]
        self.assertIn('build_start', types)
        mock_compile.assert_called_once()

    @mock.patch('ide.tasks.git.publish_event')
    @mock.patch('ide.tasks.git.run_compile')
    @mock.patch('ide.tasks.git.github_pull')
    def test_no_auto_build_when_hook_build_disabled(self, mock_pull, mock_compile, mock_publish):
        from ide.models.project import Project
        user = User.objects.create_user('pulltest3', 'pull3@test.test', 'testpass')
        project = Project.objects.create(
            owner=user, name='pullproj3',
            github_repo='owner/repo', github_branch='main',
            github_last_commit='oldsha', github_hook_build=False,
        )
        mock_pull.return_value = True
        do_github_pull(project.id)
        types = [call[0][1] for call in mock_publish.call_args_list]
        self.assertNotIn('build_start', types)
        mock_compile.assert_not_called()

    @mock.patch('ide.tasks.git.publish_event')
    @mock.patch('ide.tasks.git.github_pull')
    def test_publishes_pull_failed_on_exception(self, mock_pull, mock_publish):
        from ide.models.project import Project
        user = User.objects.create_user('pulltest4', 'pull4@test.test', 'testpass')
        project = Project.objects.create(
            owner=user, name='pullproj4',
            github_repo='owner/repo', github_branch='main',
            github_last_commit='oldsha', github_hook_build=False,
        )
        mock_pull.side_effect = Exception('pull failed')
        with self.assertRaises(Exception):
            do_github_pull(project.id)
        types = [call[0][1] for call in mock_publish.call_args_list]
        self.assertEqual(types, ['pull_start', 'pull_failed'])


class TestRunCompileEvents(TestCase):
    @mock.patch('ide.tasks.build.publish_event')
    @mock.patch('ide.tasks.build.assemble_project')
    @mock.patch('ide.tasks.build._set_resource_limits')
    @mock.patch('ide.tasks.build.shutil.rmtree')
    @mock.patch('ide.tasks.build.now')
    @mock.patch('ide.tasks.build.os.chdir')
    @mock.patch('ide.tasks.build.subprocess.check_output', side_effect=Exception('boom'))
    def test_publishes_build_complete_on_failure(self, mock_subprocess, mock_chdir, mock_now, mock_rmtree, mock_limits, mock_assemble, mock_publish):
        from ide.models.project import Project
        from ide.models.build import BuildResult
        user = User.objects.create_user('buildtest', 'build@test.test', 'testpass')
        project = Project.objects.create(owner=user, name='buildproj')
        build = BuildResult.objects.create(project=project)
        mock_now.return_value = build.started
        try:
            run_compile(build.id)
        except Exception:
            pass
        build.refresh_from_db()
        self.assertEqual(build.state, BuildResult.STATE_FAILED)
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        self.assertEqual(call_args[0][0], project.id)
        self.assertEqual(call_args[0][1], 'build_complete')
        self.assertEqual(call_args[1]['build_id'], build.id)
        self.assertEqual(call_args[1]['state'], 'failed')