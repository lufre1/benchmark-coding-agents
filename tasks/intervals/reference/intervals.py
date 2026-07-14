"""Reference solution for the intervals task. Never shown to agents."""

from bisect import bisect_left, bisect_right


def _check_point(value):
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"expected int, got {type(value).__name__}")


def _check_range(start, end):
    _check_point(start)
    _check_point(end)
    if start >= end:
        raise ValueError(f"invalid range [{start}, {end})")


class IntervalSet:
    def __init__(self):
        self._starts = []
        self._ends = []

    def add(self, start, end):
        _check_range(start, end)
        # Find all intervals that overlap or touch [start, end).
        lo = bisect_left(self._ends, start)
        hi = bisect_right(self._starts, end)
        if lo < hi:
            start = min(start, self._starts[lo])
            end = max(end, self._ends[hi - 1])
        self._starts[lo:hi] = [start]
        self._ends[lo:hi] = [end]

    def remove(self, start, end):
        _check_range(start, end)
        # Intervals strictly overlapping [start, end).
        lo = bisect_right(self._ends, start)
        hi = bisect_left(self._starts, end)
        if lo >= hi:
            return
        new_starts, new_ends = [], []
        if self._starts[lo] < start:
            new_starts.append(self._starts[lo])
            new_ends.append(start)
        if self._ends[hi - 1] > end:
            new_starts.append(end)
            new_ends.append(self._ends[hi - 1])
        self._starts[lo:hi] = new_starts
        self._ends[lo:hi] = new_ends

    def contains(self, point):
        _check_point(point)
        idx = bisect_right(self._starts, point) - 1
        return idx >= 0 and point < self._ends[idx]

    def overlaps(self, start, end):
        _check_range(start, end)
        lo = bisect_right(self._ends, start)
        hi = bisect_left(self._starts, end)
        return lo < hi

    def intervals(self):
        return list(zip(self._starts, self._ends))

    def total(self):
        return sum(e - s for s, e in zip(self._starts, self._ends))
