from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from ide.models.project import Project


class TestImportZipSizeLimit(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('zip-test', 'zip-test@example.com', 'pw')
        self.client.force_login(self.user)

    def post(self, size):
        archive = SimpleUploadedFile('p.zip', b'x' * size, content_type='application/zip')
        return self.client.post('/ide/import/zip', {'archive': archive, 'name': 'p'})

    @mock.patch('ide.api.project.MAX_IMPORT_ARCHIVE_BYTES', 10)
    @mock.patch('ide.api.project.do_import_archive')
    def test_oversized_archive_is_rejected_before_queueing(self, do_import_archive):
        response = self.post(11)
        self.assertEqual(response.status_code, 400)
        do_import_archive.delay.assert_not_called()
        self.assertFalse(Project.objects.filter(owner=self.user).exists())

    @mock.patch('ide.api.project.MAX_IMPORT_ARCHIVE_BYTES', 10)
    @mock.patch('ide.api.project.do_import_archive')
    def test_archive_at_the_limit_is_queued(self, do_import_archive):
        do_import_archive.delay.return_value.task_id = 'task-1'
        response = self.post(10)
        self.assertEqual(response.status_code, 200)
        do_import_archive.delay.assert_called_once()
