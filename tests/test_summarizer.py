"""Tests for the tiered summarization backend."""

import json
import os
import pytest
from unittest.mock import MagicMock, patch

from sigil_core.summarizer import (
    detect_backend,
    ollama_available,
    summarize,
    summarize_via_ollama,
    summarize_via_litellm,
    _make_prompt,
)

_SAMPLE_CODE = "def create_session(user_id: int) -> str:\n    token = generate_token(user_id)\n    db.save(token)\n    return token\n"


# ── prompt ───────────────────────────────────────────────────────────────────

def test_prompt_contains_name():
    p = _make_prompt("create_session", "function", _SAMPLE_CODE)
    assert "create_session" in p


def test_prompt_contains_code():
    p = _make_prompt("create_session", "function", _SAMPLE_CODE)
    assert "generate_token" in p


def test_prompt_truncates_long_source():
    long_code = "x = 1\n" * 300
    p = _make_prompt("foo", "function", long_code)
    assert len(p) < 1500  # 700 char code cap keeps prompt manageable


# ── detect_backend ───────────────────────────────────────────────────────────

def test_detect_prefers_litellm_over_ollama(monkeypatch):
    monkeypatch.setenv("SIGIL_LLM_MODEL", "gemini/gemini-2.0-flash-lite")
    with patch("sigil_core.summarizer.ollama_available", return_value=True):
        assert detect_backend() == "litellm"


def test_detect_returns_ollama_when_available(monkeypatch):
    monkeypatch.delenv("SIGIL_LLM_MODEL", raising=False)
    with patch("sigil_core.summarizer.ollama_available", return_value=True):
        assert detect_backend() == "ollama"


def test_detect_returns_none_when_nothing_available(monkeypatch):
    monkeypatch.delenv("SIGIL_LLM_MODEL", raising=False)
    with patch("sigil_core.summarizer.ollama_available", return_value=False):
        assert detect_backend() is None


# ── ollama_available ─────────────────────────────────────────────────────────

def test_ollama_available_false_on_connection_error():
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert ollama_available() is False


# ── summarize_via_ollama ─────────────────────────────────────────────────────

def test_ollama_sends_correct_payload():
    response_body = json.dumps({"response": "Handles auth session creation."}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = response_body

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data)
        return mock_resp

    with patch("urllib.request.urlopen", fake_urlopen):
        result = summarize_via_ollama("create_session", "function", _SAMPLE_CODE)

    assert result == "Handles auth session creation."
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["data"]["stream"] is False
    assert "create_session" in captured["data"]["prompt"]


def test_ollama_strips_whitespace():
    response_body = json.dumps({"response": "  Auth helper.  \n"}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = response_body

    with patch("urllib.request.urlopen", lambda r, timeout=None: mock_resp):
        result = summarize_via_ollama("foo", "function", "pass")

    assert result == "Auth helper."


# ── summarize_via_litellm ────────────────────────────────────────────────────

def test_litellm_raises_if_not_installed(monkeypatch):
    import importlib, sys
    monkeypatch.setenv("SIGIL_LLM_MODEL", "gemini/gemini-2.0-flash-lite")
    with patch.dict(sys.modules, {"litellm": None}):
        with pytest.raises(RuntimeError, match="litellm not installed"):
            summarize_via_litellm("foo", "function", "pass")


def test_litellm_calls_completion_with_model(monkeypatch):
    monkeypatch.setenv("SIGIL_LLM_MODEL", "gemini/gemini-2.0-flash-lite")
    monkeypatch.delenv("SIGIL_LLM_API_KEY", raising=False)

    mock_choice = MagicMock()
    mock_choice.message.content = "Manages auth sessions."
    mock_result = MagicMock()
    mock_result.choices = [mock_choice]

    mock_litellm = MagicMock()
    mock_litellm.completion.return_value = mock_result

    import sys
    with patch.dict(sys.modules, {"litellm": mock_litellm}):
        result = summarize_via_litellm("create_session", "function", _SAMPLE_CODE)

    assert result == "Manages auth sessions."
    call_kwargs = mock_litellm.completion.call_args[1]
    assert call_kwargs["model"] == "gemini/gemini-2.0-flash-lite"
    assert "create_session" in call_kwargs["messages"][0]["content"]


# ── summarize (top-level dispatcher) ────────────────────────────────────────

def test_summarize_returns_empty_when_no_backend(monkeypatch):
    monkeypatch.delenv("SIGIL_LLM_MODEL", raising=False)
    with patch("sigil_core.summarizer.ollama_available", return_value=False):
        result = summarize("foo", "function", "pass")
    assert result == ""


def test_summarize_uses_ollama_when_available(monkeypatch):
    monkeypatch.delenv("SIGIL_LLM_MODEL", raising=False)
    with patch("sigil_core.summarizer.ollama_available", return_value=True):
        with patch("sigil_core.summarizer.summarize_via_ollama", return_value="Auth helper.") as mock_ollama:
            result = summarize("foo", "function", "pass")
    assert result == "Auth helper."
    mock_ollama.assert_called_once()


def test_summarize_returns_empty_on_backend_exception(monkeypatch):
    monkeypatch.delenv("SIGIL_LLM_MODEL", raising=False)
    with patch("sigil_core.summarizer.ollama_available", return_value=True):
        with patch("sigil_core.summarizer.summarize_via_ollama", side_effect=Exception("timeout")):
            result = summarize("foo", "function", "pass")
    assert result == ""


def test_summarize_explicit_backend_skips_autodetect():
    with patch("sigil_core.summarizer.summarize_via_ollama", return_value="OK.") as mock_ollama:
        result = summarize("foo", "function", "pass", backend="ollama")
    assert result == "OK."
    mock_ollama.assert_called_once()
