"""csvstats -- tiny CSV summary-statistics helper (stdlib only).

Reads CSV text (comma- or semicolon-delimited), extracts numeric columns
and computes summary statistics. Missing values are ignored.
"""

import csv
import io
import math


def sniff_delimiter(text):
    """Guess the delimiter (',' or ';') from the first line."""
    first_line = text.splitlines()[0] if text else ""
    if not first_line:
        return ","
    # When sniffing, we need to handle the case where a delimiter appears inside quotes
    # The issue: csv.reader respects quotes, so with delimiter=',' and text='"name;id",score'
    # we get 2 fields. With delimiter=';' we also get 1 field because comma is not ignored.
    #
    # The fix: use a more robust approach - count fields by actually parsing with each
    # delimiter and see which produces more "sensible" results. For CSVs, the correct
    # delimiter should produce more fields (since it properly separates fields).
    
    comma_reader = csv.reader(io.StringIO(first_line), delimiter=',')
    semicolon_reader = csv.reader(io.StringIO(first_line), delimiter=';')
    comma_fields = len(list(comma_reader)[0])
    semicolon_fields = len(list(semicolon_reader)[0])
    
    # Return the delimiter that produces more fields
    # This handles both cases correctly
    if semicolon_fields > comma_fields:
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
    if text.lower() in ("", "na", "null", "none"):
        return None
    try:
        result = float(text)
        if math.isnan(result):
            return None
        return result
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
    n = len(ordered)
    pos = q * (n - 1)
    lower = int(pos)
    upper = lower + 1
    # Clamp upper to stay within bounds
    if upper >= n:
        upper = n - 1
    # Linear interpolation
    weight = pos - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


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
    if exclude is None:
        exclude_set = set()
    else:
        exclude_set = set(exclude)

    def sort_key(row):
        v = to_float(row.get(column))
        return -math.inf if v is None else v

    picked = []
    seen_values = set()
    for row in sorted(rows, key=sort_key, reverse=True):
        v = to_float(row.get(column))
        if v is None or v in exclude_set or v in seen_values:
            continue
        picked.append(row)
        seen_values.add(v)
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
