# Sigil

Symbol-graph retrieval for AI agents — returns exactly the functions needed, not entire files.

---

## What is Sigil?

When an AI agent needs to fix a function, it typically reads the entire containing file — 400 lines instead of the 25 that matter. If that function calls into another file, the agent jumps there and reads that one too.

Sigil solves this by building a **symbol graph** from your codebase. Instead of reading files, the agent calls `sigil_locate("fix login token")` and receives precisely the relevant functions — plus call-graph neighbors as signature-only stubs.

**Supported languages:** Python (`.py`), TypeScript (`.ts`, `.tsx`), JavaScript (`.js`, `.jsx`), C# (`.cs`), Razor (`.cshtml`).

---

## Installation

### Requirements

Python 3.10+, Git. No Node, no Docker.

### macOS / Linux — one command

```bash
curl -sSL https://raw.githubusercontent.com/ThaiDuong2002/sigil-graph/master/install.sh | bash
```

The script clones the repo to `~/.sigil`, creates a virtualenv, and prints the exact `export PATH=...` line to add to your shell profile.

### Windows — one command (PowerShell)

```powershell
irm https://raw.githubusercontent.com/ThaiDuong2002/sigil-graph/master/install.ps1 | iex
```

Clones to `~\.sigil` and prints the `$env:PATH = ...` line to add to your PowerShell profile.

### Custom install location

```bash
# macOS / Linux
SIGIL_DIR=~/tools/sigil curl -sSL .../install.sh | bash

# Windows
$env:SIGIL_DIR = "C:\tools\sigil"
irm .../install.ps1 | iex
```

### Alternative: pipx

```bash
pipx install git+https://github.com/ThaiDuong2002/sigil-graph.git
```

