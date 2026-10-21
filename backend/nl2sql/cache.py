"""Reuse a recent answer to the same question, instead of asking the model again.

A model answer takes 20 to 80 seconds; the same question asked again a
minute later can reuse an answer within its authorization namespace
and bounded TTL. This is a freshness window, not a guarantee of unchanged data.
So successful answers are kept for a few minutes, keyed by the question
and everything that changes how it is answered.

Only successes are kept: a refusal or a failed query may succeed on the
next try, and an outage must never be replayed. Entries live in this
process's memory, so a restart empties the cache.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict

from nl2sql.cache_scope import CacheScope, digest
from nl2sql.pipeline import Answer

# Oldest entries are dropped beyond this; answers are small, but rows can
# be up to 1,000 each.
MAX_ENTRIES = 256
MAX_BYTES = 16 * 1024 * 1024
MAX_ENTRY_BYTES = 1024 * 1024


def cache_key(question: str, *parts: object) -> str:
    """Exact question text and typed parts: literals/punctuation retain meaning."""
    return digest(["query-key-v2", question, parts])


def scoped_cache_key(question: str, scope: CacheScope, *parts: object) -> str:
    """Only the server constructs scope after current authorization succeeds."""
    return cache_key(question, asdict(scope), parts)


class AnswerCache:
    """A small time-limited cache of successful answers. Thread-safe,
    because FastAPI runs each question in a worker thread."""

    def __init__(
        self,
        ttl_seconds: int,
        max_entries: int = MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, Answer]] = OrderedDict()
        self._lock = threading.Lock()
        self._bytes = 0
        self._sizes: dict[str, int] = {}

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0

    def get(self, key: str) -> Answer | None:
        if not self.enabled:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, answer = entry
            if self._clock() - stored_at >= self.ttl_seconds:
                del self._entries[key]
                self._bytes -= self._sizes.pop(key)
                return None
            self._entries.move_to_end(key)
            return answer

    def put(self, key: str, answer: Answer) -> None:
        if not self.enabled or answer.error is not None:
            return
        size = len(
            json.dumps(asdict(answer), default=str, ensure_ascii=False).encode("utf-8")
        )
        if size > MAX_ENTRY_BYTES or self.max_entries <= 0:
            return
        with self._lock:
            self._bytes -= self._sizes.pop(key, 0)
            self._sizes[key] = size
            self._bytes += size
            self._entries[key] = (self._clock(), answer)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries or self._bytes > MAX_BYTES:
                dropped, _ = self._entries.popitem(last=False)
                self._bytes -= self._sizes.pop(dropped)
