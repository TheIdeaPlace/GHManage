"""Single source of truth for the GHManage version.

Must be a plain SemVer string — `vpk pack --packVersion` rejects 4-part
versions. CI checks this against the release tag and fails if they differ,
so bump it in the same commit as the tag.
"""

__version__ = "0.9.2"
