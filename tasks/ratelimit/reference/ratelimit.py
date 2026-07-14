"""Reference solution for the ratelimit task. Never shown to agents."""

import time


class RateLimiter:
    def __init__(self, rate, capacity, clock=None):
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
            raise ValueError("rate must be a positive number")
        if not isinstance(capacity, (int, float)) or isinstance(capacity, bool) or capacity <= 0:
            raise ValueError("capacity must be a positive number")
        self._rate = float(rate)
        self._capacity = float(capacity)
        self._clock = clock if clock is not None else time.monotonic
        self._buckets = {}  # key -> [tokens, last_update]

    def _refill(self, key):
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = [self._capacity, now]
            self._buckets[key] = bucket
            return bucket
        tokens, last = bucket
        elapsed = now - last
        if elapsed > 0:
            tokens = min(self._capacity, tokens + elapsed * self._rate)
        bucket[0] = tokens
        bucket[1] = now
        return bucket

    def allow(self, key, tokens=1.0):
        if not isinstance(tokens, (int, float)) or isinstance(tokens, bool) or tokens <= 0:
            raise ValueError("tokens must be a positive number")
        bucket = self._refill(key)
        if bucket[0] >= tokens:
            bucket[0] -= tokens
            return True
        return False

    def available(self, key):
        return self._refill(key)[0]

    def reset(self, key):
        self._buckets[key] = [self._capacity, self._clock()]
