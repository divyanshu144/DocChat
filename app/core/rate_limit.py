"""Bounded, per-process IP limits for the single-worker deployment."""
import math
import time
from collections import OrderedDict, deque
from threading import Lock


class RateLimiter:
    def __init__(self, max_keys: int = 10000):
        self._buckets = OrderedDict()
        self._lock = Lock()
        self.max_keys = max_keys

    def check(self, key: tuple, limit: int, window: int, *, now: float | None = None) -> int:
        """Return zero when allowed, otherwise Retry-After seconds."""
        now = time.monotonic() if now is None else now
        with self._lock:
            # Access-order buckets let us expire unused IPs without unbounded growth.
            while self._buckets:
                oldest_key, oldest = next(iter(self._buckets.items()))
                if oldest[-1] > now - window:
                    break
                del self._buckets[oldest_key]
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self.max_keys:
                    return window
                bucket = deque()
                self._buckets[key] = bucket
            while bucket and bucket[0] <= now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                return max(1, math.ceil(bucket[0] + window - now))
            bucket.append(now)
            self._buckets.move_to_end(key)
            return 0


rate_limiter = RateLimiter()
