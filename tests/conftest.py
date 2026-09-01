"""Keep every automated test away from the user's real application data."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile


_REAL_HOME = Path.home()
_TEST_HOME = Path(tempfile.mkdtemp(prefix="juice-lyrics-tests-"))

# This runs while pytest loads conftest, before test modules import the package
# and freeze Path.home()/XDG-derived constants.
os.environ["HOME"] = str(_TEST_HOME)
os.environ["XDG_CONFIG_HOME"] = str(_TEST_HOME / ".config")
os.environ["XDG_CACHE_HOME"] = str(_TEST_HOME / ".cache")
os.environ["XDG_DATA_HOME"] = str(_TEST_HOME / ".local" / "share")


def pytest_sessionstart(session) -> None:
    if Path.home() == _REAL_HOME or Path.home() != _TEST_HOME:
        raise RuntimeError("Tests refused to run with the real HOME")


def pytest_sessionfinish(session, exitstatus) -> None:
    shutil.rmtree(_TEST_HOME, ignore_errors=True)
