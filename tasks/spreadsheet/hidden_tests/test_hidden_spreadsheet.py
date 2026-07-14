import unittest

from spreadsheet import Spreadsheet


class TestSpreadsheet(unittest.TestCase):
    def test_basic_numbers(self):
        s = Spreadsheet()
        s.set_cell("A1", 10)
        s.set_cell("B2", 3.5)

        self.assertEqual(s.get_cell("A1"), 10)
        self.assertEqual(s.get_cell("B2"), 3.5)

    def test_basic_text(self):
        s = Spreadsheet()
        s.set_cell("A1", "hello")
        self.assertEqual(s.get_cell("A1"), "hello")
        self.assertIsNone(s.get_formula("A1"))

    def test_basic_formula(self):
        s = Spreadsheet()
        s.set_cell("A1", 10)
        s.set_cell("A2", 20)
        s.set_cell("B1", "=A1+A2")

        self.assertEqual(s.get_cell("B1"), 30)
        self.assertEqual(s.get_formula("B1"), "=A1+A2")

    def test_operator_precedence(self):
        s = Spreadsheet()
        s.set_cell("A1", "=2+3*4")
        s.set_cell("A2", "=(2+3)*4")

        self.assertEqual(s.get_cell("A1"), 14)
        self.assertEqual(s.get_cell("A2"), 20)

    def test_whitespace(self):
        s = Spreadsheet()
        s.set_cell("A1", 10)
        s.set_cell("B1", "=  A1   +   5  ")

        self.assertEqual(s.get_cell("B1"), 15)

    def test_formula_updates_after_dependency_change(self):
        s = Spreadsheet()
        s.set_cell("A1", 10)
        s.set_cell("B1", "=A1*2")

        self.assertEqual(s.get_cell("B1"), 20)

        s.set_cell("A1", 7)
        self.assertEqual(s.get_cell("B1"), 14)

    def test_empty_cell_as_zero(self):
        s = Spreadsheet()
        s.set_cell("B1", "=A1+5")

        self.assertEqual(s.get_cell("B1"), 5)

    def test_clear_cell(self):
        s = Spreadsheet()
        s.set_cell("A1", 10)
        s.set_cell("B1", "=A1*2")

        self.assertEqual(s.get_cell("B1"), 20)

        s.clear_cell("A1")
        self.assertEqual(s.get_cell("B1"), 0)

    def test_dependencies_and_dependents(self):
        s = Spreadsheet()
        s.set_cell("A1", 10)
        s.set_cell("B1", 20)
        s.set_cell("C1", "=A1+B1")

        self.assertEqual(s.get_dependencies("C1"), {"A1", "B1"})
        self.assertEqual(s.get_dependents("A1"), {"C1"})
        self.assertEqual(s.get_dependents("B1"), {"C1"})

    def test_sum_range(self):
        s = Spreadsheet()
        s.set_cell("A1", 1)
        s.set_cell("A2", 2)
        s.set_cell("A3", 3)
        s.set_cell("B1", "=SUM(A1:A3)")

        self.assertEqual(s.get_cell("B1"), 6)
        self.assertEqual(s.get_dependencies("B1"), {"A1", "A2", "A3"})

    def test_rectangular_range(self):
        s = Spreadsheet()
        s.set_cell("A1", 1)
        s.set_cell("A2", 2)
        s.set_cell("B1", 3)
        s.set_cell("B2", 4)
        s.set_cell("C1", "=SUM(A1:B2)")

        self.assertEqual(s.get_cell("C1"), 10)
        self.assertEqual(
            s.get_dependencies("C1"),
            {"A1", "A2", "B1", "B2"},
        )

    def test_functions(self):
        s = Spreadsheet()
        s.set_cell("A1", 10)
        s.set_cell("A2", 20)
        s.set_cell("A3", 30)

        s.set_cell("B1", "=SUM(A1:A3)")
        s.set_cell("B2", "=AVG(A1:A3)")
        s.set_cell("B3", "=MIN(A1:A3)")
        s.set_cell("B4", "=MAX(A1:A3)")

        self.assertEqual(s.get_cell("B1"), 60)
        self.assertEqual(s.get_cell("B2"), 20)
        self.assertEqual(s.get_cell("B3"), 10)
        self.assertEqual(s.get_cell("B4"), 30)

    def test_function_mixed_arguments(self):
        s = Spreadsheet()
        s.set_cell("A1", 10)
        s.set_cell("A2", 20)
        s.set_cell("B1", "=SUM(A1:A2, 5, A1*2)")

        self.assertEqual(s.get_cell("B1"), 55)

    def test_text_in_numeric_formula_raises_type_error(self):
        s = Spreadsheet()
        s.set_cell("A1", "hello")
        s.set_cell("B1", "=A1+5")

        with self.assertRaises(TypeError):
            s.get_cell("B1")

    def test_division_by_zero(self):
        s = Spreadsheet()
        s.set_cell("A1", "=10/0")

        with self.assertRaises(ZeroDivisionError):
            s.get_cell("A1")

    def test_invalid_cell_names(self):
        s = Spreadsheet()

        invalid_names = ["", "a1", "A0", "1A", "A-1", "A", "11", "A1B"]

        for name in invalid_names:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    s.set_cell(name, 10)

    def test_invalid_formula(self):
        s = Spreadsheet()

        invalid_formulas = [
            "=",
            "=1+",
            "=SUM(",
            "=A1:",
            "=()",
        ]

        for formula in invalid_formulas:
            with self.subTest(formula=formula):
                with self.assertRaises(ValueError):
                    s.set_cell("A1", formula)

    def test_unsupported_function(self):
        s = Spreadsheet()

        with self.assertRaises(ValueError):
            s.set_cell("A1", "=MEDIAN(1,2,3)")

    def test_direct_cycle(self):
        s = Spreadsheet()

        with self.assertRaises(ValueError):
            s.set_cell("A1", "=A1")

    def test_indirect_cycle(self):
        s = Spreadsheet()
        s.set_cell("A1", "=B1")
        s.set_cell("B1", "=C1")

        with self.assertRaises(ValueError):
            s.set_cell("C1", "=A1")

    def test_failed_cyclic_update_leaves_state_unchanged(self):
        s = Spreadsheet()
        s.set_cell("A1", 10)
        s.set_cell("B1", "=A1+1")
        s.set_cell("C1", 100)

        with self.assertRaises(ValueError):
            s.set_cell("A1", "=B1")

        self.assertEqual(s.get_cell("A1"), 10)
        self.assertEqual(s.get_cell("B1"), 11)
        self.assertEqual(s.get_cell("C1"), 100)


if __name__ == "__main__":
    unittest.main()
