"""
Generate project knowledge: architecture, business logic, conventions, hotspots.
All analysis is static — no external LLM required.
"""
import re
import sqlite3
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_docstring(source_text: str) -> str:
    """Return the first docstring found in source_text, or empty string."""
    m = re.search(r'"""(.*?)"""', source_text, re.DOTALL)
    if m:
        return ' '.join(m.group(1).strip().splitlines()).strip()
    m = re.search(r"'''(.*?)'''", source_text, re.DOTALL)
    if m:
        return ' '.join(m.group(1).strip().splitlines()).strip()
    return ""


def _classify_name(name: str) -> str:
    local = name.split('.')[-1].lstrip('_')
    if not local:
        return 'other'
    if local[0].isupper():
        return 'PascalCase'
    if any(c.isupper() for c in local[1:]):
        return 'camelCase'
    return 'snake_case'  # single-word lowercase is valid snake_case


def _has_type_hints(sig: str) -> bool:
    return '->' in sig or bool(re.search(r'\w+\s*:\s*\w', sig))


def _has_docstring(source_text: str) -> bool:
    return bool(_extract_docstring(source_text))


def _detect_layer(file_path: str) -> str:
    p = file_path.replace('\\', '/').lower()
    parts = set(p.split('/'))
    name = Path(p).stem
    if any(k in parts for k in ('api', 'routes', 'controllers', 'views', 'endpoints')):
        return 'API'
    if any(k in parts for k in ('services', 'service', 'managers')):
        return 'Service'
    if any(k in parts for k in ('models', 'model', 'schemas', 'entities', 'domain')):
        return 'Model'
    if any(k in parts for k in ('repositories', 'repo', 'dao', 'db', 'database')):
        return 'Data'
    if any(k in parts for k in ('utils', 'helpers', 'util', 'helper', 'common', 'shared')):
        return 'Utility'
    if any(k in parts for k in ('tests', '__tests__', 'test', 'spec')):
        return 'Test'
    if any(k in name for k in ('service', 'manager', 'handler')):
        return 'Service'
    if any(name.endswith(k) for k in ('model', 'schema', 'entity')):
        return 'Model'
    if any(name.startswith(k) for k in ('db', 'database', 'repo')):
        return 'Data'
    if name in ('main', 'app', 'server', 'cli', 'index'):
        return 'Entry'
    return 'Core'


def _count_prefix(names: list[str], prefix: str) -> int:
    return sum(1 for n in names if n.split('.')[-1].startswith(prefix))


# ---------------------------------------------------------------------------
# Section generators
# ---------------------------------------------------------------------------

def _section_architecture(conn: sqlite3.Connection) -> list[str]:
    lines = ["## Architecture", ""]

    # Layer breakdown
    file_rows = conn.execute(
        "SELECT file_path, COUNT(*) FROM symbols WHERE is_test=0 "
        "GROUP BY file_path ORDER BY file_path"
    ).fetchall()

    layers: dict[str, list[str]] = {}
    for file_path, cnt in file_rows:
        layer = _detect_layer(file_path)
        layers.setdefault(layer, []).append(f"`{file_path}` ({cnt} symbols)")

    if layers:
        lines.append("### Module layers")
        for layer in ('Entry', 'API', 'Service', 'Core', 'Model', 'Data', 'Utility', 'Test'):
            if layer in layers:
                lines.append(f"\n**{layer}**")
                for item in layers[layer]:
                    lines.append(f"- {item}")
        lines.append("")

    # Entry points — functions/methods with no callers
    entry_rows = conn.execute(
        """
        SELECT s.name, s.kind, s.file_path, s.start_line, s.signature_text
        FROM symbols s
        LEFT JOIN edges e ON e.callee_id = s.id
        WHERE s.is_test = 0
          AND e.callee_id IS NULL
          AND s.kind IN ('function', 'method')
        ORDER BY s.file_path, s.name
        LIMIT 20
        """
    ).fetchall()

    lines.append("### Entry points (no callers)")
    if entry_rows:
        for row in entry_rows:
            name, kind, fp, sl, sig = row
            lines.append(f"- `{name}` — {fp}:{sl}")
            sig_clean = sig.rstrip(': ...').strip()
            lines.append(f"  `{sig_clean}`")
    else:
        lines.append("- *(none detected)*")
    lines.append("")

    # Cross-module dependencies
    dep_rows = conn.execute(
        """
        SELECT cs.file_path, ce.file_path, SUM(e.call_count) as total
        FROM edges e
        JOIN symbols cs ON cs.id = e.caller_id
        JOIN symbols ce ON ce.id = e.callee_id
        WHERE cs.file_path != ce.file_path
        GROUP BY cs.file_path, ce.file_path
        ORDER BY total DESC
        LIMIT 15
        """
    ).fetchall()

    if dep_rows:
        lines.append("### Top cross-module call paths")
        for caller_file, callee_file, total in dep_rows:
            lines.append(f"- `{caller_file}` → `{callee_file}` ({total} calls)")
        lines.append("")

    return lines


