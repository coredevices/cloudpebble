"""BuildResult.commit_sha must capture the project's GitHub state at build
creation time (issue #57: show which commit a build is based on)."""
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils.timezone import now

from ide.models.build import BuildResult
from ide.models.project import Project


class BuildCommitShaTest(TestCase):
    def _make_project(self, **kwargs):
        user, _ = User.objects.get_or_create(username='test')
        return Project.objects.create(
            owner=user, name='test', project_type='native',
            app_short_name='test', app_long_name='test',
            app_company_name='test', **kwargs)

    def test_no_github_repo_leaves_commit_blank(self):
        project = self._make_project()
        build = BuildResult.objects.create(project=project)
        self.assertIsNone(build.commit_sha)

    def test_captures_synced_commit(self):
        sync = now()
        project = self._make_project(
            github_repo='a/b', github_last_commit='a' * 40,
            github_last_sync=sync)
        Project.objects.filter(pk=project.pk).update(last_modified=sync - datetime.timedelta(minutes=1))
        project.refresh_from_db()
        build = BuildResult.objects.create(project=project)
        self.assertEqual(build.commit_sha, 'a' * 40)

    def test_marks_dirty_when_edited_after_sync(self):
        sync = now() - datetime.timedelta(hours=1)
        project = self._make_project(
            github_repo='a/b', github_last_commit='a' * 40,
            github_last_sync=sync)
        # Project.last_modified is bumped by file saves; simulate one.
        Project.objects.filter(pk=project.pk).update(last_modified=now())
        project.refresh_from_db()
        build = BuildResult.objects.create(project=project)
        self.assertEqual(build.commit_sha, 'a' * 40 + '-dirty')
