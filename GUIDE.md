# Symbex — Hướng dẫn sử dụng

> Symbol-graph retrieval cho AI agents — trả về đúng hàm cần đọc, không đọc cả file.

---

## Symbex là gì?

Khi AI agent cần sửa một hàm, nó thường đọc cả file chứa hàm đó — 400 dòng thay vì 25 dòng cần thiết. Nếu hàm đó gọi sang file khác, agent nhảy sang đọc file đó tiếp.

Symbex giải quyết vấn đề này bằng cách xây dựng **symbol graph** từ toàn bộ codebase. Thay vì đọc file, agent gọi `symbex_locate("fix login token")` và nhận về đúng những hàm cần thiết — kèm call graph ở dạng signature-only cho các hàm liên quan.

**Ngôn ngữ hỗ trợ:** Python (`.py`), TypeScript (`.ts`, `.tsx`), JavaScript (`.js`, `.jsx`).

---

## Cài đặt

### Yêu cầu

Python 3.10 trở lên. Không cần Node, không cần Docker.

### macOS / Linux

```bash
# Clone repo
git clone https://github.com/ThaiDuong2002/symbex-graph ~/Projects/symbex

# Chạy install script
cd ~/Projects/symbex
bash install.sh

# Thêm vào PATH (script in ra hướng dẫn cụ thể)
export PATH="$HOME/Projects/symbex/.venv/bin:$PATH"
```

### Windows (PowerShell)

```powershell
# Clone repo
git clone https://github.com/ThaiDuong2002/symbex-graph $env:USERPROFILE\Projects\symbex

# Chạy install script
cd $env:USERPROFILE\Projects\symbex
.\install.ps1

# Thêm vào PATH
$env:PATH = "$env:USERPROFILE\Projects\symbex\.venv\Scripts;$env:PATH"
```

### Kiểm tra cài đặt

```bash
symbex --help
```

---

## Lần đầu sử dụng

Chạy một lệnh duy nhất ở root của project bạn muốn index:

```bash
cd ~/Projects/my-app
symbex init
```

Lệnh này làm 4 việc:

1. **Index project** — Parse tất cả file Python/TS/JS, lưu vào SQLite (`.symbex/symbex.db`). Tự động bỏ qua `node_modules`, `venv`, `dist`, file > 500KB.
2. **Tạo overview** — Sinh ra `.symbex/overview.md` — tóm tắt project từ symbol graph: entry points, key classes, top modules.
3. **Ghi agent policy** — Thêm block hướng dẫn vào `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`. Agent tự đọc file này khi bắt đầu session và biết dùng Symbex trước khi đọc file.
4. **Đăng ký MCP server** — Ghi vào `.mcp.json` (Claude Code) và `~/.gemini/config/mcp_config.json` (Gemini/Antigravity). Restart agent IDE để load.

```
# Output mẫu
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

## Tham khảo lệnh

Tất cả lệnh nhận `--root PATH` để chỉ định project root (mặc định là thư mục hiện tại).

### `symbex index`

Re-index những file đã thay đổi. Dùng sau `git pull` hoặc khi codebase thay đổi. Chỉ re-index file có hash khác — file không đổi được skip.

```bash
symbex index

# Output
Indexed 3 symbols, 3 files, 2 edges
```

---

### `symbex locate <task>`

Lệnh cốt lõi. Dùng BM25 search + call graph expansion + token trimming để trả về tập symbol tối thiểu trong budget.

```bash
symbex locate "fix login token" --budget 2000

# Output
auth.py:12-45  login  (function, 180 tokens)
def login(user: str, password: str) -> str:
    token = generate_token(user)
    ...

tokens.py:8-8  refresh_token: ...  (method sig, 8 tokens)
def refresh_token(user_id: int, token: str) -> str: ...

Total: 2 symbols, 188 tokens
```

**Depth:**
- **depth 0** — Symbol match trực tiếp → full source code
- **depth 1** — Hàm mà symbol đó gọi → signature only (`def foo(...): ...`)

---

### `symbex symbol <name>`

Xem full source của một hàm/class. Thay thế việc mở file và tìm hàm thủ công.

```bash
symbex symbol "refresh_token"

