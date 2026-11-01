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
