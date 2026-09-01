"""
conversation/rollout_stage.py -- reloaded under different ROLLOUT_STAGE
env values (it reads the env var at import time), same technique as
test_llm_provider_selection.py.
"""
import importlib

import rollout_stage as rs


def _reload_with_stage(monkeypatch, stage):
    monkeypatch.setenv("ROLLOUT_STAGE", stage)
    importlib.reload(rs)


def test_default_stage_is_full_when_unset(monkeypatch):
    monkeypatch.delenv("ROLLOUT_STAGE", raising=False)
    importlib.reload(rs)
    try:
        assert rs.is_enabled("reschedule") is True
        assert rs.is_enabled("booking") is True
    finally:
        importlib.reload(rs)


def test_confirmations_only_disables_reschedule_and_booking(monkeypatch):
    _reload_with_stage(monkeypatch, "confirmations_only")
    try:
        assert rs.is_enabled("reschedule") is False
        assert rs.is_enabled("booking") is False
    finally:
        monkeypatch.delenv("ROLLOUT_STAGE", raising=False)
        importlib.reload(rs)


def test_reschedule_stage_enables_reschedule_not_booking(monkeypatch):
    _reload_with_stage(monkeypatch, "reschedule")
    try:
        assert rs.is_enabled("reschedule") is True
        assert rs.is_enabled("booking") is False
    finally:
        monkeypatch.delenv("ROLLOUT_STAGE", raising=False)
        importlib.reload(rs)


def test_full_stage_enables_everything(monkeypatch):
    _reload_with_stage(monkeypatch, "full")
    try:
        assert rs.is_enabled("reschedule") is True
        assert rs.is_enabled("booking") is True
    finally:
        importlib.reload(rs)


def test_invalid_stage_raises_at_import_time(monkeypatch):
    monkeypatch.setenv("ROLLOUT_STAGE", "not_a_real_stage")
    try:
        import pytest
        with pytest.raises(ValueError):
            importlib.reload(rs)
    finally:
        monkeypatch.delenv("ROLLOUT_STAGE", raising=False)
        importlib.reload(rs)


def test_unknown_capability_raises():
    import pytest
    with pytest.raises(ValueError):
        rs.is_enabled("delete_the_database")
