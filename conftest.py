"""Pytest configuration for the cparser repo.

The ``tests`` directory contains a self-referential symlink
(``tests/cparser -> ..``) that exists so the test modules can do plain
``import cparser.X`` without sys.path manipulation.  Pytest's default
collector follows that link, recurses infinitely, and eventually
deadlocks (or runs out of file descriptors).  We block the descent
here so ``python -m pytest`` from the cparser-repo root is safe.
"""

import os
import sys

# The tests do plain ``import helpers_test`` (not package-relative), so
# the tests dir must be on sys.path when pytest is invoked from the
# cparser-repo root.
_TESTS_DIR = os.path.join(os.path.dirname(__file__), "tests")
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

# Skip the symlinked self-reference when collecting tests.
collect_ignore_glob = [
    "tests/cparser",
    "tests/cparser/*",
]


def pytest_collection_modifyitems(config, items):
    """Drop any item discovered via the ``tests/cparser`` symlink
    (belt-and-braces in case the glob above misses some collector
    entry point)."""
    sym_path = os.path.join(
        os.path.dirname(__file__), "tests", "cparser") + os.sep
    items[:] = [it for it in items
                if not str(it.fspath).startswith(sym_path)]
