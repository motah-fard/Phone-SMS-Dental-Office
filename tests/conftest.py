"""
Shared pytest fixtures. Every module in this repo does its own manual
sys.path.insert() based on __file__ location (no packages/__init__.py) --
this file follows the same convention rather than introducing a second
import style, so it puts every source directory on sys.path once, here,
for all tests.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
for subdir in ("scripts", "mirror_system", "source_system", "conversation", "integrations"):
    sys.path.insert(0, str(ROOT / subdir))

from init_source_db import init_db as init_source_db  # noqa: E402
from init_mirror_db import init_mirror_db, init_lookup_db  # noqa: E402
import sync as sync_module  # noqa: E402
from audit_log import AUDIT_DB  # noqa: E402
from conversation_store import STATE_DB  # noqa: E402


@pytest.fixture
def fresh_db():
    """Rebuilds source + mirror + identity_lookup from scratch and syncs
    them, then clears the audit log and conversation-state store -- the
    same sequence scripts/demo.py runs, reused here so tests and the
    manual demo never drift apart. Function-scoped: every test gets a
    clean, known dataset."""
    init_source_db()
    init_mirror_db()
    init_lookup_db()
    sync_module.sync()
    if AUDIT_DB.exists():
        AUDIT_DB.unlink()
    if STATE_DB.exists():
        STATE_DB.unlink()
    yield
