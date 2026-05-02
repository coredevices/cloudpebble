import json
import tempfile
import shutil
import os

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.test.client import Client

from ide.models import Project
from ide.models.project import EnvironmentVariable
from ide.utils.crypto import encrypt_value, decrypt_value, ENV_VAR_MASK
from ide.utils.sdk.project_assembly import assemble_project


@override_settings(SECRET_KEY='test-secret-key-for-testing-12345')
class TestCrypto(TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        plaintext = 'my-secret-api-key'
        ciphertext = encrypt_value(plaintext)
        self.assertNotEqual(ciphertext, plaintext)
        self.assertEqual(decrypt_value(ciphertext), plaintext)

    def test_encrypt_different_values_produce_different_ciphertexts(self):
        ct1 = encrypt_value('value1')
        ct2 = encrypt_value('value2')
        self.assertNotEqual(ct1, ct2)

    def test_encrypt_same_value_produces_different_ciphertexts(self):
        ct1 = encrypt_value('same-value')
        ct2 = encrypt_value('same-value')
        self.assertNotEqual(ct1, ct2)
        self.assertEqual(decrypt_value(ct1), decrypt_value(ct2))

    def test_encrypt_empty_string(self):
        ciphertext = encrypt_value('')
        self.assertEqual(decrypt_value(ciphertext), '')

    def test_env_var_mask_constant(self):
        self.assertEqual(ENV_VAR_MASK, '******')


@override_settings(SECRET_KEY='test-secret-key-for-testing-12345')
class TestEnvironmentVariableModel(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.post('/accounts/register', {
            'username': 'test',
            'email': 'test@test.test',
            'password1': 'test',
            'password2': 'test',
        })
        self.assertTrue(self.client.login(username='test', password='test'))
        result = json.loads(self.client.post('/ide/project/create', {
            'name': 'envtest',
            'template': 0,
            'type': 'native',
            'sdk': '4.9.148',
        }).content)
        self.project_id = result['id']
        self.project = Project.objects.get(pk=self.project_id)

    def test_create_env_var(self):
        ev = EnvironmentVariable.objects.create(
            project=self.project,
            key='API_KEY',
            encrypted_value=encrypt_value('secret123')
        )
        self.assertEqual(ev.key, 'API_KEY')
        self.assertEqual(decrypt_value(ev.encrypted_value), 'secret123')

    def test_env_var_unique_key_per_project(self):
        EnvironmentVariable.objects.create(
            project=self.project,
            key='DUPLICATE_KEY',
            encrypted_value=encrypt_value('value1')
        )
        with self.assertRaises(ValidationError):
            ev = EnvironmentVariable(
                project=self.project,
                key='DUPLICATE_KEY',
                encrypted_value=encrypt_value('value2')
            )
            ev.full_clean()
            ev.save()


@override_settings(SECRET_KEY='test-secret-key-for-testing-12345')
class TestSaveEnvVarsAPI(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.post('/accounts/register', {
            'username': 'test',
            'email': 'test@test.test',
            'password1': 'test',
            'password2': 'test',
        })
        self.assertTrue(self.client.login(username='test', password='test'))
        result = json.loads(self.client.post('/ide/project/create', {
            'name': 'envtest',
            'template': 0,
            'type': 'native',
            'sdk': '4.9.148',
        }).content)
        self.project_id = result['id']

    def test_save_env_vars(self):
        response = self.client.post('/ide/project/%d/save_env_vars' % self.project_id, {
            'env_vars': json.dumps([
                {'key': 'API_KEY', 'value': 'secret123'},
                {'key': 'DB_HOST', 'value': 'localhost'},
            ])
        })
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        env_vars = payload['env_vars']
        self.assertEqual(len(env_vars), 2)
        keys = [ev[0] for ev in env_vars]
        self.assertIn('API_KEY', keys)
        self.assertIn('DB_HOST', keys)
        for ev in env_vars:
            self.assertEqual(ev[1], ENV_VAR_MASK)

        ev = EnvironmentVariable.objects.get(project_id=self.project_id, key='API_KEY')
        self.assertEqual(decrypt_value(ev.encrypted_value), 'secret123')

    def test_save_env_vars_preserves_unchanged(self):
        self.client.post('/ide/project/%d/save_env_vars' % self.project_id, {
            'env_vars': json.dumps([
                {'key': 'API_KEY', 'value': 'original_secret'},
            ])
        })
        original_ev = EnvironmentVariable.objects.get(project_id=self.project_id, key='API_KEY')
        original_ciphertext = original_ev.encrypted_value

        response = self.client.post('/ide/project/%d/save_env_vars' % self.project_id, {
            'env_vars': json.dumps([
                {'key': 'API_KEY', 'value': ENV_VAR_MASK},
            ])
        })
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])

        updated_ev = EnvironmentVariable.objects.get(project_id=self.project_id, key='API_KEY')
        self.assertEqual(updated_ev.encrypted_value, original_ciphertext)
        self.assertEqual(decrypt_value(updated_ev.encrypted_value), 'original_secret')

    def test_save_env_vars_rejects_invalid_key(self):
        response = self.client.post('/ide/project/%d/save_env_vars' % self.project_id, {
            'env_vars': json.dumps([
                {'key': '123INVALID', 'value': 'test'},
            ])
        })
        payload = json.loads(response.content)
        self.assertFalse(payload['success'])

    def test_save_env_vars_rejects_duplicate_keys(self):
        response = self.client.post('/ide/project/%d/save_env_vars' % self.project_id, {
            'env_vars': json.dumps([
                {'key': 'DUPE', 'value': 'val1'},
                {'key': 'DUPE', 'value': 'val2'},
            ])
        })
        payload = json.loads(response.content)
        self.assertFalse(payload['success'])

    def test_project_info_includes_env_vars(self):
        self.client.post('/ide/project/%d/save_env_vars' % self.project_id, {
            'env_vars': json.dumps([
                {'key': 'MY_VAR', 'value': 'my_value'},
            ])
        })
        response = self.client.get('/ide/project/%d/info' % self.project_id)
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        env_vars = payload['env_vars']
        self.assertEqual(len(env_vars), 1)
        self.assertEqual(env_vars[0][0], 'MY_VAR')
        self.assertEqual(env_vars[0][1], ENV_VAR_MASK)

    def test_save_env_vars_deletes_removed_vars(self):
        self.client.post('/ide/project/%d/save_env_vars' % self.project_id, {
            'env_vars': json.dumps([
                {'key': 'KEEP', 'value': 'val1'},
                {'key': 'REMOVE', 'value': 'val2'},
            ])
        })
        self.assertEqual(EnvironmentVariable.objects.filter(project_id=self.project_id).count(), 2)

        response = self.client.post('/ide/project/%d/save_env_vars' % self.project_id, {
            'env_vars': json.dumps([
                {'key': 'KEEP', 'value': ENV_VAR_MASK},
            ])
        })
        payload = json.loads(response.content)
        self.assertTrue(payload['success'])
        self.assertEqual(EnvironmentVariable.objects.filter(project_id=self.project_id).count(), 1)
        self.assertTrue(EnvironmentVariable.objects.filter(project_id=self.project_id, key='KEEP').exists())


@override_settings(SECRET_KEY='test-secret-key-for-testing-12345', AWS_ENABLED=False)
class TestEnvVarsInProjectAssembly(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.post('/accounts/register', {
            'username': 'test',
            'email': 'test@test.test',
            'password1': 'test',
            'password2': 'test',
        })
        self.assertTrue(self.client.login(username='test', password='test'))
        result = json.loads(self.client.post('/ide/project/create', {
            'name': 'envtest',
            'template': 0,
            'type': 'native',
            'sdk': '4.9.148',
        }).content)
        self.project_id = result['id']
        self.project = Project.objects.get(pk=self.project_id)

    def _create_source_file(self, name, contents, target='pkjs'):
        from ide.models.files import SourceFile
        source = SourceFile.objects.create(project=self.project, file_name=name, target=target)
        source.save_text(contents)
        return source

    def _assemble_and_read(self, filename):
        base_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base_dir)
        assemble_project(self.project, base_dir)
        js_path = os.path.join(base_dir, 'src', 'pkjs', filename)
        with open(js_path, 'r') as f:
            return f.read()

    def test_process_env_substituted_in_pkjs_files(self):
        self._create_source_file('index.js', 'var key = process.env.API_KEY; var host = process.env.DB_HOST;')
        EnvironmentVariable.objects.create(
            project=self.project,
            key='API_KEY',
            encrypted_value=encrypt_value('secret123')
        )
        EnvironmentVariable.objects.create(
            project=self.project,
            key='DB_HOST',
            encrypted_value=encrypt_value('db.example.com')
        )
        content = self._assemble_and_read('index.js')
        self.assertIn('"secret123"', content)
        self.assertIn('"db.example.com"', content)
        self.assertNotIn('process.env.API_KEY', content)
        self.assertNotIn('process.env.DB_HOST', content)

    def test_unknown_process_env_left_unchanged(self):
        self._create_source_file('index.js', 'var x = process.env.UNKNOWN_VAR;')
        EnvironmentVariable.objects.create(
            project=self.project,
            key='API_KEY',
            encrypted_value=encrypt_value('secret123')
        )
        content = self._assemble_and_read('index.js')
        self.assertIn('process.env.UNKNOWN_VAR', content)
        self.assertNotIn('process.env.API_KEY', content)

    def test_no_substitution_when_no_env_vars(self):
        self._create_source_file('index.js', 'var key = process.env.API_KEY;')
        content = self._assemble_and_read('index.js')
        self.assertIn('process.env.API_KEY', content)

    def test_value_with_double_quotes_is_escaped(self):
        self._create_source_file('index.js', 'var x = process.env.MSG;')
        EnvironmentVariable.objects.create(
            project=self.project,
            key='MSG',
            encrypted_value=encrypt_value('he said "hello"')
        )
        content = self._assemble_and_read('index.js')
        self.assertIn('"he said \\"hello\\""', content)
        self.assertNotIn('process.env.MSG', content)

    def test_value_with_single_quotes_is_valid_json(self):
        self._create_source_file('index.js', "var x = process.env.MSG;")
        EnvironmentVariable.objects.create(
            project=self.project,
            key='MSG',
            encrypted_value=encrypt_value("it's working")
        )
        content = self._assemble_and_read('index.js')
        parsed = json.loads('{' + content.replace('var x = ', '"result":').rstrip(';') + '}')
        self.assertEqual(parsed['result'], "it's working")

    def test_value_with_newline_is_escaped(self):
        self._create_source_file('index.js', 'var x = process.env.MSG;')
        EnvironmentVariable.objects.create(
            project=self.project,
            key='MSG',
            encrypted_value=encrypt_value('line1\nline2')
        )
        content = self._assemble_and_read('index.js')
        self.assertNotIn('\n', content.split('= ', 1)[1].rstrip(';'))
        self.assertIn('\\n', content)
