"""csvstats -- tiny CSV summary-statistics helper (stdlib only).

Reference solution with the four planted bugs fixed. Never shown to agents.
"""

import csv
import io
import math

_MISSING = {"", "na", "nan", "null", "none"}


def sniff_delimiter(text):
    """Guess the delimiter (',' or ';') from the first line."""
    first_line = text.splitlines()[0] if text else ""
    counts = {}
    for delim in (",", ";"):
        try:
            fields = next(csv.reader([first_line], delimiter=delim))
        except StopIteration:
            fields = []
        counts[delim] = len(fields)
    if counts[";"] > counts[","]:
        return ";"
    return ","


def parse_csv(text, delimiter=None):
    """Parse CSV text into a list of dicts (one per row, keyed by header).

    If `delimiter` is None it is guessed from the first line.
    """
    if delimiter is None:
        delimiter = sniff_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return [dict(row) for row in reader]


def to_float(value):
    """Convert a CSV field to float, or None if missing/non-numeric.

    Missing markers: "", "NA", "NaN", "null", "none" (case-insensitive).
    """
    if value is None:
        return None
    text = value.strip()
    if text.lower() in _MISSING:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def numeric_column(rows, column):
    """All non-missing numeric values of `column`, in row order."""
    values = []
    for row in rows:
        v = to_float(row.get(column))
        if v is not None:
            values.append(v)
    return values


def quantile(values, q):
    """Quantile of `values` (q in [0, 1]) with linear interpolation
    between the two nearest order statistics."""
    if not values:
        raise ValueError("quantile of empty data")
    if not 0 <= q <= 1:
        raise ValueError("q must be in [0, 1]")
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return ordered[lower]
    frac = pos - lower
    return ordered[lower] * (1 - frac) + ordered[upper] * frac


def column_stats(rows, column):
    """Summary stats dict for a column: count, mean, min, max, median."""
    values = numeric_column(rows, column)
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None, "median": None}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
        "median": quantile(values, 0.5),
    }


def top_k(rows, column, k=5, exclude=None):
    """Return the k rows with the largest numeric value in `column`.

    Values listed in `exclude` are skipped. Rows whose value equals an
    already-picked value are skipped too (each value appears at most once).
    """
    seen = set(exclude) if exclude else set()

    def sort_key(row):
        v = to_float(row.get(column))
        return -math.inf if v is None else v

    picked = []
    for row in sorted(rows, key=sort_key, reverse=True):
        v = to_float(row.get(column))
        if v is None or v in seen:
            continue
        picked.append(row)
        seen.add(v)
        if len(picked) == k:
            break
    return picked


def summarize(text, delimiter=None):
    """Stats for every numeric column of the CSV text.

    Returns {column: stats_dict} for each column that has at least one
    numeric value.
    """
    rows = parse_csv(text, delimiter)
    if not rows:
        return {}
    result = {}
    for column in rows[0]:
        if numeric_column(rows, column):
            result[column] = column_stats(rows, column)
    return result
