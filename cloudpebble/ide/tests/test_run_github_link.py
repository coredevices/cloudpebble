""" Tests for the appstore-source → import-deep-link translation in
ide.views.run. parse_github_source is the single authority on accepted
shapes; anything it rejects degrades to a plain repository link when a
user/repo pair is discernible, and to no link at all otherwise. """

from django.test import TestCase

from ide.views.run import _github_import_url


class TestGithubImportUrl(TestCase):
    def test_plain_repository(self):
        self.assertEqual('/ide/import/github/user/repo',
                         _github_import_url('https://github.com/user/repo'))

    def test_legacy_colon_form(self):
        self.assertEqual('/ide/import/github/user/repo',
                         _github_import_url('github.com:user/repo'))

    def test_tree_deep_link(self):
        self.assertEqual('/ide/import/github/user/repo/tree/main/faces/slothvec',
                         _github_import_url('github.com/user/repo/tree/main/faces/slothvec'))

    def test_blob_deep_link(self):
        self.assertEqual('/ide/import/github/user/repo/blob/main/src/app.js',
                         _github_import_url('https://github.com/user/repo/blob/main/src/app.js'))

    def test_unsafe_path_characters_are_reencoded(self):
        # The parser percent-decodes; the deep link must re-encode so the
        # href survives as one URL path.
        self.assertEqual('/ide/import/github/user/repo/tree/main/my%20dir',
                         _github_import_url('github.com/user/repo/tree/main/my%20dir'))
        self.assertEqual('/ide/import/github/user/repo/tree/main/foo%23bar',
                         _github_import_url('github.com/user/repo/tree/main/foo%23bar'))

    def test_ssh_port_form_makes_no_wrong_link(self):
        # '22/user' must never be read as a user/repo pair.
        self.assertEqual('', _github_import_url('ssh://git@github.com:22/user/repo'))

    def test_unrecognized_shapes_fall_back_to_the_repository(self):
        for source in ('https://github.com/user/repo/Blob/main/x',
                       'https://github.com/user/repo/releases',
                       'https://github.com/user/repo.git/issues/5'):
            self.assertEqual('/ide/import/github/user/repo',
                             _github_import_url(source), source)

    def test_url_inside_prose(self):
        self.assertEqual(
            '/ide/import/github/user/repo/tree/main/faces/x',
            _github_import_url('Source: https://github.com/user/repo/tree/main/faces/x, enjoy!'))

    def test_no_github_no_link(self):
        self.assertEqual('', _github_import_url(''))
        self.assertEqual('', _github_import_url('https://gitlab.com/user/repo'))
