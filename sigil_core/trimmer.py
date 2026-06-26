from sigil_core.retrieval import SymbolResult


def trim_to_budget(results: list[SymbolResult], budget: int) -> list[SymbolResult]:
    """Keep highest-scoring symbols that fit within `budget` tokens.
    BM25 scores are negative (lower = better), so sort ascending."""
    sorted_results = sorted(results, key=lambda r: r.score)
    kept: list[SymbolResult] = []
    used = 0
    for r in sorted_results:
        if used + r.token_estimate <= budget:
            kept.append(r)
            used += r.token_estimate
        elif not kept:
            # Always include at least one result even if over budget
            kept.append(r)
            break
    return kept
