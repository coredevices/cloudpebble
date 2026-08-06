""" Tests for the GitHub-import ref/path resolution in ide.tasks.git —
resolve_ref_and_path() with the GitHub API mocked out, and the strict
codeload probe fallback with file_exists mocked — plus the /ide/import/github
API flows around linking (add_remote). """

import json
from unittest import mock

from django.test import TestCase

from ide.models.project import Project
from ide.tasks.git import resolve_ref_and_path
from ide.utils.cloudpebble_test import CloudpebbleTestCase


@mock.patch('ide.tasks.git.get_ref_names')
class TestResolveRefAndPath(TestCase):
    REFS = ['main', 'develop', 'feature/foo', 'v1.0.0']

    def test_api_split(self, get_ref_names):
        get_ref_names.return_value = self.REFS
        self.assertEqual(('main', 'faces/slothvec'),
                         resolve_ref_and_path(None, 'u', 'r', 'main/faces/slothvec', 'tree'))

    def test_api_split_slashed_branch(self, get_ref_names):
        get_ref_names.return_value = self.REFS
        self.assertEqual(('feature/foo', 'src'),
                         resolve_ref_and_path(None, 'u', 'r', 'feature/foo/src', 'tree'))

    def test_blob_resolves_to_the_files_directory(self, get_ref_names):
        get_ref_names.return_value = self.REFS
        self.assertEqual(('main', 'faces'),
                         resolve_ref_and_path(None, 'u', 'r', 'main/faces/app.js', 'blob'))

    def test_commit_passthrough(self, get_ref_names):
        self.assertEqual(('abc1234', ''),
                         resolve_ref_and_path(None, 'u', 'r', 'abc1234', 'commit'))
        get_ref_names.assert_not_called()

    def test_invalid_path_fails_loud(self, get_ref_names):
        get_ref_names.return_value = self.REFS
        with self.assertRaises(Exception):
            resolve_ref_and_path(None, 'u', 'r', 'main/../etc', 'tree')

    @mock.patch('ide.tasks.git.file_exists')
    def test_probe_fallback_longest_first(self, file_exists, get_ref_names):
        get_ref_names.return_value = None
        probed = []

        def fake_exists(url):
            probed.append(url)
            return url.endswith('/zip/refs/heads/feature/foo')
        file_exists.side_effect = fake_exists

        self.assertEqual(('feature/foo', 'src'),
                         resolve_ref_and_path(None, 'u', 'r', 'feature/foo/src', 'tree'))
        # Longest candidate first, strict refs-qualified codeload URLs only.
        self.assertIn('https://codeload.github.com/u/r/zip/refs/heads/feature/foo/src', probed)
        self.assertTrue(all('/zip/refs/' in url for url in probed))

    @mock.patch('ide.tasks.git.file_exists')
    def test_probe_strips_refs_qualifier_and_pins_namespace(self, file_exists, get_ref_names):
        get_ref_names.return_value = None
        probed = []

        def fake_exists(url):
            probed.append(url)
            return url.endswith('/zip/refs/heads/feature/foo')
        file_exists.side_effect = fake_exists

        # refs/heads/feature/foo/src: candidates must NOT start with refs/heads/
        # a second time, and refs/tags/ must never be probed.
        self.assertEqual(('feature/foo', 'src'),
                         resolve_ref_and_path(None, 'u', 'r', 'refs/heads/feature/foo/src', 'tree'))
        self.assertTrue(all('/zip/refs/heads/' in url for url in probed))
        self.assertTrue(all('refs/heads/refs' not in url for url in probed))

    @mock.patch('ide.tasks.git.file_exists')
    def test_probe_quotes_unsafe_ref_characters(self, file_exists, get_ref_names):
        # A branch may legally contain '#' or '?'; raw in a probe URL they
        # would truncate the request path into a fragment/query.
        get_ref_names.return_value = None
        probed = []

        def fake_exists(url):
            probed.append(url)
            return url.endswith('/zip/refs/heads/bug%237')
        file_exists.side_effect = fake_exists

        self.assertEqual(('bug#7', 'src'),
                         resolve_ref_and_path(None, 'u', 'r', 'bug#7/src', 'tree'))
        self.assertTrue(all('#' not in url for url in probed))

    @mock.patch('ide.tasks.git.file_exists')
    def test_probe_miss_falls_back_to_first_segment(self, file_exists, get_ref_names):
        get_ref_names.return_value = None
        file_exists.return_value = False
        self.assertEqual(('main', 'faces/slothvec'),
                         resolve_ref_and_path(None, 'u', 'r', 'main/faces/slothvec', 'tree'))


@mock.patch('ide.api.project.do_import_github')
class TestImportGithubApi(CloudpebbleTestCase):
    """ The linking (add_remote) rules of POST /ide/import/github. """

    def setUp(self):
        self.login()

    def import_repo(self, do_import_github, repo, add_remote='false', branch=''):
        do_import_github.delay.return_value.task_id = 'task-id'
        return self.client.post('/ide/import/github', {
            'name': 'imported', 'repo': repo, 'branch': branch, 'add_remote': add_remote})

    def test_branch_only_tree_url_keeps_linking(self, do_import_github):
        result = json.loads(self.import_repo(
            do_import_github, 'github.com/u/r/tree/main', add_remote='true').content)
        self.assertTrue(result['success'], msg=result.get('error'))
        project = Project.objects.get(pk=result['project_id'])
        self.assertEqual(project.github_repo, 'u/r')
        self.assertEqual(project.github_branch, 'main')
        args, kwargs = do_import_github.delay.call_args
        self.assertEqual(args[3], 'main')
        self.assertIsNone(kwargs['github_refpath'])

    def test_subdirectory_with_linking_is_rejected(self, do_import_github):
        response = self.import_repo(
            do_import_github, 'github.com/u/r/tree/main/faces/x', add_remote='true')
        self.assertEqual(response.status_code, 400)
        self.assertIn('subdirectory imports', json.loads(response.content)['error'])
        do_import_github.delay.assert_not_called()

    def test_commit_with_linking_is_rejected_with_its_own_reason(self, do_import_github):
        response = self.import_repo(
            do_import_github, 'github.com/u/r/commit/abc123', add_remote='true')
        self.assertEqual(response.status_code, 400)
        self.assertIn('commit imports', json.loads(response.content)['error'])
        do_import_github.delay.assert_not_called()

    def test_subdirectory_without_linking_passes_the_refpath(self, do_import_github):
        result = json.loads(self.import_repo(
            do_import_github, 'github.com/u/r/tree/main/faces/x').content)
        self.assertTrue(result['success'], msg=result.get('error'))
        args, kwargs = do_import_github.delay.call_args
        self.assertEqual(args[3], '')
        self.assertEqual(kwargs['github_refpath'], 'main/faces/x')
        self.assertEqual(kwargs['github_kind'], 'tree')
