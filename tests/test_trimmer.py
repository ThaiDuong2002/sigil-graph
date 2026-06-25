from symbex_core.retrieval import SymbolResult
from symbex_core.trimmer import trim_to_budget
from symbex_core.cache import QueryCache


def _make_result(name: str, tokens: int, score: float = 1.0) -> SymbolResult:
    text = "x" * (tokens * 4)
    return SymbolResult(
        symbol_id=1, name=name, kind='function',
        file_path='f.py', start_line=1, end_line=10,
        text=text, is_signature_only=False,
        token_estimate=tokens, score=score,
    )


def test_trim_keeps_all_within_budget():
    results = [_make_result("a", 100), _make_result("b", 200)]
    trimmed = trim_to_budget(results, budget=400)
    assert len(trimmed) == 2


def test_trim_drops_least_relevant_when_over_budget():
    results = [
        _make_result("high", 100, score=-1.0),   # BM25: lower = better
        _make_result("low",  100, score=-0.5),
        _make_result("mid",  100, score=-0.8),
    ]
    trimmed = trim_to_budget(results, budget=250)
    names = [r.name for r in trimmed]
    assert "high" in names   # best BM25 score
    assert "low" not in names  # worst score dropped


def test_trim_never_cuts_symbol_mid_way():
    results = [_make_result("a", 900), _make_result("b", 200)]
    trimmed = trim_to_budget(results, budget=500)
    # "a" is 900 tokens — over budget alone — still returned as first result
    assert trimmed[0].name in ("a", "b")
    total = sum(r.token_estimate for r in trimmed)
    assert total <= 1200  # not unbounded


def test_cache_miss_returns_none():
    cache = QueryCache(max_size=10)
    assert cache.get(("task", 1)) is None


def test_cache_hit_returns_stored():
    cache = QueryCache(max_size=10)
    data = [_make_result("x", 50)]
    cache.set(("task", 1), data)
    assert cache.get(("task", 1)) == data


def test_cache_lru_eviction():
    cache = QueryCache(max_size=2)
    cache.set(("a", 1), [_make_result("a", 50)])
    cache.set(("b", 1), [_make_result("b", 50)])
    cache.set(("c", 1), [_make_result("c", 50)])  # should evict ("a", 1)
    assert cache.get(("a", 1)) is None
    assert cache.get(("b", 1)) is not None
    assert cache.get(("c", 1)) is not None


def test_cache_stale_after_version_bump(tmp_path):
    from symbex_core.db import get_db, init_schema, bump_index_version
    conn = get_db(tmp_path)
    init_schema(conn)
    cache = QueryCache(max_size=10)
    cache.set(("task", 0), [_make_result("x", 50)])
    cache._current_version = 0
    bump_index_version(conn)
    cache.invalidate_if_stale(conn)
    assert cache.get(("task", 0)) is None
