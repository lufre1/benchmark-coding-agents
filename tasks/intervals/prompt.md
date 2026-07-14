You are being evaluated as a coding agent.

Task: Implement an interval-set library in Python (standard library only).

Create a class called `IntervalSet` that maintains a set of disjoint, half-open integer intervals `[start, end)` and keeps them normalized (sorted, non-overlapping, non-adjacent).

Public API:

```python
class IntervalSet:
    def add(self, start: int, end: int) -> None: ...
    def remove(self, start: int, end: int) -> None: ...
    def contains(self, point: int) -> bool: ...
    def overlaps(self, start: int, end: int) -> bool: ...
    def intervals(self) -> list[tuple[int, int]]: ...
    def total(self) -> int: ...
```

Semantics:

- All intervals are half-open: `[start, end)` includes `start`, excludes `end`.
- `add(start, end)` adds the range. Overlapping **and adjacent** intervals merge into one: adding `[1, 3)` and `[3, 5)` yields the single interval `[1, 5)`. Adding an already-covered range changes nothing.
- `remove(start, end)` removes the range from the set. Removing from the middle of an interval splits it in two. Removing a range that is not (fully or partially) covered is not an error — only the covered parts are removed.
- `contains(point)` is True iff some interval covers the point (boundary rules follow from half-openness).
- `overlaps(start, end)` is True iff the range `[start, end)` intersects any interval by at least one point. Mere adjacency is NOT overlap: if the set holds `[1, 3)`, then `overlaps(3, 5)` is False.
- `intervals()` returns the normalized intervals as a sorted list of `(start, end)` tuples.
- `total()` returns the total number of integer points covered (sum of `end - start`).

Validation:

- `start` and `end` must be `int` (`bool` does not count as int here). Anything else raises `TypeError`.
- For `add`, `remove`, and `overlaps`: `start < end` is required; empty or inverted ranges raise `ValueError`.

The implementation should be reasonably efficient and must not use any third-party libraries.

Deliverables (in the current working directory):

- `intervals.py` — the implementation.
- `test_intervals.py` — your own unit tests (unittest or pytest).
- `NOTES.md` — brief design explanation and edge cases handled.
