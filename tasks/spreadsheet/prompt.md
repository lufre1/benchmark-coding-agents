You are being evaluated as a coding agent.

Task: Implement a small spreadsheet engine in Python 3.11 using only the standard library.

Create a class called `Spreadsheet`.

Public API:

```python
class Spreadsheet:
    def set_cell(self, cell: str, value: str | int | float) -> None:
        ...

    def get_cell(self, cell: str) -> int | float | str:
        ...

    def get_formula(self, cell: str) -> str | None:
        ...

    def clear_cell(self, cell: str) -> None:
        ...

    def get_dependencies(self, cell: str) -> set[str]:
        ...

    def get_dependents(self, cell: str) -> set[str]:
        ...
Cell names:
Valid names look like A1, B2, AA10.
Columns are uppercase letters only.
Rows are positive integers starting at 1.
Invalid names should raise ValueError.
Supported values:
Numbers:
sheet.set_cell("A1", 10)
sheet.set_cell("A2", 3.5)
Plain strings:
sheet.set_cell("B1", "hello")
Strings that do not start with = are stored as text.
Formulas:
Formulas are strings starting with =.
Supported operators: +, -, *, /
Parentheses must be supported.
Cell references must be supported.
Formulas may contain whitespace.
Formulas may reference other formula cells.
Formula values should update when referenced cells change.
Examples:
sheet = Spreadsheet()
sheet.set_cell("A1", 10)
sheet.set_cell("A2", 20)
sheet.set_cell("B1", "=A1+A2")
assert sheet.get_cell("B1") == 30
Functions and ranges:
Supported functions:
SUM(...)
AVG(...)
MIN(...)
MAX(...)
Ranges:
Ranges are rectangular.
Example: A1:B2 includes A1, A2, B1, B2.
Ranges may only appear as arguments to SUM, AVG, MIN, or MAX.
Examples:
sheet.set_cell("A1", 10)
sheet.set_cell("A2", 20)
sheet.set_cell("C1", "=SUM(A1:A2)")
assert sheet.get_cell("C1") == 30

sheet.set_cell("D1", "=AVG(A1:A2)")
assert sheet.get_cell("D1") == 15

sheet.set_cell("E1", "=SUM(A1:A2, 5, A1*2)")
assert sheet.get_cell("E1") == 55
Error behavior:
Division by zero should raise ZeroDivisionError.
Referencing an empty cell should treat it as numeric 0.
Referencing a text cell in a numeric formula should raise TypeError.
Invalid formulas should raise ValueError.
Unsupported functions should raise ValueError.
Dependency tracking:
get_dependencies(cell) should return the direct cells referenced by that cell’s formula.
If C1 is =A1+B1, dependencies are {"A1", "B1"}.
If D1 is =SUM(A1:A3), dependencies are {"A1", "A2", "A3"}.
get_dependents(cell) should return direct cells that depend on the given cell.
Cycle detection:
Cycles must be detected when setting formulas.
If setting a formula would create a cycle, set_cell should raise ValueError.
If a cyclic update fails, the spreadsheet must remain unchanged.
Example:
sheet.set_cell("A1", "=B1")
sheet.set_cell("B1", "=C1")

# This should raise ValueError and leave C1 unchanged.
sheet.set_cell("C1", "=A1")
Clearing cells:
clear_cell(cell) removes the cell’s value/formula.
Cells that depend on the cleared cell should treat it as 0.
Example:
sheet = Spreadsheet()
sheet.set_cell("A1", 10)
sheet.set_cell("B1", "=A1*2")

assert sheet.get_cell("B1") == 20

sheet.set_cell("A1", 7)
assert sheet.get_cell("B1") == 14

sheet.clear_cell("A1")
assert sheet.get_cell("B1") == 0
Implementation constraints:
Use only the Python standard library.
Do not use eval or exec.
Do not use third-party expression parsers.
Avoid global mutable state.
The implementation should be reasonably efficient.
Deliverables:
Implementation of Spreadsheet.
Unit tests using unittest or pytest.
Brief explanation of the design.
Notes on edge cases handled.
Time complexity for:
setting a cell
getting a cell
clearing a cell
Tests should cover at least:
Basic numeric cells.
Basic text cells.
Basic formulas.
Operator precedence.
Parentheses.
Whitespace.
Formula updates after changing dependencies.
Formula updates after clearing dependencies.
Direct dependencies.
Direct dependents.
Ranges.
Rectangular ranges.
SUM, AVG, MIN, MAX.
Function arguments mixing ranges and expressions.
Empty cells as zero.
Text cells in numeric formulas.
Division by zero.
Invalid cell names.
Invalid formulas.
Unsupported functions.
Direct cycles.
Indirect cycles.
Failed cyclic update leaves spreadsheet unchanged.

File layout (required):
- Put the implementation in `spreadsheet.py` in the current working directory.
- Put your unit tests in `test_spreadsheet.py`.
- Put the design explanation, edge-case notes, and complexity analysis in `NOTES.md`.