[pipx](https://pipx.pypa.io) installs into an isolated environment and adds `sigil` to your PATH automatically — no manual PATH editing needed.

### Verify

```bash
sigil --version
# sigil, version 0.4.6

sigil --help
```

### Updating

```bash
# Git-based installs (install.sh / install.ps1)
sigil update
# Updating sigil at ~/.sigil ...
# Updated: af1fedd → cdb6882 (sigil 0.4.6)

# pipx installs
pipx upgrade sigil-graph
```

---

## Getting Started

Run one command at the root of the project you want to index:

```bash
cd ~/Projects/my-app
sigil init
```

This does six things:

1. **Index** — Parses all Python/TS/JS/C#/Razor files into SQLite (`.sigil/sigil.db`). Automatically skips `node_modules`, `venv`, `dist`, `bin`, `obj`, and files over 500 KB.
2. **Overview** — Writes `.sigil/overview.md` — a compact project summary.
3. **Knowledge** — Writes `.sigil/knowledge.md` — architecture, business logic, conventions, and hotspots derived from the full symbol graph.
4. **Agent policy** — Appends a guidance block to `CLAUDE.md`, `AGENTS.md`, and `GEMINI.md` so agents know to reach for Sigil before reading files.
5. **Global policy** — Writes a trigger-based rule to `~/.claude/CLAUDE.md` and `~/.agents/AGENTS.md` so agents use Sigil automatically in any indexed repo, without being told per session.
6. **MCP registration** — Writes to `.mcp.json` (Claude Code) and `~/.gemini/config/mcp_config.json` (Gemini/Antigravity). Restart your agent IDE to load.

```
Indexing project...
Parsing 23 changed file(s)...
Resolving call graph for 23 file(s)...
Found 89 edges.
Indexed 142 new symbols across 23 file(s), 23 files total, 89 edges
Overview written to .sigil/overview.md
Project knowledge written to .sigil/knowledge.md
Agent policy written to CLAUDE.md
Agent policy written to AGENTS.md
Agent policy written to GEMINI.md
MCP server registered in .mcp.json
MCP server registered in ~/.gemini/config/mcp_config.json
Global policy written to ~/.claude/CLAUDE.md
Global policy written to ~/.agents/AGENTS.md
Done. Restart your agent IDE to load the MCP server.
```

---

## Command Reference

All commands accept `--root PATH` to specify a project root (defaults to the current directory). Run `sigil --version` to check the installed version.

### `sigil index`

Re-index changed files. Run after `git pull` or whenever the codebase changes. Only files whose content has changed are re-parsed (mtime fast-path, then SHA-256 for confirmation).

```bash
sigil index

# When files changed:
# Parsing 3 changed file(s)...
# Resolving call graph for 12 file(s)...
# Found 8 edges.
# Indexed 3 new symbols across 3 file(s), 12 files total, 8 edges
#   + new      3  add_user, get_session, validate_token
#   ~ changed  1  login
#   - removed  1  legacy_auth

# When nothing changed:
# Up to date — 142 symbols, 12 files, 8 edges
```

---

### `sigil summarize`

Generate AI-powered summaries for indexed symbols. Summaries are stored in the database and included in the BM25 search index, bridging the semantic gap between query terms and function names.

**Why this matters:** A function called `create_session` won't appear when searching "auth" — unless its summary says "Handles user authentication and creates a JWT session token." After `sigil summarize`, semantic queries like "auth", "login flow", "token expiry" find functions that BM25 alone would miss.

```bash
sigil summarize           # auto-detect backend
sigil summarize --backend ollama    # force Ollama
sigil summarize --force             # re-summarize all symbols
```

**Backends (auto-detected in order):**

| Backend | Setup | Cost |
|---|---|---|
| **LiteLLM** | `SIGIL_LLM_MODEL=gemini/gemini-2.0-flash-lite SIGIL_LLM_API_KEY=<key>` | API cost (~$0.001 per 100 symbols) |
| **Ollama** | Install Ollama + `ollama pull qwen2.5:0.5b` | Free, local |

LiteLLM supports any provider: `gemini/gemini-2.0-flash-lite`, `deepseek/deepseek-chat`, `anthropic/claude-haiku-4-5`, `openai/gpt-4o-mini`, `ollama/llama3.2`, etc.

Via MCP (no CLI): `sigil_summarize()` uses the **host agent's model** (MCP Sampling) — zero config for Claude Code users.

```bash
# Install LiteLLM support
pip install sigil[llm]

# Gemini (cheapest)
export SIGIL_LLM_MODEL=gemini/gemini-2.0-flash-lite
export SIGIL_LLM_API_KEY=AIza...
sigil summarize

# DeepSeek
export SIGIL_LLM_MODEL=deepseek/deepseek-chat
export SIGIL_LLM_API_KEY=sk-...
sigil summarize

# Ollama (local, free)
ollama pull qwen2.5:0.5b
sigil summarize --backend ollama
```

---

### `sigil locate <task>`

The core command. Uses BM25 search + call-graph expansion + token-aware trimming to return the minimal set of symbols within a token budget. Frequently-called symbols are boosted in ranking so central functions surface even with imprecise queries.

```bash
sigil locate "fix login token" --budget 2000

# auth.py:12-45  login  (function, 180 tokens)
# def login(user: str, password: str) -> str:
#     token = generate_token(user)
#     ...
#
# tokens.py:8-8  refresh_token: ...  (method sig, 8 tokens)
# def refresh_token(user_id: int, token: str) -> str: ...
#
# Total: 2 symbols, 188 tokens
```

**Depth semantics:**
- **depth 0** — Direct BM25 matches → full source
- **depth 1** — Functions those symbols call → signature only (`def foo(...): ...`)

---

### `sigil symbol <name>`

View the full source of a function or class. Replaces manually opening a file and searching.

```bash
sigil symbol "refresh_token"

# tokens.py:8-32  refresh_token  (function)
# def refresh_token(user_id: int, token: str) -> str:
#     record = db.get_token(user_id)
#     if record.expired:
#         raise TokenExpiredError(...)
#     ...
```

---

### `sigil callers <name>`

Who calls this function, how many times, and from which lines?

```bash
sigil callers "refresh_token"

# Callers of 'refresh_token' (2):
#   api.py:34  api_refresh  (function, 2x)
#   called at lines: 41, 67
#   def api_refresh(req): ...
#
#   handler.py:89  handle_auth  (function, 1x)
#   called at lines: 94
#   def handle_auth(ctx): ...
```

Results are sorted by call count descending — the heaviest caller appears first.

---

### `sigil callees <name>`

What does this function call, how many times, and from which lines?

```bash
sigil callees "login"

# Callees of 'login' (2):
#   auth.py:12  validate_user  (function, 1x)
#   called at lines: 18
#   def validate_user(user: str) -> bool: ...
#
#   tokens.py:8  refresh_token  (function, 2x)
#   called at lines: 22, 31
#   def refresh_token(user_id: int, token: str) -> str: ...
```

Tracks both cross-file calls (via imports) and same-file calls.

---

### `sigil impact <name>`

What breaks if this function changes? Use before refactoring or changing a signature.

```bash
sigil impact "refresh_token"

# 'refresh_token' affects 3 callers:
#   api.py:34     api_refresh  (2x)  lines: 41, 67
#   handler.py:89 handle_auth  (1x)  lines: 94
#   test_auth.py:12 test_refresh_ok  (1x)  lines: 15
```

---

### `sigil knowledge`

Generate `.sigil/knowledge.md` — a static-analysis document that gives an AI agent a complete picture of the project before it reads a single source file.

```bash
sigil knowledge
# Project knowledge written to .sigil/knowledge.md
```

The generated file has four sections:

| Section | Contents |
|---|---|
| **Architecture** | Module layers (API/Service/Model/Data auto-detected), entry points, top cross-module call paths |
| **Business Logic** | Core functions by incoming call volume, orchestrators by out-degree, domain classes by method count — all with inline docstrings |
| **Conventions** | Naming style, type-hint coverage %, docstring coverage %, common prefixes (`get_*`, `validate_*`...), architectural class suffixes (`*Service`, `*Repository`...) |
| **Hotspots** | Largest functions by line count, test coverage map |

Also generated automatically by `sigil init`.

---

### `sigil update`

Pull the latest version from GitHub and reinstall. Only works for git-based installs (`install.sh` / `install.ps1`).

```bash
sigil update
# Updating sigil at ~/.sigil ...
# Updated: a1b2c3d → e4f5a6b
# Restart your shell to use the new version.
```

For pipx installs: `pipx upgrade sigil-graph`

---

### `sigil preview <task>`

Estimate token cost before loading anything. Useful for staying within budget.

```bash
sigil preview "fix login"

# Symbol preview (token costs):
#   login         function  auth.py:12    ~180 tokens
#   validate_user function  auth.py:67    ~120 tokens
#   refresh_token function  tokens.py:8   ~95 tokens
#
# Total if loaded: ~395 tokens
```

---

### `sigil tests <name>`

Find which tests cover a function.

```bash
sigil tests "refresh_token"

# Test symbols referencing 'refresh_token' (2):
#   auth_test.py:12-25  test_refresh_ok      (function)
#   auth_test.py:27-40  test_refresh_expired (function)
```

---

### `sigil status`

Show current index stats.

```bash
sigil status

# Index:    .sigil/sigil.db
# Symbols:  142
# Files:    23
# Edges:    89
# Version:  7
```

---

## Token Comparison

Token counts estimated using `len(text) / 4` — consistent with major LLM tokenizers.

| Scenario | Without Sigil | With Sigil | Savings |
|---|---|---|---|
| Fix bug in `refresh_token()` — reads auth.py (~400 lines) | ~1,600 tokens | ~100 tokens | **−94%** |
| Trace why `TokenExpiredError` appears — 3 related files | ~4,000 tokens | ~400 tokens | **−90%** |
| Understand project structure on first look | ~15,000 tokens | ~300 tokens | **−98%** |
| Refactor a class with 5 callers — grep + read each file | ~8,000 tokens | ~50 tokens | **−99%** |
| Add tests for `login()` — need current tests + source | ~2,400 tokens | ~280 tokens | **−88%** |

**Why such large savings?** Without Sigil, an agent reads the full file even when it only needs one function. If that function calls into another file, the agent reads that file too. Sigil breaks the chain — returning only the function's source span, with dependency functions as signatures.

---

## How It Works

### Locate pipeline

Each call to `sigil locate` (CLI) or `sigil_locate` (MCP tool) runs the same pipeline:

```
BM25 Search  →  Call-count boost  →  Call Graph  →  Token Trim  →  Cache
Top 20 matches  Rank by frequency    Add callees     Fit budget      Hit on repeat
                (central functions   as signatures   (default 2000)
                surface first)
```

### Edge data

Every edge in the call graph stores:

- **`call_count`** — how many times the caller calls the callee
- **`call_sites`** — the exact line numbers of each call site

This covers both cross-file calls (via import resolution) and same-file calls. Results from `callers`, `callees`, and `impact` are sorted by call count so the most load-bearing relationships appear first.

### Incremental indexing

Each file's modification time (mtime) is checked first — if it hasn't changed, the file is skipped without any I/O. If mtime changed, the SHA-256 hash is compared to confirm real content changes before re-parsing. Only content-changed files are re-parsed.

After `git pull`, `sigil index` syncs in seconds regardless of project size. Tested on codebases with 500k–1M LOC and 20k+ symbols.

### Language support

| Language | Extensions | Symbols extracted | Call graph |
|---|---|---|---|
| Python | `.py` | functions, classes, methods | Cross-file + same-file |
| TypeScript | `.ts`, `.tsx` | functions, classes, methods | Cross-file + same-file |
| JavaScript | `.js`, `.jsx` | functions, classes, methods | Cross-file + same-file |
| C# | `.cs` | classes, interfaces, enums, structs, records, methods, constructors, properties | Same-file |
| Razor | `.cshtml` | methods inside `@functions { }` blocks | Same-file |

**C# notes:**
- Methods are indexed as `ClassName.MethodName` — qualified by their containing class
- ASP.NET attributes (`[HttpGet]`, `[Route]`, `[Authorize]`) are stripped from signatures; the declaration line is clean
- `bin/`, `obj/`, `packages/` are excluded from indexing automatically
- `*Tests.cs`, `*Test.cs` files are flagged as test files
- Cross-namespace call edges are not tracked (would require Roslyn-level analysis)

**Razor notes:**
- Only `@functions { ... }` blocks are indexed — these contain indexable C# methods
- Line numbers in results point back to the original `.cshtml` file
- HTML template parts are ignored

---

## Keeping the Index Fresh

```bash
git pull
sigil index
# Parsing 3 changed file(s)...
# Resolving call graph for 47 file(s)...
# Found 312 edges.
# Indexed 8 new symbols across 3 file(s), 47 files total, 312 edges
#   + new     5  handle_payment, refund, validate_card, ...
#   ~ changed 3  checkout, cart_total, apply_discount
```

Unchanged files are skipped entirely — mtime check first, SHA-256 only when mtime changed.

---

## Agent Integration

After `sigil init`, agents receive two layers of guidance:

**Per-project** (`CLAUDE.md` / `AGENTS.md` / `GEMINI.md`):

| Instead of | Use |
|---|---|
| Grep + Read to find code | `sigil_locate("<task>")` |
| Read to view a function | `sigil_symbol("<name>")` |
| Grep to find callers | `sigil_callers("<name>")` |
| Grep to find callees | `sigil_callees("<name>")` |
| Guessing what breaks | `sigil_impact("<name>")` before any edit |
| Reading files for project context | `sigil_knowledge()` at start of task |

**Global** (`~/.claude/CLAUDE.md` / `~/.agents/AGENTS.md`):

A trigger-based rule that fires automatically in any repo with a `.sigil/` directory — no per-session instructions needed.
