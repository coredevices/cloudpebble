""" Tests for ide.utils.github_urls — the GitHub source parser behind the
import dialog and the /ide/import/github/... deep links (including the
appstore's "Remix on CloudPebble" button URLs). Dependency-free on purpose:
    python -m unittest ide.tests.test_github_urls
"""

from unittest import TestCase

from ide.utils.github_urls import parse_github_source, split_ref_and_path, normalize_subpath


class TestParseGithubSource(TestCase):
    def assert_parsed(self, source, user, project, kind=None, refpath=None):
        parsed = parse_github_source(source)
        self.assertIsNotNone(parsed, "expected %r to parse" % source)
        self.assertEqual(
            (user, project, kind, refpath),
            (parsed.user, parsed.project, parsed.kind, parsed.refpath),
        )

    def test_bare_shorthand(self):
        self.assert_parsed('Katharine/pebble-stopwatch', 'Katharine', 'pebble-stopwatch')

    def test_plain_domain(self):
        self.assert_parsed('github.com/user/repo', 'user', 'repo')

    def test_https_www_git_suffix_trailing_slash(self):
        self.assert_parsed('https://www.github.com/user/repo.git/', 'user', 'repo')

    def test_ssh_form(self):
        self.assert_parsed('git@github.com:user/repo.git', 'user', 'repo')

    def test_git_protocol(self):
        self.assert_parsed('git://github.com/user/repo', 'user', 'repo')

    def test_dotted_names(self):
        self.assert_parsed('github.com/user.name/repo.js', 'user.name', 'repo.js')

    def test_tree_with_branch(self):
        self.assert_parsed('https://github.com/user/repo/tree/main', 'user', 'repo', 'tree', 'main')

    def test_tree_with_branch_and_subpath(self):
        # The appstore "Remix" button shape.
        self.assert_parsed(
            'github.com/emindeniz99/pebble-signals/tree/main/faces/slothvec',
            'emindeniz99', 'pebble-signals', 'tree', 'main/faces/slothvec')

    def test_blob_form(self):
        self.assert_parsed(
            'https://github.com/user/repo/blob/main/src/app.js',
            'user', 'repo', 'blob', 'main/src/app.js')

    def test_commit_form(self):
        self.assert_parsed('github.com/user/repo/commit/abc123', 'user', 'repo', 'commit', 'abc123')

    def test_query_and_fragment_stripped(self):
        self.assert_parsed(
            'https://github.com/user/repo/tree/main/dir?tab=readme#l10',
            'user', 'repo', 'tree', 'main/dir')

    def test_empty_tree_tail_is_plain_repo(self):
        self.assert_parsed('github.com/user/repo/tree/', 'user', 'repo')

    def test_rejects_other_github_pages(self):
        for source in ('github.com/user/repo/releases',
                       'github.com/user/repo/issues/12',
                       'github.com/user/repo/pull/3',
                       'github.com/user/repo/wiki'):
            self.assertIsNone(parse_github_source(source), source)

    def test_case_insensitive_host(self):
        self.assert_parsed('GitHub.com/user/repo', 'user', 'repo')
        self.assert_parsed('HTTPS://WWW.GITHUB.COM/user/repo', 'user', 'repo')

    def test_percent_encoded_input(self):
        self.assert_parsed('github.com/user/repo/tree/main/my%20dir',
                           'user', 'repo', 'tree', 'main/my dir')

    def test_legacy_colon_form(self):
        # The pre-parser server regex matched github.com[/:], so links using a
        # bare colon after the domain must keep importing.
        self.assert_parsed('github.com:user/repo', 'user', 'repo')
        self.assert_parsed('https://github.com:user/repo.git', 'user', 'repo')

    def test_legacy_regex_parity(self):
        # Every form the OLD import regex accepted (it truncated at the repo
        # name) must still parse to the same user/project pair.
        for source in ('https://github.com/user/repo',
                       'http://github.com/user/repo',
                       'www.github.com/user/repo',
                       'git@github.com:user/repo',
                       'git://github.com/user/repo',
                       'github.com/user/repo.git',
                       'github.com/user/repo/'):
            self.assert_parsed(source, 'user', 'repo')

    def test_rejects_non_github(self):
        for source in ('gitlab.com/user/repo', 'https://example.com/user/repo', 'user', ''):
            self.assertIsNone(parse_github_source(source), source)


class TestSplitRefAndPath(TestCase):
    REFS = ['main', 'develop', 'feature/foo', 'feature/foo/bar', 'v1.0.0']

    def test_plain_ref(self):
        self.assertEqual(('main', ''), split_ref_and_path('main', self.REFS))

    def test_ref_and_path(self):
        self.assertEqual(('main', 'faces/slothvec'),
                         split_ref_and_path('main/faces/slothvec', self.REFS))

    def test_slashed_ref_wins_over_short_ref(self):
        self.assertEqual(('feature/foo', 'src'),
                         split_ref_and_path('feature/foo/src', self.REFS))

    def test_longest_ref_wins(self):
        self.assertEqual(('feature/foo/bar', 'src'),
                         split_ref_and_path('feature/foo/bar/src', self.REFS))

    def test_tag_ref(self):
        self.assertEqual(('v1.0.0', 'dir'), split_ref_and_path('v1.0.0/dir', self.REFS))

    def test_unknown_ref_falls_back_to_first_segment(self):
        self.assertEqual(('sha123', 'a/b'), split_ref_and_path('sha123/a/b', self.REFS))

    def test_refs_heads_spelling(self):
        self.assertEqual(('feature/foo', 'src'),
                         split_ref_and_path('refs/heads/feature/foo/src', self.REFS))

    def test_refs_tags_spelling(self):
        self.assertEqual(('v1.0.0', 'dir'),
                         split_ref_and_path('refs/tags/v1.0.0/dir', self.REFS))

    def test_no_ref_list_falls_back_to_first_segment(self):
        self.assertEqual(('main', 'faces/slothvec'),
                         split_ref_and_path('main/faces/slothvec', None))


class TestNormalizeSubpath(TestCase):
    def test_empty_and_root(self):
        self.assertEqual('', normalize_subpath(''))
        self.assertEqual('', normalize_subpath(None))
        self.assertEqual('', normalize_subpath('/'))
        self.assertEqual('', normalize_subpath('.'))

    def test_collapses(self):
        self.assertEqual('faces/slothvec', normalize_subpath('/faces//slothvec/'))
        self.assertEqual('a/b', normalize_subpath('a/./b'))

    def test_rejects_escapes(self):
        for bad in ('..', '../x', 'a/../../b'):
            with self.assertRaises(ValueError):
                normalize_subpath(bad)
