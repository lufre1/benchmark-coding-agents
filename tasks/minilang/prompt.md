You are being evaluated as a coding agent.

Task: Implement an interpreter for MiniLang, a small imperative programming language, in Python 3.11 using only the standard library.

Public API (your module must expose exactly these names):

```python
class LangError(Exception): ...          # base class for ALL language errors
class LangSyntaxError(LangError): ...    # lexing/parsing errors
class LangNameError(LangError): ...      # undefined variable; duplicate declaration
class LangTypeError(LangError): ...      # operand/condition type mismatch; calling a non-function
class LangArityError(LangError): ...     # wrong number of call arguments
class LangZeroDivError(LangError): ...   # division or modulo by zero

def run(source: str) -> list[str]:
    """Execute a MiniLang program. Returns the list of lines printed by
    `print` (one list element per print call). Raises a LangError subclass
    on any lexing, parsing, or runtime failure."""
```

Error messages are not graded — only the exception types. All syntax errors
(including misplaced `return`/`break`/`continue`, see below) must be raised
during parsing, before any statement executes.

Example:

```python
run('''
fn makeCounter() {
  let n = 0;
  fn inc() { n = n + 1; return n; }
  return inc;
}
let c = makeCounter();
print(c(), c());
print("done");
''')
# returns ["1 2", "done"]
```

## Lexical rules

- Whitespace (spaces, tabs, carriage returns, newlines) is insignificant
  outside string literals and only separates tokens.
- Comments: `//` to end of line. A `//` inside a string literal is not a
  comment.
- Identifiers: `[A-Za-z_][A-Za-z0-9_]*`. Keywords (`let fn return if else
  while break continue true false nil`) are reserved and can never be used
  as identifiers.
- Integer literals: `[0-9]+`, always decimal. Leading zeros are allowed and
  carry no special meaning (`007` is the integer 7). Integers are arbitrary
  precision. There is no `-7` literal: that is unary minus applied to `7`.
- String literals: double-quoted. The only valid escapes are `\"`, `\\`,
  `\n`, `\t`. Any other escape (e.g. `\q`), an unterminated string, or a
  raw (unescaped) newline inside a string literal is a `LangSyntaxError`.
- Lexing uses maximal munch: `<=` is one token, never `<` then `=`.

## Grammar

```
program    := statement* EOF
statement  := letStmt | assignStmt | fnDecl | ifStmt | whileStmt
            | returnStmt | breakStmt | continueStmt | block | exprStmt
letStmt    := "let" IDENT "=" expression ";"
assignStmt := IDENT "=" expression ";"
fnDecl     := "fn" IDENT "(" (IDENT ("," IDENT)*)? ")" block
ifStmt     := "if" "(" expression ")" block ("else" (block | ifStmt))?
whileStmt  := "while" "(" expression ")" block
returnStmt := "return" expression? ";"
breakStmt  := "break" ";"
continueStmt := "continue" ";"
block      := "{" statement* "}"
exprStmt   := expression ";"
expression := orExpr
orExpr     := andExpr ("||" andExpr)*
andExpr    := eqExpr ("&&" eqExpr)*
eqExpr     := relExpr (("==" | "!=") relExpr)*
relExpr    := addExpr (("<" | "<=" | ">" | ">=") addExpr)*
addExpr    := mulExpr (("+" | "-") mulExpr)*
mulExpr    := unary (("*" | "/" | "%") unary)*
unary      := ("-" | "!") unary | call
call       := primary ("(" (expression ("," expression)*)? ")")*
primary    := INT | STRING | "true" | "false" | "nil" | IDENT | "(" expression ")"
```

Notes on the grammar:

- Braces are mandatory for `if`, `else`, `while`, and `fn` bodies.
  `if (c) print(1);` without braces is a `LangSyntaxError`. `else` takes
  either a block or another `if` statement (this is how `else if` chains
  work); there is no dangling-else ambiguity.
- Assignment is a statement, not an expression. `=` appearing inside an
  expression (e.g. `print(x = 1);`) is a `LangSyntaxError`.
- No trailing commas in parameter or argument lists.
- Duplicate parameter names in a `fn` declaration (`fn f(a, a)`) are a
  `LangSyntaxError`.
