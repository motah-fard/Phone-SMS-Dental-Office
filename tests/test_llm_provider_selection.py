"""
Proves the LLM_PROVIDER env var actually switches which module
sms_conversation.py binds handle_open_ended to -- the whole point of
having two provider files is that this switch works, so it's worth
testing directly rather than trusting the branch by inspection.

Reloads the module to re-run its module-level import logic under a
different environment, then reloads it back to the default afterward
so this doesn't affect any other test's behavior.
"""
import importlib

import sms_conversation as sc


def test_llm_provider_openai_selects_openai_module(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    try:
        importlib.reload(sc)
        assert sc.handle_open_ended.__module__ == "llm_fallback_openai"
    finally:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        importlib.reload(sc)


def test_llm_provider_default_selects_anthropic_module():
    assert sc.handle_open_ended.__module__ == "llm_fallback"
