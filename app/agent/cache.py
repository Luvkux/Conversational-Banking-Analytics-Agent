"""
Question → cached generation cache.

We cache the *generation* (SQL, retrieved tables, retrieved examples) keyed
on a normalized question hash. Execution is NOT cached — we re-run the SQL
against the DB every time so results stay fresh.

This is the right caching layer for a Text-to-SQL system: schema/data may
change underneath, but the question→SQL mapping is stable.

Thread-safety: protected by a lock for use behind FastAPI workers.
"""
from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CachedGeneration:
    sql: str
    retrieved_tables: tuple[str, ...]
    retrieved_examples: tuple[str, ...]
    attempts: int


def _normalize(question: str) -> str:
    q = question.strip().lower()
    q = re.sub(r"\s+", " ", q)
    q = re.sub(r"[?.!]+$", "", q)
    return q


def _key(question: str, mode: str) -> str:
    norm = _normalize(question)
    return hashlib.sha1(f"{mode}::{norm}".encode("utf-8")).hexdigest()


class LRUCache:
    def __init__(self, maxsize: int = 256) -> None:
        self._max = maxsize
        self._store: OrderedDict[str, CachedGeneration] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, question: str, mode: str = "rag") -> Optional[CachedGeneration]:
        k = _key(question, mode)
        with self._lock:
            if k in self._store:
                self._store.move_to_end(k)
                self.hits += 1
                return self._store[k]
            self.misses += 1
            return None

    def put(self, question: str, value: CachedGeneration, mode: str = "rag") -> None:
        k = _key(question, mode)
        with self._lock:
            self._store[k] = value
            self._store.move_to_end(k)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            return {"size": len(self._store), "hits": self.hits, "misses": self.misses}


_cache: LRUCache | None = None


def get_cache() -> LRUCache:
    global _cache
    if _cache is None:
        _cache = LRUCache(maxsize=256)
    return _cache
