# Symbex

Symbol-graph retrieval for AI agents — returns exactly the functions needed, not entire files.

---

## What is Symbex?

When an AI agent needs to fix a function, it typically reads the entire containing file — 400 lines instead of the 25 that matter. If that function calls into another file, the agent jumps there and reads that one too.

Symbex solves this by building a **symbol graph** from your codebase. Instead of reading files, the agent calls `symbex_locate("fix login token")` and receives precisely the relevant functions — plus call-graph neighbors as signature-only stubs.

**Supported languages:** Python (`.py`), TypeScript (`.ts`, `.tsx`), JavaScript (`.js`, `.jsx`).

---

## Installation

### Requirements

Python 3.10+. No Node, no Docker.

### macOS / Linux

```bash
git clone https://github.com/ThaiDuong2002/symbex-graph ~/Projects/symbex
cd ~/Projects/symbex
bash install.sh

# Add to PATH (the script prints exact instructions)
export PATH="$HOME/Projects/symbex/.venv/bin:$PATH"
```

### Windows (PowerShell)

```powershell
git clone https://github.com/ThaiDuong2002/symbex-graph $env:USERPROFILE\Projects\symbex
cd $env:USERPROFILE\Projects\symbex
.\install.ps1

$env:PATH = "$env:USERPROFILE\Projects\symbex\.venv\Scripts;$env:PATH"
```

### Verify

```bash
symbex --help
```

---

## Getting Started

Run one command at the root of the project you want to index:

```bash
cd ~/Projects/my-app
symbex init
```

This does four things:

1. **Index** — Parses all Python/TS/JS files into SQLite (`.symbex/symbex.db`). Automatically skips `node_modules`, `venv`, `dist`, and files over 500 KB.
2. **Overview** — Writes `.symbex/overview.md` — a project summary derived from the symbol graph: entry points, key classes, top modules.
3. **Agent policy** — Appends a guidance block to `CLAUDE.md`, `AGENTS.md`, and `GEMINI.md` so agents know to reach for Symbex before reading files.
4. **MCP registration** — Writes to `.mcp.json` (Claude Code) and `~/.gemini/config/mcp_config.json` (Gemini/Antigravity). Restart your agent IDE to load.

```
Indexing project...
Indexed 142 symbols, 23 files, 89 edges
Overview written to .symbex/overview.md
Agent policy written to CLAUDE.md
Agent policy written to AGENTS.md
Agent policy written to GEMINI.md
MCP server registered in .mcp.json
MCP server registered in ~/.gemini/config/mcp_config.json
Done. Restart your agent IDE to load the MCP server.
```

---

## Command Reference

All commands accept `--root PATH` to specify a project root (defaults to the current directory).

### `symbex index`

Re-index changed files. Run after `git pull` or whenever the codebase changes. Only files whose SHA-256 hash has changed are re-parsed.

```bash
symbex index
# Indexed 3 symbols, 3 files, 2 edges
```

---

### `symbex locate <task>`

The core command. Uses BM25 search + call-graph expansion + token-aware trimming to return the minimal set of symbols within a token budget.

```bash
symbex locate "fix login token" --budget 2000

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

### `symbex symbol <name>`

View the full source of a function or class. Replaces manually opening a file and searching.

```bash
symbex symbol "refresh_token"

# tokens.py:8-32  refresh_token  (function)
# def refresh_token(user_id: int, token: str) -> str:
#     record = db.get_token(user_id)
#     if record.expired:
#         raise TokenExpiredError(...)
#     ...
```

---

### `symbex callers <name>`

Who calls this function?

```bash
symbex callers "refresh_token"

# Callers of 'refresh_token' (2):
#   api.py:34  api_refresh  (function)
#   def api_refresh(req): ...
#
#   handler.py:89  handle_auth  (function)
#   def handle_auth(ctx): ...
```

---

### `symbex callees <name>`

What does this function call?

```bash
symbex callees "login"

# Callees of 'login' (2):
#   auth.py:67  validate_user  (function)
#   def validate_user(user: str) -> bool: ...
#
#   tokens.py:8  refresh_token  (function)
#   def refresh_token(user_id: int, token: str) -> str: ...
```

---

### `symbex impact <name>`

What breaks if this function changes? Use before refactoring or changing a signature.

```bash
symbex impact "refresh_token"

# 'refresh_token' affects 3 callers:
#   api.py:34     api_refresh
#   handler.py:89 handle_auth
#   test_auth.py:12 test_refresh_ok
```

---

### `symbex preview <task>`

Estimate token cost before loading anything. Useful for staying within budget.

```bash
symbex preview "fix login"

# Symbol preview (token costs):
#   login         function  auth.py:12    ~180 tokens
#   validate_user function  auth.py:67    ~120 tokens
#   refresh_token function  tokens.py:8   ~95 tokens
#
# Total if loaded: ~395 tokens
```

---

### `symbex tests <name>`

Find which tests cover a function.

```bash
symbex tests "refresh_token"

# Test symbols referencing 'refresh_token' (2):
#   auth_test.py:12-25  test_refresh_ok      (function)
#   auth_test.py:27-40  test_refresh_expired (function)
```

---

### `symbex status`

Show current index stats.

```bash
symbex status

# Index:    .symbex/symbex.db
# Symbols:  142
# Files:    23
# Edges:    89
# Version:  7
```

---

## Token Comparison

Token counts estimated using `len(text) / 4` — consistent with major LLM tokenizers.

| Scenario | Without Symbex | With Symbex | Savings |
|---|---|---|---|
| Fix bug in `refresh_token()` — reads auth.py (~400 lines) | ~1,600 tokens | ~100 tokens | **−94%** |
| Trace why `TokenExpiredError` appears — 3 related files | ~4,000 tokens | ~400 tokens | **−90%** |
| Understand project structure on first look | ~15,000 tokens | ~300 tokens | **−98%** |
| Refactor a class with 5 callers — grep + read each file | ~8,000 tokens | ~50 tokens | **−99%** |
| Add tests for `login()` — need current tests + source | ~2,400 tokens | ~280 tokens | **−88%** |

**Why such large savings?** Without Symbex, an agent reads the full file even when it only needs one function. If that function calls into another file, the agent reads that file too. Symbex breaks the chain — returning only the function's source span, with dependency functions as signatures.

---

## How It Works

Each call to `symbex locate` (CLI) or `symbex_locate` (MCP tool) runs the same pipeline:

```
BM25 Search  →  Call Graph  →  Token Trim  →  Cache
Top 5 matches   Add callees     Fit budget      Return on repeat
                as signatures   (default 2000)
```

Indexing is incremental: each file's SHA-256 is stored, and only files with a changed hash are re-parsed. After `git pull`, run `symbex index` to sync.

---

## Keeping the Index Fresh

```bash
git pull
symbex index
# Indexed 8 symbols, 3 files, 5 edges
```

Unchanged files are skipped entirely regardless of project size.