- `return` outside a function body, and `break`/`continue` outside a loop,
  are `LangSyntaxError`s, detected at parse time. `break`/`continue` must be
  lexically inside a loop *within the same function*: a `fn` body nested
  inside a loop does not count (`while (true) { fn f() { break; } }` is a
  `LangSyntaxError`).

## Values and types

MiniLang has exactly five kinds of values:

- `int` — arbitrary-precision integers.
- `bool` — `true` and `false`. Bools are NOT ints: `true + 1` is a
  `LangTypeError`, and `true == 1` is `false`.
- `string` — immutable text.
- `nil` — the unit value.
- functions — first-class values (see Functions below).

There are no implicit conversions of any kind and no truthiness:
`if`/`while` conditions and the operands of `&&`, `||`, `!` must be bools,
otherwise `LangTypeError`.

## Operators

Precedence from lowest to highest; all binary operators are
left-associative:

| Level | Operators | Semantics |
|---|---|---|
| 1 | `\|\|` | Operands must be bool. Short-circuits: if the left is `true`, the right is not evaluated. |
| 2 | `&&` | Operands must be bool. Short-circuits: if the left is `false`, the right is not evaluated and never type-checked — `false && 5` evaluates to `false`, no error. |
| 3 | `==` `!=` | Any two values. Values of different types are simply unequal (never an error): `1 == "1"` is `false`, `true == 1` is `false`, `nil == nil` is `true`. Ints, bools, strings compare by value; functions compare by identity. |
| 4 | `<` `<=` `>` `>=` | Both operands must be ints, else `LangTypeError`. Note left-associativity: `1 < 2 < 3` parses as `(1 < 2) < 3`, which is a `LangTypeError` (bool compared with int). |
| 5 | `+` `-` | `+` requires two ints (addition) or two strings (concatenation); anything else is a `LangTypeError`. `-` requires two ints. |
| 6 | `*` `/` `%` | Ints only. `/` and `%` truncate toward zero (NOT Python floor semantics): `7 / 2 == 3`, `-7 / 2 == -3`, `7 / -2 == -3`, `-7 / -2 == 3`; `7 % 2 == 1`, `-7 % 2 == -1`, `7 % -2 == 1`, `-7 % -2 == -1`. The invariant `a == (a / b) * b + a % b` always holds. A right operand of 0 raises `LangZeroDivError`. |
| 7 | unary `-` `!` | `-` requires an int; `!` requires a bool. Else `LangTypeError`. |
| 8 | call `f(args)` | The callee must be a function value, else `LangTypeError`. Argument count must match the parameter count exactly, else `LangArityError`. Arguments are evaluated left to right. Calls chain: `f(1)(2)` calls the function returned by `f(1)`. |

## Variables and scoping

- `let x = expr;` declares `x` in the innermost (current) scope. Declaring a
  name that already exists *in the same scope instance* is a `LangNameError`
  at runtime.
- `x = expr;` assigns to the nearest enclosing binding of `x`, searching
  outward through the scope chain. If no binding exists, `LangNameError`.
- Reading an undeclared variable is a `LangNameError`.
- A block `{ ... }` introduces a new scope; inner `let`s shadow outer
  bindings. Every *execution* of a block creates a fresh scope instance, so
  a `let` inside a loop body is legal on every iteration.
- `fn name(...) { ... }` declares `name` in the current scope exactly like
  `let` (so redeclaring it in the same scope is a `LangNameError`).

## Functions and closures

- Functions are declared with `fn name(params) { body }` and are first-class:
  they can be passed as arguments, returned, and stored in variables.
- The declaration binds `name` when the declaration statement executes.
  There is no hoisting: calling a function before its declaration has
  executed is a `LangNameError`. (Mutual recursion works as long as both
  declarations execute before the first call, because names are resolved at
  call time.)
- A function captures its defining environment by reference (late binding):

  ```
  let x = 1;
  fn get() { return x; }
  x = 2;
  print(get());   // prints 2, not 1
  ```

  Closures over the same variable share it: mutations through one closure
  are visible through the other. Captured variables outlive the scope that
  created them.
- Parameters are declared in the function's body scope; a top-level `let`
  in the body reusing a parameter's name is a `LangNameError`.