def _section_business_logic(conn: sqlite3.Connection) -> list[str]:
    lines = ["## Business Logic", ""]

    # Core functions — highest total incoming call_count
    core_rows = conn.execute(
        """
        SELECT s.name, s.file_path, s.start_line, s.signature_text,
               s.source_text, SUM(e.call_count) as total_calls
        FROM symbols s
        JOIN edges e ON e.callee_id = s.id
        WHERE s.is_test = 0
        GROUP BY s.id
        ORDER BY total_calls DESC
        LIMIT 15
        """
    ).fetchall()

    lines.append("### Core functions (most called)")
    if core_rows:
        for row in core_rows:
            name, fp, sl, sig, src, total = row
            doc = _extract_docstring(src)
            sig_clean = sig.rstrip(': ...').strip()
            desc = f" — {doc}" if doc else ""
            lines.append(f"- `{name}` ({total}×) — {fp}:{sl}{desc}")
            lines.append(f"  `{sig_clean}`")
    else:
        lines.append("- *(call graph empty — run `sigil index` first)*")
    lines.append("")

    # Orchestrators — functions that call the most others
    orch_rows = conn.execute(
        """
        SELECT s.name, s.file_path, s.start_line, COUNT(e.callee_id) as out_degree
        FROM symbols s
        JOIN edges e ON e.caller_id = s.id
        WHERE s.is_test = 0
        GROUP BY s.id
        ORDER BY out_degree DESC
        LIMIT 10
        """
    ).fetchall()

    lines.append("### Orchestrators (call the most other functions)")
    if orch_rows:
        for name, fp, sl, out_degree in orch_rows:
            lines.append(f"- `{name}` ({out_degree} callees) — {fp}:{sl}")
    else:
        lines.append("- *(none detected)*")
    lines.append("")

    # Domain objects — classes with most methods
    class_rows = conn.execute(
        """
        SELECT s.name, s.file_path, s.start_line, s.source_text,
               COUNT(m.id) as method_count
        FROM symbols s
        LEFT JOIN symbols m ON m.name LIKE s.name || '.%' AND m.kind = 'method'
        WHERE s.kind = 'class' AND s.is_test = 0
        GROUP BY s.id
        ORDER BY method_count DESC
        LIMIT 10
        """
    ).fetchall()

    lines.append("### Domain objects (classes)")
    if class_rows:
        for name, fp, sl, src, method_count in class_rows:
            doc = _extract_docstring(src)
            desc = f" — {doc}" if doc else ""
            methods_str = f"{method_count} method{'s' if method_count != 1 else ''}"
            lines.append(f"- `{name}` ({methods_str}) — {fp}:{sl}{desc}")
    else:
        lines.append("- *(no classes found)*")
    lines.append("")

    return lines


