You are being evaluated as a coding agent.

Task: Implement a token-bucket rate limiter in Python (standard library only).

Create a class called `RateLimiter` that rate-limits independent keys (e.g. user IDs) using the token-bucket algorithm.

Public API:

```python
class RateLimiter:
    def __init__(self, rate: float, capacity: float, clock=None) -> None: ...
    def allow(self, key: str, tokens: float = 1.0) -> bool: ...
    def available(self, key: str) -> float: ...
    def reset(self, key: str) -> None: ...
```

Semantics:

- Each key has its own bucket. A bucket holds at most `capacity` tokens and starts **full** (the first time a key is seen, it has `capacity` tokens).
- Tokens refill continuously at `rate` tokens per second, capped at `capacity`. Refill is based on elapsed time since the bucket was last updated — no background threads, no sleeping.
- `clock` is a zero-argument callable returning the current time in seconds as a float. If `clock` is None, use `time.monotonic`. All time arithmetic must go through this clock (this makes the limiter fully testable with a fake clock).
- `allow(key, tokens)`: if the bucket currently holds at least `tokens` tokens, consume them and return True; otherwise consume nothing and return False (no partial consumption, no debt).
- `available(key)`: current token count of the bucket (after applying refill), without consuming anything. For a never-seen key this is `capacity`.
- `reset(key)`: restore the key's bucket to full capacity.
- Buckets are independent: exhausting one key must not affect another.
- Fractional token amounts are allowed everywhere.

Validation:

- Constructor: `rate` and `capacity` must be positive numbers, otherwise `ValueError`.
- `allow`: `tokens` must be > 0, otherwise `ValueError`. Requesting more than `capacity` tokens returns False (it can never succeed).

Determinism requirement: with an injected fake clock, behavior must be exactly reproducible — the tests will use a fake clock and no real sleeps.

Deliverables (in the current working directory):

- `ratelimit.py` — the implementation.
- `test_ratelimit.py` — your own unit tests using a fake clock (unittest or pytest).
- `NOTES.md` — brief design explanation and edge cases handled.
