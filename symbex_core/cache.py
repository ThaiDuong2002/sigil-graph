from collections import OrderedDict
import sqlite3
from symbex_core.db import get_index_version
from symbex_core.retrieval import SymbolResult


class QueryCache:
    def __init__(self, max_size: int = 100):
        self._store: OrderedDict[tuple, list[SymbolResult]] = OrderedDict()
        self._max_size = max_size
        self._current_version: int = -1

    def get(self, key: tuple) -> list[SymbolResult] | None:
        if key in self._store:
            self._store.move_to_end(key)
            return self._store[key]
        return None

    def set(self, key: tuple, value: list[SymbolResult]) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = value
        if len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def invalidate_if_stale(self, conn: sqlite3.Connection) -> None:
        version = get_index_version(conn)
        if version != self._current_version:
            self._store.clear()
            self._current_version = version
