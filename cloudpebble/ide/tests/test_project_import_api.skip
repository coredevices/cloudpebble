import json
from io import BytesIO
from zipfile import ZipFile

import mock
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import Client
from django.test import TestCase
from django.contrib.auth.models import User

from ide.models import Project, SourceFile


def _make_zip_bytes():
    buf = BytesIO()
    with ZipFile(buf, 'w') as zf:
        zf.writestr('appinfo.json', '{"sdkVersion":"3"}')
        zf.writestr('src/main.c', 'int main(void){return 0;}')
        zf.writestr('wscript', 'def options(ctx): pass')
    return buf.getvalue()


class _FakeTask(object):
    task_id = 'task-123'


class TestProjectImportApi(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.post('/accounts/register', {
            'username': 'test',
            'email': 'test@test.test',
            'password1': 'test',
            'password2': 'test',
        })
        self.assertTrue(self.client.login(username='test', password='test'))

    @mock.patch('ide.api.project.do_import_archive')
    def test_import_zip_uses_selected_sdk(self, import_archive):
        import_archive.delay.return_value = _FakeTask()
        response = self.client.post('/ide/import/zip', {
            'name': 'zip-sdk-4927',
            'sdk': '4.9.148',
            'archive': SimpleUploadedFile('project.zip', _make_zip_bytes(), content_type='application/zip'),
        })
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        project = Project.objects.get(id=payload['project_id'])
        self.assertEqual(project.sdk_version, '4.9.148')

    @mock.patch('ide.api.project.do_import_archive')
    def test_import_zip_defaults_to_4927(self, import_archive):
        import_archive.delay.return_value = _FakeTask()
        response = self.client.post('/ide/import/zip', {
            'name': 'zip-sdk-default',
            'archive': SimpleUploadedFile('project.zip', _make_zip_bytes(), content_type='application/zip'),
        })
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        project = Project.objects.get(id=payload['project_id'])
        self.assertEqual(project.sdk_version, '4.9.148')

    @mock.patch('ide.api.project.do_import_archive')
    def test_import_zip_rejects_invalid_sdk(self, import_archive):
        response = self.client.post('/ide/import/zip', {
            'name': 'zip-sdk-invalid',
            'sdk': 'invalid-sdk',
            'archive': SimpleUploadedFile('project.zip', _make_zip_bytes(), content_type='application/zip'),
        })
        payload = json.loads(response.content)
        self.assertFalse(payload['success'])
        self.assertEqual(response.status_code, 400)
        import_archive.delay.assert_not_called()
        self.assertFalse(Project.objects.filter(name='zip-sdk-invalid').exists())

    @mock.patch('ide.api.project.do_import_github')
    def test_import_github_uses_selected_sdk(self, import_github):
        import_github.delay.return_value = _FakeTask()
        response = self.client.post('/ide/import/github', {
            'name': 'github-sdk-4927',
            'repo': 'github.com/example/repo',
            'branch': 'master',
            'sdk': '4.9.148',
            'add_remote': 'false',
        })
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        project = Project.objects.get(id=payload['project_id'])
        self.assertEqual(project.sdk_version, '4.9.148')

    @mock.patch('ide.api.project.do_import_github')
    def test_import_github_defaults_to_4927(self, import_github):
        import_github.delay.return_value = _FakeTask()
        response = self.client.post('/ide/import/github', {
            'name': 'github-sdk-default',
            'repo': 'github.com/example/repo',
            'branch': 'master',
            'add_remote': 'false',
        })
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        project = Project.objects.get(id=payload['project_id'])
        self.assertEqual(project.sdk_version, '4.9.148')

    @mock.patch('ide.api.project.do_import_github')
    def test_import_github_rejects_invalid_sdk(self, import_github):
        response = self.client.post('/ide/import/github', {
            'name': 'github-sdk-invalid',
            'repo': 'github.com/example/repo',
            'branch': 'master',
            'sdk': 'invalid-sdk',
            'add_remote': 'false',
        })
        payload = json.loads(response.content)
        self.assertFalse(payload['success'])
        self.assertEqual(response.status_code, 400)
        import_github.delay.assert_not_called()
        self.assertFalse(Project.objects.filter(name='github-sdk-invalid').exists())

    @mock.patch('ide.api.project.do_import_archive')
    @mock.patch('ide.api.project.build_c_template_archive')
    @mock.patch('ide.api.project.list_c_templates')
    def test_create_native_project_from_dynamic_template(self, list_templates, build_c_template_archive, import_archive):
        list_templates.return_value = [{'id': 'watchface-tutorial/part1'}]
        build_c_template_archive.return_value = b'zip-data'
        response = self.client.post('/ide/project/create', {
            'name': 'native-from-template',
            'type': 'native',
            'template': 'watchface-tutorial/part1',
            'sdk': '4.9.148',
        })
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        project = Project.objects.get(id=payload['id'])
        build_c_template_archive.assert_called_once_with('watchface-tutorial/part1')
        import_archive.assert_called_once_with(project.id, b'zip-data', delete_project=True)

    @mock.patch('ide.api.project.list_c_templates')
    def test_create_native_project_rejects_unknown_dynamic_template(self, list_templates):
        list_templates.return_value = []
        response = self.client.post('/ide/project/create', {
            'name': 'native-bad-template',
            'type': 'native',
            'template': 'watchface-tutorial/missing',
            'sdk': '4.9.148',
        })
        payload = json.loads(response.content)
        self.assertFalse(payload['success'])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.filter(name='native-bad-template').exists())

    @mock.patch('ide.api.project.do_import_archive')
    @mock.patch('ide.api.project.build_template_archive')
    @mock.patch('ide.api.project.list_alloy_templates')
    def test_create_alloy_project_from_dynamic_template(self, list_templates, build_template_archive, import_archive):
        list_templates.return_value = [{'id': 'hellopebble'}]
        build_template_archive.return_value = b'zip-data'
        def _import_side_effect(project_id, _bundle, delete_project=False):
            project = Project.objects.get(id=project_id)
            project.app_platforms = 'flint,emery'
            project.save()
        import_archive.side_effect = _import_side_effect
        response = self.client.post('/ide/project/create', {
            'name': 'alloy-from-template',
            'type': 'alloy',
            'alloy_template': 'hellopebble',
            'sdk': '4.9.148',
            'template': '0',
        })
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        project = Project.objects.get(id=payload['id'])
        build_template_archive.assert_called_once_with('hellopebble')
        import_archive.assert_called_once_with(project.id, b'zip-data', delete_project=True)
        self.assertEqual(project.app_platforms, 'flint,emery')

    @mock.patch('ide.api.project.list_alloy_templates')
    def test_create_alloy_project_falls_back_when_template_unavailable(self, list_templates):
        list_templates.return_value = []
        response = self.client.post('/ide/project/create', {
            'name': 'alloy-fallback',
            'type': 'alloy',
            'alloy_template': 'missing-template',
            'sdk': '4.9.148',
            'template': '0',
        })
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        project = Project.objects.get(id=payload['id'])
        self.assertTrue(SourceFile.objects.filter(project=project, file_name='main.js', target='embeddedjs').exists())

    def test_project_info_marks_binary_sources_read_only(self):
        response = self.client.post('/ide/project/create', {
            'name': 'alloy-binary-info',
            'type': 'alloy',
            'template': '0',
            'alloy_template': 'missing-template',
            'sdk': '4.9.148',
        })
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        project = Project.objects.get(id=payload['id'])
        binary = SourceFile.objects.create(project=project, file_name='emery/dial.png', target='embeddedjs')
        binary.save_string(b'\x89PNG\r\n')

        info = json.loads(self.client.get('/ide/project/{}/info'.format(project.id)).content)
        src = [x for x in info['source_files'] if x['name'] == 'emery/dial.png'][0]
        self.assertTrue(src['is_binary'])
        self.assertFalse(src['is_editable'])