def _section_conventions(conn: sqlite3.Connection) -> list[str]:
    lines = ["## Code Conventions", ""]

    sym_rows = conn.execute(
        "SELECT name, kind, signature_text, source_text FROM symbols WHERE is_test=0"
    ).fetchall()

    if not sym_rows:
        lines.append("*(no symbols indexed)*")
        return lines

    all_names = [row[0] for row in sym_rows]
    func_rows = [row for row in sym_rows if row[1] in ('function', 'method')]
    class_rows = [row for row in sym_rows if row[1] == 'class']

    # Naming convention for functions
    func_names = [row[0] for row in func_rows]
    func_styles: dict[str, int] = {}
    for n in func_names:
        s = _classify_name(n)
        func_styles[s] = func_styles.get(s, 0) + 1
    dominant_func_style = max(func_styles, key=func_styles.get) if func_styles else 'unknown'

    # Naming convention for classes
    class_names = [row[0] for row in class_rows]
    class_styles: dict[str, int] = {}
    for n in class_names:
        s = _classify_name(n)
        class_styles[s] = class_styles.get(s, 0) + 1
    dominant_class_style = max(class_styles, key=class_styles.get) if class_styles else 'unknown'

    lines.append("### Naming style")
    lines.append(f"- Functions/methods: **{dominant_func_style}**")
    lines.append(f"- Classes: **{dominant_class_style}**")
    lines.append("")

    # Type hint coverage
    if func_rows:
        typed = sum(1 for row in func_rows if _has_type_hints(row[2]))
        pct = int(typed / len(func_rows) * 100)
        lines.append("### Type hints")
        lines.append(f"- {typed}/{len(func_rows)} functions typed ({pct}%)")
        lines.append("")

    # Docstring coverage
    if func_rows:
        doc_count = sum(1 for row in func_rows if _has_docstring(row[3]))
        pct = int(doc_count / len(func_rows) * 100)
        lines.append("### Docstring coverage")
        lines.append(f"- {doc_count}/{len(func_rows)} functions documented ({pct}%)")
        lines.append("")

    # Common prefixes — indicates domain vocabulary
    all_local_names = [n.split('.')[-1] for n in all_names]
    prefixes = ['get_', 'set_', 'create_', 'update_', 'delete_', 'fetch_',
                'validate_', 'handle_', 'process_', 'build_', 'parse_', 'is_', 'has_']
    found_prefixes = [(p, _count_prefix(all_names, p)) for p in prefixes]
    found_prefixes = [(p, c) for p, c in found_prefixes if c > 0]
    found_prefixes.sort(key=lambda x: -x[1])

    if found_prefixes:
        lines.append("### Common function prefixes")
        for prefix, count in found_prefixes[:8]:
            lines.append(f"- `{prefix}*` — {count} occurrences")
        lines.append("")

    # Class suffixes — indicates architectural patterns
    class_local = [n.split('.')[-1] for n in class_names]
    suffixes = ['Service', 'Manager', 'Handler', 'Controller', 'Repository',
                'Client', 'Factory', 'Builder', 'Model', 'Schema', 'Error', 'Exception']
    found_suffixes = [(s, sum(1 for n in class_local if n.endswith(s))) for s in suffixes]
    found_suffixes = [(s, c) for s, c in found_suffixes if c > 0]
    found_suffixes.sort(key=lambda x: -x[1])

    if found_suffixes:
        lines.append("### Architectural patterns (class suffixes)")
        for suffix, count in found_suffixes[:8]:
            lines.append(f"- `*{suffix}` — {count} class{'es' if count != 1 else ''}")
        lines.append("")

    return lines


def _section_hotspots(conn: sqlite3.Connection) -> list[str]:
    lines = ["## Hotspots", ""]

    # Largest functions by line count
    size_rows = conn.execute(
        """
        SELECT name, file_path, start_line, end_line,
               (end_line - start_line + 1) as line_count
        FROM symbols
        WHERE is_test = 0 AND kind IN ('function', 'method', 'class')
        ORDER BY line_count DESC
        LIMIT 10
        """
    ).fetchall()

    lines.append("### Largest functions (by line count)")
    if size_rows:
        for name, fp, sl, el, lc in size_rows:
            lines.append(f"- `{name}` — {lc} lines ({fp}:{sl}-{el})")
    else:
        lines.append("- *(none)*")
    lines.append("")

    # Test coverage map — which source files have test counterparts
    source_files = {
        row[0] for row in conn.execute(
            "SELECT DISTINCT file_path FROM symbols WHERE is_test=0"
        ).fetchall()
    }
    tested_files = {
        row[0] for row in conn.execute(
            """
            SELECT DISTINCT ce.file_path
            FROM edges e
            JOIN symbols cs ON cs.id = e.caller_id AND cs.is_test = 1
            JOIN symbols ce ON ce.id = e.callee_id AND ce.is_test = 0
            """
        ).fetchall()
    }
    untested = sorted(source_files - tested_files)

    lines.append("### Test coverage map")
    lines.append(f"- **{len(tested_files)}/{len(source_files)}** source files have test coverage")
    if untested:
        lines.append("- Files with no test references:")
        for f in untested[:10]:
            lines.append(f"  - `{f}`")
    lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_knowledge(conn: sqlite3.Connection, root: Path) -> str:
    total_symbols = conn.execute("SELECT COUNT(*) FROM symbols WHERE is_test=0").fetchone()[0]
    total_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    total_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    header = [
        f"# Project Knowledge — {root.name}",
        "",
        f"> {total_symbols} symbols · {total_files} files · {total_edges} call edges",
        "> Generated by sigil. Re-run `sigil knowledge` to refresh.",
        "",
        "---",
        "",
    ]

    body = (
        _section_architecture(conn)
        + ["---", ""]
        + _section_business_logic(conn)
        + ["---", ""]
        + _section_conventions(conn)
        + ["---", ""]
        + _section_hotspots(conn)
    )

    return "\n".join(header + body)


def write_knowledge(conn: sqlite3.Connection, root: Path) -> Path:
    out = root / ".sigil" / "knowledge.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(generate_knowledge(conn, root), encoding='utf-8')
    return out
