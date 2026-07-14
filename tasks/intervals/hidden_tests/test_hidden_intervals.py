import unittest

from intervals import IntervalSet


class TestAddAndNormalize(unittest.TestCase):
    def test_empty_set(self):
        s = IntervalSet()
        self.assertEqual(s.intervals(), [])
        self.assertEqual(s.total(), 0)

    def test_single_add(self):
        s = IntervalSet()
        s.add(1, 5)
        self.assertEqual(s.intervals(), [(1, 5)])
        self.assertEqual(s.total(), 4)

    def test_disjoint_adds_sorted(self):
        s = IntervalSet()
        s.add(10, 12)
        s.add(1, 3)
        s.add(5, 7)
        self.assertEqual(s.intervals(), [(1, 3), (5, 7), (10, 12)])

    def test_overlapping_adds_merge(self):
        s = IntervalSet()
        s.add(1, 5)
        s.add(3, 8)
        self.assertEqual(s.intervals(), [(1, 8)])

    def test_adjacent_adds_merge(self):
        s = IntervalSet()
        s.add(1, 3)
        s.add(3, 5)
        self.assertEqual(s.intervals(), [(1, 5)])

    def test_add_bridging_many(self):
        s = IntervalSet()
        s.add(1, 2)
        s.add(4, 5)
        s.add(7, 8)
        s.add(2, 7)
        self.assertEqual(s.intervals(), [(1, 8)])

    def test_add_covered_range_is_noop(self):
        s = IntervalSet()
        s.add(1, 10)
        s.add(3, 4)
        s.add(1, 10)
        self.assertEqual(s.intervals(), [(1, 10)])

    def test_negative_coordinates(self):
        s = IntervalSet()
        s.add(-5, -2)
        s.add(-3, 1)
        self.assertEqual(s.intervals(), [(-5, 1)])
        self.assertTrue(s.contains(-5))
        self.assertFalse(s.contains(1))


class TestRemove(unittest.TestCase):
    def test_remove_middle_splits(self):
        s = IntervalSet()
        s.add(1, 10)
        s.remove(4, 6)
        self.assertEqual(s.intervals(), [(1, 4), (6, 10)])
        self.assertEqual(s.total(), 7)

    def test_remove_exact_interval(self):
        s = IntervalSet()
        s.add(1, 5)
        s.remove(1, 5)
        self.assertEqual(s.intervals(), [])

    def test_remove_across_multiple(self):
        s = IntervalSet()
        s.add(1, 3)
        s.add(5, 7)
        s.add(9, 11)
        s.remove(2, 10)
        self.assertEqual(s.intervals(), [(1, 2), (10, 11)])

    def test_remove_uncovered_is_noop(self):
        s = IntervalSet()
        s.add(1, 3)
        s.remove(5, 8)
        self.assertEqual(s.intervals(), [(1, 3)])

    def test_remove_adjacent_range_is_noop(self):
        s = IntervalSet()
        s.add(1, 3)
        s.remove(3, 5)
        s.remove(0, 1)
        self.assertEqual(s.intervals(), [(1, 3)])

    def test_remove_trims_edges(self):
        s = IntervalSet()
        s.add(1, 10)
        s.remove(1, 3)
        s.remove(8, 12)
        self.assertEqual(s.intervals(), [(3, 8)])


class TestQueries(unittest.TestCase):
    def test_contains_half_open_boundaries(self):
        s = IntervalSet()
        s.add(1, 3)
        self.assertTrue(s.contains(1))
        self.assertTrue(s.contains(2))
        self.assertFalse(s.contains(3))
        self.assertFalse(s.contains(0))

    def test_overlaps_true_on_intersection(self):
        s = IntervalSet()
        s.add(1, 5)
        self.assertTrue(s.overlaps(4, 8))
        self.assertTrue(s.overlaps(0, 2))
        self.assertTrue(s.overlaps(2, 3))
        self.assertTrue(s.overlaps(0, 10))

    def test_overlaps_false_on_adjacency(self):
        s = IntervalSet()
        s.add(1, 3)
        self.assertFalse(s.overlaps(3, 5))
        self.assertFalse(s.overlaps(-1, 1))
        self.assertFalse(s.overlaps(5, 7))

    def test_total_multiple(self):
        s = IntervalSet()
        s.add(1, 3)
        s.add(10, 14)
        self.assertEqual(s.total(), 6)


class TestValidation(unittest.TestCase):
    def test_empty_and_inverted_ranges_raise(self):
        s = IntervalSet()
        for method in (s.add, s.remove, s.overlaps):
            with self.subTest(method=method.__name__):
                with self.assertRaises(ValueError):
                    method(3, 3)
                with self.assertRaises(ValueError):
                    method(5, 2)

    def test_non_int_raises_type_error(self):
        s = IntervalSet()
        for bad in (1.5, "1", None, True):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    s.add(bad, 10)
                with self.assertRaises(TypeError):
                    s.contains(bad)


if __name__ == "__main__":
    unittest.main()