class TestProjectSettingsApi(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='test', email='test@test.test', password='test')
        self.assertTrue(self.client.login(username='test', password='test'))
        self.project = Project.objects.create(owner=self.user, name='settings-sdk-test', project_type='native')

    def _settings_payload(self, sdk_version):
        return {
            'name': self.project.name,
            'app_uuid': self.project.app_uuid,
            'app_company_name': self.project.app_company_name or 'Test Co',
            'app_short_name': self.project.app_short_name or 'TestApp',
            'app_long_name': self.project.app_long_name or 'Test App',
            'app_version_label': self.project.app_version_label or '1.0',
            'app_is_watchface': '0',
            'app_is_hidden': '0',
            'app_is_shown_on_communication': '0',
            'app_capabilities': self.project.app_capabilities or '',
            'app_keys': self.project.app_keys or '[]',
            'app_jshint': '1',
            'sdk_version': sdk_version,
            'app_platforms': self.project.app_platforms or 'aplite,basalt',
            'app_modern_multi_js': '1',
            'menu_icon': '',
        }

    def test_save_settings_rejects_invalid_sdk(self):
        response = self.client.post('/ide/project/{}/save_settings'.format(self.project.id), self._settings_payload('4.9.77'))
        payload = json.loads(response.content)
        self.assertFalse(payload['success'])
        self.assertEqual(response.status_code, 400)
        self.project.refresh_from_db()
        self.assertEqual(self.project.sdk_version, '4.9.148')

    def test_save_settings_accepts_current_sdk(self):
        response = self.client.post('/ide/project/{}/save_settings'.format(self.project.id), self._settings_payload('4.9.148'))
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.sdk_version, '4.9.148')

    def test_save_settings_accepts_flint_for_embeddedjs(self):
        self.project.project_type = 'alloy'
        self.project.app_platforms = 'flint,emery'
        self.project.save()
        SourceFile.objects.create(project=self.project, file_name='main.js', target='embeddedjs').save_text('trace("x");')

        payload = self._settings_payload('4.9.148')
        payload['app_platforms'] = 'flint,emery'
        response = self.client.post('/ide/project/{}/save_settings'.format(self.project.id), payload)
        body = json.loads(response.content)
        self.assertTrue(body['success'])
        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.app_platforms, 'flint,emery')