# Output
tokens.py:8-32  refresh_token  (function)
def refresh_token(user_id: int, token: str) -> str:
    record = db.get_token(user_id)
    if record.expired:
        raise TokenExpiredError(...)
    ...
```

---

### `symbex callers <name>`

Ai đang gọi hàm này?

```bash
symbex callers "refresh_token"

# Output
Callers of 'refresh_token' (2):
  api.py:34  api_refresh  (function)
  def api_refresh(req): ...

  handler.py:89  handle_auth  (function)
  def handle_auth(ctx): ...
```

---

### `symbex callees <name>`

Hàm này đang gọi những gì?

```bash
symbex callees "login"

# Output
Callees of 'login' (2):
  auth.py:67  validate_user  (function)
  def validate_user(user: str) -> bool: ...

  tokens.py:8  refresh_token  (function)
  def refresh_token(user_id: int, token: str) -> str: ...
```

---

### `symbex impact <name>`

Đổi hàm này sẽ ảnh hưởng đến đâu? Dùng trước khi refactor hoặc thay đổi signature.

```bash
symbex impact "refresh_token"

# Output
'refresh_token' affects 3 callers:
  api.py:34     api_refresh
  handler.py:89 handle_auth
  test_auth.py:12 test_refresh_ok
```

---

### `symbex preview <task>`

Ước tính token trước khi load. Xem trước cost mà không thực sự load source.

```bash
symbex preview "fix login"

# Output
Symbol preview (token costs):
  login         function  auth.py:12    ~180 tokens
  validate_user function  auth.py:67    ~120 tokens
  refresh_token function  tokens.py:8   ~95 tokens

Total if loaded: ~395 tokens
```

---

### `symbex tests <name>`

Tìm test nào cover hàm này.

```bash
symbex tests "refresh_token"

# Output
Test symbols referencing 'refresh_token' (2):
  auth_test.py:12-25  test_refresh_ok      (function)
  auth_test.py:27-40  test_refresh_expired (function)
```

---

### `symbex status`

Xem thông tin index hiện tại.

```bash
symbex status

# Output
Index:    .symbex/symbex.db
Symbols:  142
Files:    23
Edges:    89
Version:  7
```

---

## So sánh token

Số token ước tính dựa trên quy tắc `len(text) / 4` — phù hợp với cách tính của các LLM phổ biến.

| Tình huống | Không có Symbex | Có Symbex | Tiết kiệm |
|---|---|---|---|
| Sửa bug trong `refresh_token()` (đọc auth.py ~400 lines) | ~1,600 tokens | ~100 tokens | **−94%** |
| Trace tại sao `TokenExpiredError` xuất hiện (3 file liên quan) | ~4,000 tokens | ~400 tokens | **−90%** |
| Hiểu cấu trúc project lần đầu (README + config + entry points) | ~15,000 tokens | ~300 tokens | **−98%** |
| Refactor một class có 5 callers (grep + đọc từng file) | ~8,000 tokens | ~50 tokens | **−99%** |
| Thêm test cho `login()` (xem test hiện tại + source) | ~2,400 tokens | ~280 tokens | **−88%** |

**Tại sao tiết kiệm nhiều vậy?** Khi không có Symbex, agent đọc cả file dù chỉ cần 1 hàm. Khi hàm đó gọi sang file khác, agent đọc tiếp file đó. Symbex cắt đứt vòng lặp này — chỉ trả về span của hàm cần thiết, và chỉ trả signature của hàm phụ thuộc.

---

## Pipeline bên trong

Mỗi lần gọi `symbex locate` hoặc `symbex_locate` qua MCP:

```
[BM25 Search] → [Call Graph expansion] → [Token Trim] → [Cache]
   Top 5 symbols    Thêm callee depth=1     Vừa budget       Hit nếu hỏi lại
                    (signature only)        (mặc định 2000)
```

Index được cập nhật incremental: Symbex so sánh SHA-256 của từng file, chỉ re-parse file thay đổi. Sau `git pull`, chạy `symbex index` để sync.

---

## Cập nhật index

```bash
# Sau git pull
git pull
symbex index

# Chỉ 3 file thay đổi → chỉ re-index 3 file đó
Indexed 8 symbols, 3 files, 5 edges
```

File không thay đổi sẽ được skip hoàn toàn, bất kể project có bao nhiêu file.