- `return expr;` returns a value; `return;` returns `nil`; falling off the
  end of the body returns `nil`.
- Recursion is supported. Graded programs never exceed a call depth of 100 —
  but note that a recursive tree-walking evaluator in Python may need
  `sys.setrecursionlimit(...)` raised to handle even that comfortably.

## Built-in functions

Three built-ins are pre-bound in an outer scope that encloses the global
scope. They are ordinary function values. Because they live in an *outer*
scope, `let print = 5;` at the top level is legal shadowing, not a
redeclaration error.

| Builtin | Arity | Semantics |
|---|---|---|
| `print(v, ...)` | any (including zero) | Converts each argument using `str` rules below, joins them with a single space, and appends the result to the output as ONE list element. `print()` appends `""`. A string argument containing `\n` still produces one list element — elements are split per print call, never per newline. |
| `str(v)` | 1 | int → decimal digits (e.g. `"42"`, `"-7"`); bool → `"true"`/`"false"`; nil → `"nil"`; string → unchanged; function → `LangTypeError`. |
| `len(s)` | 1 | Length of a string. Non-string argument → `LangTypeError`. |

`print` applies the same conversion as `str`, so printing a function value
is also a `LangTypeError`. Wrong argument counts for `str`/`len` are
`LangArityError`s.

## Error taxonomy summary

| Exception | Raised for |
|---|---|
| `LangSyntaxError` | Any lexing or parsing failure: bad characters, bad escapes, unterminated strings, missing `;`/braces/parens, keyword used as identifier, trailing comma, `=` in an expression, duplicate parameter, misplaced `return`/`break`/`continue`. Always raised before execution begins. |
| `LangNameError` | Reading or assigning an undeclared variable; declaring (`let` or `fn`) a name already present in the same scope instance. |
| `LangTypeError` | Wrong operand type for any operator; non-bool `if`/`while` condition or logic operand; calling a non-function; `str`/`print` of a function; `len` of a non-string. |
| `LangArityError` | Calling any function (user-defined or builtin) with the wrong number of arguments. |
| `LangZeroDivError` | `/` or `%` with a zero right operand. |

All are subclasses of `LangError`. MiniLang has no try/catch: language
errors are not catchable from within MiniLang programs.

## Not in the language

There are no floats, no anonymous functions (`fn` is always a named
declaration), no arrays/lists/dicts/objects, no `for` loops, no string
indexing/slicing/ordering (`"a" < "b"` is a `LangTypeError`), no compound
assignment (`+=`), no increment/decrement, no ternary operator, no
try/catch, and no I/O besides `print`.

## Grading guarantees

Graded programs never exceed a call depth of 100 and never exceed roughly
100,000 loop iterations. Each graded program must complete in about 1 second
on modest hardware, so a straightforward tree-walking interpreter is fast
enough — but avoid gratuitous inefficiency (e.g. re-tokenizing inside the
evaluation loop).

## Implementation constraints

- Python 3.11, standard library only.
- Write the interpreter yourself: do not use `eval`, `exec`, `compile`, the
  `ast` module, or any parser-generator shortcuts.
- `run` must be self-contained per call: no global mutable state may leak
  between calls.

Write your own unit tests. They should cover at least:

- Printing every value type and multi-argument `print` joining.
- String escapes and rejected escapes.
- Operator precedence, associativity, and parentheses.
- Truncating division and modulo with all four sign combinations.
- Equality across types; function identity.
- Short-circuit evaluation of `&&` and `||`.
- Block scoping, shadowing, assignment through the scope chain.
- Same-scope redeclaration errors; fresh scope per loop iteration.
- `if`/`else if`/`else` chains; `while` with `break` and `continue`.
- Function declaration, calls, `return;`, falling off the end.
- Recursion and mutual recursion.
- Closures: independent instances, shared captured variables, late binding.
- No hoisting.
- Every error class with at least two distinct triggers.
- Parse-time detection of misplaced `return`/`break`/`continue`.
- Built-ins, their error cases, and builtin shadowing.

File layout (required):
- Put the implementation in `interp.py` in the current working directory.
- Put your unit tests in `test_interp.py`.
- Put the design explanation, edge-case notes, and complexity analysis in `NOTES.md`.
