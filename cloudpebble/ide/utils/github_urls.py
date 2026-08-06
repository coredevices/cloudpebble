""" Parsing for GitHub project "sources" — the strings users paste into the
import dialog or arrive with via /ide/import/github/... deep links (e.g. the
appstore's "Remix on CloudPebble" button, which links to
.../import/github/<user>/<repo>/tree/<branch>/<subdirectory>).

This module is deliberately dependency-free (no Django, no PyGithub) so it can
be unit-tested standalone. Anything that needs the network — resolving which
prefix of an ambiguous "<ref>/<path>" remainder is a real branch — lives in
ide.tasks.git and uses split_ref_and_path() from here with a real ref list.
"""
import posixpath
import re
from collections import namedtuple
from urllib.parse import unquote

__author__ = 'emindeniz99'

# A parsed source:
#   user, project: the repository coordinates.
#   kind: None (plain repo), 'tree', 'blob' or 'commit'.
#   refpath: the raw remainder after /tree/ or /blob/ — "<ref>" or
#     "<ref>/<path>". GitHub branch names may contain slashes, so the split
#     between ref and path can only be decided against the repository's real
#     ref names (split_ref_and_path below).
GithubSource = namedtuple('GithubSource', ['user', 'project', 'kind', 'refpath'])

# Accepted forms (raw query strings and fragments are stripped before
# percent-decoding, so encoded delimiters survive inside path segments):
#   user/repo
#   github.com/user/repo[.git][/]           (bare, http, https, www; the
#                                            legacy 'github.com:user/repo'
#                                            colon form stays accepted)
#   git@github.com:user/repo[.git]
#   git://github.com/user/repo[.git]
#   .../user/repo/tree/<ref>[/<path>]
#   .../user/repo/blob/<ref>/<path-to-file>
#   .../user/repo/commit/<sha>
# Anything else after the repo (releases, issues, wiki, ...) is rejected so a
# nonsensical import fails loudly instead of silently importing the repo root.
_SOURCE_RE = re.compile(r"""
    ^
    (?:
        (?i:(?:https?://)?(?:www\.)?github\.com)[/:] |
        (?i:git@github\.com): |
        (?i:git://github\.com)/
    )?
    (?P<user>[\w.-]+)
    /
    (?P<project>[\w.-]+?)
    (?:\.git)?
    (?:
        /
        (?:
            (?P<kind>tree|blob|commit)
            (?:
                /
                (?P<refpath>.+?)
            )?
        )?
    )?
    /?
    $
""", re.VERBOSE)


def parse_github_source(source):
    """ Parse a GitHub repository source string.
    :param source: whatever the user gave us (URL, shorthand, deep-link tail).
    :return: a GithubSource, or None if this isn't a recognizable GitHub source.
    """
    # Split the RAW string on the query/fragment delimiters first, THEN
    # percent-decode: an encoded '#' or '?' inside a path segment
    # (…/tree/main/faces/foo%23bar) is data, not a delimiter.
    raw = source.strip().split('#', 1)[0].split('?', 1)[0]
    match = _SOURCE_RE.match(unquote(raw))
    if match is None:
        return None
    kind = match.group('kind')
    refpath = match.group('refpath')
    if refpath is not None:
        refpath = refpath.strip('/')
    if not refpath:
        # "…/repo/tree/" and "…/repo/tree" carry no information — treat as the
        # plain repository rather than rejecting the whole import.
        kind, refpath = None, None
    return GithubSource(match.group('user'), match.group('project'), kind, refpath)


def split_ref_qualifier(refpath):
    """ Strip GitHub's self-qualified "refs/heads/..." / "refs/tags/..."
    spelling (which its Raw button emits) off a /tree/ or /blob/ remainder.

    This is the single authority for the rule — the ref resolver and the
    import API both need it, and a second copy could silently drift.

    :return: (namespaces, refpath) — the namespaces the URL pinned
        (('heads',) or ('tags',), or both when unqualified) and the
        remainder without the qualifier.
    """
    parts = refpath.split('/')
    if len(parts) >= 3 and parts[0] == 'refs' and parts[1] in ('heads', 'tags'):
        return (parts[1],), '/'.join(parts[2:])
    return ('heads', 'tags'), refpath


def split_ref_and_path(refpath, ref_names):
    """ Split a /tree/ or /blob/ remainder into (ref, path).

    GitHub branch names may contain slashes ("feature/foo"), so "a/b/c" is
    ambiguous between ref "a/b" + path "c" and ref "a" + path "b/c". We match
    the remainder against the repository's REAL ref names, longest prefix
    first (the approach used by gitpick and gitingest; create-next-app instead
    naive-splits and asks the user for --example-path in the ambiguous case).
    Git's directory/file conflict rule means at most ONE branch and at most
    ONE tag can prefix-match, so the split is deterministic — longest-first
    only decides the cross-namespace case (tag "release" vs branch
    "release/1.0") in favor of the more specific ref.

    Callers strip GitHub's self-qualified refs/heads|tags spelling first,
    with split_ref_qualifier() — which also tells them which namespace the
    URL pinned, something this function has no use for.

    :param refpath: "<ref>" or "<ref>/<path>" (slashes and any refs/...
        qualifier already stripped).
    :param ref_names: iterable of the repository's ref names in the
        namespaces the URL allows. Pass None when the list is unavailable —
        the first segment is then taken as the ref, which is correct for
        every ref without a slash in its name (commit SHAs included, since a
        SHA is never slashed).
    :return: (ref, path) — path is '' when the remainder is just a ref.
    """
    parts = refpath.split('/')
    if len(parts) == 1:
        return refpath, ''
    if ref_names is not None:
        names = set(ref_names)
        for i in range(len(parts), 0, -1):
            candidate = '/'.join(parts[:i])
            if candidate in names:
                return candidate, '/'.join(parts[i:])
    return parts[0], '/'.join(parts[1:])


def normalize_subpath(path):
    """ Normalize a repo-relative subdirectory: collapse separators, forbid
    escapes. Returns '' for the repo root; raises ValueError on '..' or
    absolute paths (deep links are attacker-suppliable). """
    if not path:
        return ''
    if '..' in path.split('/'):
        # Reject '..' outright rather than letting cancelling segments
        # normalize away — deep links are attacker-suppliable and there is no
        # legitimate reason for a GitHub tree URL to contain '..'.
        raise ValueError("Invalid project path: %r" % path)
    normalized = posixpath.normpath(path.strip('/'))
    if normalized in ('.', ''):
        return ''
    if normalized.startswith(('/', '..')):
        raise ValueError("Invalid project path: %r" % path)
    return normalized
