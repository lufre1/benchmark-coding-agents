import math
import unittest

from csvstats import (
    column_stats,
    parse_csv,
    quantile,
    sniff_delimiter,
    summarize,
    to_float,
    top_k,
)

COMMA_CSV = "name,score\nalice,10\nbob,20\ncarol,30\n"
SEMI_CSV = "name;score\nalice;10\nbob;20\ncarol;30\n"


def rows_with_scores(scores):
    return [{"name": f"r{i}", "score": str(v)} for i, v in enumerate(scores)]


class TestBug1Quantile(unittest.TestCase):
    def test_median_even_length(self):
        self.assertEqual(quantile([1, 2, 3, 4], 0.5), 2.5)

    def test_quantile_interpolation(self):
        self.assertEqual(quantile([1, 2, 3, 4], 0.25), 1.75)

    def test_quantile_extremes(self):
        self.assertEqual(quantile([5, 1, 9], 0), 1)
        self.assertEqual(quantile([5, 1, 9], 1), 9)

    def test_median_via_column_stats(self):
        rows = rows_with_scores([1, 2, 3, 4])
        self.assertEqual(column_stats(rows, "score")["median"], 2.5)

    def test_quantile_invalid_inputs_still_raise(self):
        with self.assertRaises(ValueError):
            quantile([], 0.5)
        with self.assertRaises(ValueError):
            quantile([1, 2], 1.5)


class TestBug2TopK(unittest.TestCase):
    def test_top_k_idempotent(self):
        rows = rows_with_scores([10, 40, 20, 30])
        first = top_k(rows, "score", k=2)
        second = top_k(rows, "score", k=2)
        self.assertEqual(first, second)
        self.assertEqual([r["score"] for r in first], ["40", "30"])

    def test_top_k_does_not_mutate_callers_exclude(self):
        rows = rows_with_scores([10, 40, 20, 30])
        exclude = [40.0]
        result = top_k(rows, "score", k=2, exclude=exclude)
        self.assertEqual([r["score"] for r in result], ["30", "20"])
        self.assertEqual(exclude, [40.0])

    def test_top_k_dedupes_equal_values(self):
        rows = rows_with_scores([10, 10, 9])
        result = top_k(rows, "score", k=2)
        self.assertEqual([r["score"] for r in result], ["10", "9"])


class TestBug3Sniffing(unittest.TestCase):
    def test_quoted_semicolon_in_comma_file(self):
        text = '"name;id",score\nalice,10\n'
        rows = parse_csv(text)
        self.assertEqual(rows, [{"name;id": "alice", "score": "10"}])

    def test_plain_comma_file(self):
        self.assertEqual(sniff_delimiter(COMMA_CSV), ",")
        rows = parse_csv(COMMA_CSV)
        self.assertEqual(rows[0], {"name": "alice", "score": "10"})

    def test_plain_semicolon_file(self):
        self.assertEqual(sniff_delimiter(SEMI_CSV), ";")
        rows = parse_csv(SEMI_CSV)
        self.assertEqual(rows[0], {"name": "alice", "score": "10"})

    def test_explicit_delimiter_bypasses_sniffing(self):
        rows = parse_csv(SEMI_CSV, delimiter=";")
        self.assertEqual(rows[2], {"name": "carol", "score": "30"})


class TestBug4Missing(unittest.TestCase):
    def test_nan_marker_ignored(self):
        for marker in ("NaN", "nan", "null", "none", "NA", ""):
            with self.subTest(marker=marker):
                self.assertIsNone(to_float(marker))

    def test_mean_ignores_nan_rows(self):
        rows = rows_with_scores([10, "NaN", 20, "null"])
        stats = column_stats(rows, "score")
        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["mean"], 15)
        self.assertFalse(math.isnan(stats["mean"]))


class TestRegressions(unittest.TestCase):
    def test_basic_stats(self):
        rows = rows_with_scores([1, 2, 3])
        stats = column_stats(rows, "score")
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["mean"], 2)
        self.assertEqual(stats["min"], 1)
        self.assertEqual(stats["max"], 3)
        self.assertEqual(stats["median"], 2)

    def test_empty_column_stats(self):
        rows = [{"name": "alice"}]
        stats = column_stats(rows, "score")
        self.assertEqual(stats["count"], 0)
        self.assertIsNone(stats["mean"])

    def test_to_float_parses_numbers(self):
        self.assertEqual(to_float(" 3.5 "), 3.5)
        self.assertEqual(to_float("-2"), -2.0)
        self.assertIsNone(to_float("abc"))

    def test_summarize_numeric_columns_only(self):
        result = summarize(COMMA_CSV)
        self.assertEqual(set(result), {"score"})
        self.assertEqual(result["score"]["count"], 3)
        self.assertEqual(result["score"]["mean"], 20)

    def test_summarize_empty_text(self):
        self.assertEqual(summarize(""), {})


if __name__ == "__main__":
    unittest.main()
