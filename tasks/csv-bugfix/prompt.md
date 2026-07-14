You are being evaluated as a coding agent.

Task: Fix four reported bugs in `csvstats.py` (in the current working directory), a small stdlib-only CSV statistics module.

Users have filed the following bug reports. The reports describe observed behavior only — you need to find the causes in the code.

## Bug report 1 — wrong medians and quantiles

`column_stats(rows, "x")["median"]` for a column with the values 1, 2, 3, 4 returns 3, but the median should be 2.5. Columns with an odd number of values look correct.

Other quantiles are also off: `quantile([1, 2, 3, 4], 0.25)` should be 1.75.

Expected behavior (as the docstring already claims): linear interpolation between the two nearest order statistics — the quantile at fraction `q` sits at position `q * (n - 1)` in the sorted values, interpolating linearly when that position is not an integer. `q=0` must give the minimum, `q=1` the maximum.

## Bug report 2 — `top_k` is not idempotent

Calling `top_k(rows, "score")` twice in a row with the same arguments returns the correct rows the first time and different (or no) rows the second time, even though neither `rows` nor anything else changed between the calls.

Also, when a caller passes its own `exclude` list, that list gets modified by the call, which surprises callers who reuse it.

The documented skip semantics (values in `exclude` are skipped; each value appears at most once in the result) must be preserved.

## Bug report 3 — comma files containing semicolons mis-parse

A comma-delimited file whose quoted header field contains a semicolon is parsed as if it were semicolon-delimited, producing garbage. Example first line:

```
"name;id",score
```

This must parse as two columns, `name;id` and `score`. Ordinary semicolon-delimited files (and ordinary comma-delimited files) must keep working, and passing an explicit `delimiter` must still bypass sniffing entirely.

## Bug report 4 — "NaN" values poison the mean

Columns containing missing values written as `NaN` produce `mean = nan` instead of ignoring the missing entries. The markers `null` and `none` are also not ignored, even though the docstring says they should be. `""` and `NA` already work. Missing markers are case-insensitive.

## Constraints

- Fix the bugs in place in `csvstats.py`. Do not rewrite the module from scratch and do not change the public API (function names, parameters callers rely on, return shapes).
- All previously-correct behavior must keep working.
- Standard library only.
- Add regression tests covering the four fixes in `test_csvstats.py`.
- Briefly note the root cause of each bug in `NOTES.md`.
