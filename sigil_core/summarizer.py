"""Tiered AI summarization backends for semantic search enrichment.

Auto-detection order: MCP Sampling → Ollama → LiteLLM → skip (return '').
"""

import json
import os
import urllib.request
from typing import Any


_PROMPT = (
    "Write a 1-2 sentence summary for a code search index. "
    "State what this {kind} does, its domain (auth, payments, sessions, "
    "user management, etc.), and key inputs/outputs if relevant. "
    "Terse, search-friendly keywords only.\n\n"
    "{kind} {name}:\n{code}"
)


def _make_prompt(name: str, kind: str, source_text: str) -> str:
    return _PROMPT.format(name=name, kind=kind, code=source_text[:700])


# ── Ollama ──────────────────────────────────────────────────────────────────

def ollama_model() -> str:
    return os.environ.get("SIGIL_OLLAMA_MODEL", "qwen2.5:0.5b")


def ollama_available() -> bool:
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2):
            return True
    except Exception:
        return False


def summarize_via_ollama(name: str, kind: str, source_text: str) -> str:
    payload = json.dumps({
        "model": ollama_model(),
        "prompt": _make_prompt(name, kind, source_text),
        "stream": False,
        "options": {"num_predict": 120},
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["response"].strip()


# ── LiteLLM ─────────────────────────────────────────────────────────────────

def litellm_model() -> str | None:
    return os.environ.get("SIGIL_LLM_MODEL")


def summarize_via_litellm(name: str, kind: str, source_text: str) -> str:
    try:
        import litellm  # type: ignore
    except ImportError as exc:
        raise RuntimeError("litellm not installed — run: pip install litellm") from exc

    model = litellm_model()
    api_key = os.environ.get("SIGIL_LLM_API_KEY") or None
    result = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": _make_prompt(name, kind, source_text)}],
        max_tokens=120,
        api_key=api_key,
    )
    return result.choices[0].message.content.strip()


# ── MCP Sampling ─────────────────────────────────────────────────────────────

async def summarize_via_mcp(name: str, kind: str, source_text: str, ctx: Any) -> str:
    """Generate a summary using the host agent via MCP sampling."""
    prompt = _make_prompt(name, kind, source_text)
    try:
        # FastMCP 2.x exposes ctx.sample()
        if hasattr(ctx, "sample"):
            result = await ctx.sample(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=120,
            )
            return (getattr(result, "text", None) or str(result)).strip()

        # MCP 1.x: use the underlying session
        from mcp.types import SamplingMessage, TextContent  # type: ignore
        result = await ctx.session.create_message(
            messages=[SamplingMessage(
                role="user",
                content=TextContent(type="text", text=prompt),
            )],
            max_tokens=120,
        )
        content = result.content
        return (getattr(content, "text", None) or str(content)).strip()
    except Exception:
        return ""


# ── Auto-detection ──────────────────────────────────────────────────────────

def detect_backend() -> str | None:
    """Return 'litellm', 'ollama', or None — checked in priority order."""
    if litellm_model():
        return "litellm"
    if ollama_available():
        return "ollama"
    return None


def summarize(name: str, kind: str, source_text: str, backend: str | None = "auto") -> str:
    """Generate a summary using the available backend. Returns '' on any failure."""
    if backend == "auto":
        backend = detect_backend()
    if not backend:
        return ""
    try:
        if backend == "ollama":
            return summarize_via_ollama(name, kind, source_text)
        if backend == "litellm":
            return summarize_via_litellm(name, kind, source_text)
    except Exception:
        pass
    return ""
