import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from ide.models.project import Project


class TestGithubHook(TestCase):
    def setUp(self):
        user = User.objects.create_user('hook-test', 'hook-test@example.com', 'pw')
        self.project = Project.objects.create(owner=user, name='p', github_branch='main',
                                              github_hook_uuid='hook-key')
        self.url = '/ide/project/%d/github/push_hook?key=%s' % (self.project.pk, self.project.github_hook_uuid)

    def post(self, payload):
        return self.client.post(self.url, {'payload': json.dumps(payload)})

    @mock.patch('ide.views.project.hooked_commit')
    def test_ping_event_is_ok(self, hooked_commit):
        response = self.post({'zen': 'Keep it logically awesome.', 'hook_id': 1, 'repository': {'default_branch': 'main'}})
        self.assertEqual(response.status_code, 200)
        hooked_commit.delay.assert_not_called()

    @mock.patch('ide.views.project.hooked_commit')
    def test_push_to_branch_queues_commit(self, hooked_commit):
        response = self.post({'ref': 'refs/heads/main', 'after': 'abc123', 'repository': {'default_branch': 'main'}})
        self.assertEqual(response.status_code, 200)
        hooked_commit.delay.assert_called_once_with(str(self.project.pk), 'abc123')


class TestLinkRepoWebhookDenied(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('link-test', 'link-test@example.com', 'pw')
        self.project = Project.objects.create(owner=self.user, name='p')
        self.client.force_login(self.user)

    @mock.patch('ide.api.git.ide.git.check_repo_access', return_value=True)
    @mock.patch('ide.api.git.ide.git.git_verify_tokens', return_value=True)
    @mock.patch('ide.api.git.ide.git.get_github')
    def test_webhook_403_is_a_400_and_saves_nothing(self, get_github, _verify, _access):
        from github import GithubException
        g_repo = get_github.return_value.get_repo.return_value
        g_repo.create_hook.side_effect = GithubException(403, {'message': 'Resource not accessible by integration'}, None)
        response = self.client.post('/ide/project/%d/github/repo' % self.project.pk, {
            'repo': 'github.com/someone/watchapp', 'branch': 'main', 'auto_pull': '1', 'auto_build': '0'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('admin access', json.loads(response.content)['error'])
        self.project.refresh_from_db()
        self.assertIsNone(self.project.github_repo)
        self.assertIsNone(self.project.github_hook_uuid)
