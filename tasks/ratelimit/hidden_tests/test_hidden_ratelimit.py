import unittest

from ratelimit import RateLimiter


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TestBurstAndDeny(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.rl = RateLimiter(rate=1.0, capacity=5.0, clock=self.clock)

    def test_bucket_starts_full(self):
        self.assertEqual(self.rl.available("k"), 5.0)

    def test_burst_up_to_capacity_then_denied(self):
        for _ in range(5):
            self.assertTrue(self.rl.allow("k"))
        self.assertFalse(self.rl.allow("k"))

    def test_denied_request_consumes_nothing(self):
        self.assertTrue(self.rl.allow("k", 4.0))
        self.assertFalse(self.rl.allow("k", 2.0))
        self.assertEqual(self.rl.available("k"), 1.0)
        self.assertTrue(self.rl.allow("k", 1.0))


class TestRefill(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.rl = RateLimiter(rate=2.0, capacity=10.0, clock=self.clock)

    def test_refill_proportional_to_elapsed_time(self):
        self.assertTrue(self.rl.allow("k", 10.0))
        self.assertEqual(self.rl.available("k"), 0.0)
        self.clock.advance(3.0)
        self.assertEqual(self.rl.available("k"), 6.0)

    def test_refill_capped_at_capacity(self):
        self.assertTrue(self.rl.allow("k", 4.0))
        self.clock.advance(100.0)
        self.assertEqual(self.rl.available("k"), 10.0)

    def test_denied_then_allowed_after_wait(self):
        self.assertTrue(self.rl.allow("k", 10.0))
        self.assertFalse(self.rl.allow("k", 4.0))
        self.clock.advance(2.0)
        self.assertTrue(self.rl.allow("k", 4.0))

    def test_no_time_passes_no_refill(self):
        self.assertTrue(self.rl.allow("k", 10.0))
        self.assertEqual(self.rl.available("k"), 0.0)
        self.assertEqual(self.rl.available("k"), 0.0)


class TestKeysAndReset(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.rl = RateLimiter(rate=1.0, capacity=3.0, clock=self.clock)

    def test_keys_are_independent(self):
        self.assertTrue(self.rl.allow("a", 3.0))
        self.assertFalse(self.rl.allow("a"))
        self.assertEqual(self.rl.available("b"), 3.0)
        self.assertTrue(self.rl.allow("b", 3.0))

    def test_reset_restores_full_capacity(self):
        self.assertTrue(self.rl.allow("a", 3.0))
        self.assertFalse(self.rl.allow("a"))
        self.rl.reset("a")
        self.assertEqual(self.rl.available("a"), 3.0)
        self.assertTrue(self.rl.allow("a", 3.0))

    def test_fractional_tokens(self):
        self.assertTrue(self.rl.allow("a", 2.5))
        self.assertEqual(self.rl.available("a"), 0.5)
        self.assertTrue(self.rl.allow("a", 0.5))
        self.assertFalse(self.rl.allow("a", 0.5))
        self.clock.advance(0.25)
        self.assertEqual(self.rl.available("a"), 0.25)


class TestValidation(unittest.TestCase):
    def test_invalid_constructor_args(self):
        clock = FakeClock()
        for rate, capacity in ((0, 5), (-1, 5), (1, 0), (1, -2)):
            with self.subTest(rate=rate, capacity=capacity):
                with self.assertRaises(ValueError):
                    RateLimiter(rate=rate, capacity=capacity, clock=clock)

    def test_invalid_tokens_raise(self):
        rl = RateLimiter(rate=1.0, capacity=5.0, clock=FakeClock())
        with self.assertRaises(ValueError):
            rl.allow("k", 0)
        with self.assertRaises(ValueError):
            rl.allow("k", -1.0)

    def test_more_than_capacity_always_denied(self):
        clock = FakeClock()
        rl = RateLimiter(rate=1.0, capacity=5.0, clock=clock)
        self.assertFalse(rl.allow("k", 6.0))
        clock.advance(1000.0)
        self.assertFalse(rl.allow("k", 6.0))
        self.assertTrue(rl.allow("k", 5.0))

    def test_default_clock_works(self):
        rl = RateLimiter(rate=100.0, capacity=5.0)
        self.assertTrue(rl.allow("k"))


if __name__ == "__main__":
    unittest.main()
