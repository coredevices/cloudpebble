from unittest import mock

from django.contrib.auth.models import User
from django.db import transaction
from django.test import TestCase, override_settings

from ide.models.files import SourceFile
from ide.models.project import Project


@override_settings(AWS_ENABLED=False)
class TestStoredFileDeletedOnlyAfterCommit(TestCase):
    """A project delete whose transaction fails must not destroy the files."""

    def setUp(self):
        user = User.objects.create_user('delete-test', 'delete-test@example.com', 'pw')
        self.project = Project.objects.create(owner=user, name='p')
        SourceFile.objects.create(project=self.project, file_name='main.c', target='app')

    @mock.patch('ide.models.s3file.os.unlink')
    def test_rolled_back_delete_keeps_files(self, unlink):
        project_id = self.project.pk  # delete() clears .pk even if it rolls back
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    self.project.delete()
                    raise RuntimeError('commit fails, e.g. FK violation')
            except RuntimeError:
                pass
        unlink.assert_not_called()
        self.assertTrue(SourceFile.objects.filter(project_id=project_id).exists())

    @mock.patch('ide.models.s3file.os.unlink')
    def test_committed_delete_removes_files(self, unlink):
        with self.captureOnCommitCallbacks(execute=True):
            self.project.delete()
        unlink.assert_called_once()
