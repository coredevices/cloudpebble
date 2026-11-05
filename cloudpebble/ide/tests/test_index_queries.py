from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from ide.models.build import BuildResult
from ide.models.project import Project


@override_settings(SOCIAL_AUTH_PEBBLE_REQUIRED=False)
class TestIndexQueryCount(TestCase):
    """The project list must not run a query per project: the production DB is ~120 ms away."""

    def setUp(self):
        self.user = User.objects.create_user('index-test', 'index-test@example.com', 'pw')
        settings = self.user.settings  # property: get_or_create on every access
        settings.accepted_terms = True
        settings.save()
        self.client.force_login(self.user)

    def add_projects(self, n):
        for i in range(n):
            project = Project.objects.create(name='p%d' % i, owner=self.user)
            BuildResult.objects.create(project=project, state=BuildResult.STATE_FAILED)
            BuildResult.objects.create(project=project, state=BuildResult.STATE_SUCCEEDED)

    def index_queries(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/ide/')
        self.assertEqual(response.status_code, 200)
        return len(queries), response

    def test_query_count_does_not_grow_with_projects(self):
        self.add_projects(2)
        few, _ = self.index_queries()
        self.add_projects(5)
        many, response = self.index_queries()
        self.assertEqual(few, many)
        # the last build (succeeded) is what the list shows, not the earlier failed one
        self.assertNotContains(response, 'label-error')
        self.assertContains(response, 'label-success', count=7)
