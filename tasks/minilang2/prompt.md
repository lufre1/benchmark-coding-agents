You are being evaluated as a coding agent.

Task: Implement an interpreter for MiniLang2, a small imperative programming
language, in Python (3.10+) using only the standard library. MiniLang2 is a
strict superset of a simple expression/statement language: it has first-class
functions and closures, arrays and dicts with reference semantics, `for`
loops with per-iteration bindings, `try`/`catch`/`finally`, and a precise
error taxonomy where every error knows its source position.

This spec is long and exact. Every graded behavior is stated here, most with
a worked example. Read carefully: the grading rewards precise spec
compliance, especially in the sections marked as commonly-gotten-wrong.

**Build incrementally.** Get the core language (literals, arithmetic,
variables, `if`/`while`, functions, closures, the error classes) working and
self-tested first; then add containers, `for`, and `try`/`catch`/`finally`.
A partially complete but importable, runnable module earns partial credit; a
file that does not import earns nothing.

## Public API

Your module must expose exactly these names:

```python
class LangError(Exception): ...          # base class for ALL language errors
class LangSyntaxError(LangError): ...    # lexing/parsing errors
class LangNameError(LangError): ...      # undefined variable; duplicate declaration
class LangTypeError(LangError): ...      # operand/condition type mismatch; calling a non-function; bad index type
class LangArityError(LangError): ...     # wrong number of call arguments
class LangZeroDivError(LangError): ...   # division or modulo by zero
class LangIndexError(LangError): ...     # array/string index out of range (including negative)
class LangKeyError(LangError): ...       # missing dict key
class LangValueError(LangError): ...     # structurally valid but unacceptable value (see taxonomy)
class LangThrownError(LangError): ...    # a user `throw` of a non-error value reached the top level

def run(source: str) -> list[str]:
    """Execute a MiniLang2 program. Returns the list of lines printed by
    `print` (one list element per print call). Raises a LangError subclass
    on any lexing, parsing, or runtime failure."""
```

Every instance of a `LangError` subclass must carry two attributes,
`e.line` and `e.col` (integers, both 1-based), giving the source position
of the error. The exact anchor token is specified — and graded — only for
the cases listed in the **Error positions** section; for all other errors
the attributes must exist and be integers, but the exact values are up to
you. Error *messages* are never graded — only the exception types and the
graded positions.

All syntax errors (including misplaced `return`/`break`/`continue`, see
below) must be raised during parsing, before any statement executes.

Example:

```python
run('''
fn tally() {
  let total = 0;
  fn add(xs) {
    for (v in xs) { total += v; }
    return total;
  }
  return add;
}
let t = tally();
print(t([3, 4]));
print(t([10]));
''')
# returns ["7", "17"]
```

## Lexical rules

- Whitespace (spaces, tabs, carriage returns, newlines) is insignificant
  outside string literals and only separates tokens.
- Comments: `//` to end of line. A `//` inside a string literal is not a
  comment.
- Identifiers: `[A-Za-z_][A-Za-z0-9_]*`. Keywords (`let fn return if else
  while for in break continue true false nil try catch finally throw`) are
  reserved and can never be used as identifiers: `let in = 1;` is a
  `LangSyntaxError`.
- Integer literals: `[0-9]+`, always decimal. Leading zeros are allowed and
  carry no special meaning (`007` is the integer 7). Integers are arbitrary
  precision. There is no `-7` literal: that is unary minus applied to `7`.
- String literals: double-quoted. The only valid escapes are `\"`, `\\`,
  `\n`, `\t`. Any other escape (e.g. `\q`), an unterminated string, or a
  raw (unescaped) newline inside a string literal is a `LangSyntaxError`.
- Lexing uses maximal munch: `<=` is one token, never `<` then `=`; `**` is
  one token, never `*` then `*`; `+=` is one token, never `+` then `=`.
- Source positions: lines are 1-based and advance at each `\n`; columns are
  1-based counts of characters within the line (a tab counts as one
  column).

## Grammar

```
program    := statement* EOF
statement  := letStmt | assignStmt | fnDecl | ifStmt | whileStmt | forStmt
            | forInStmt | tryStmt | throwStmt | returnStmt | breakStmt
            | continueStmt | block | exprStmt
letStmt    := "let" IDENT "=" expression ";"
assignStmt := target assignOp expression ";"
assignOp   := "=" | "+=" | "-=" | "*=" | "/=" | "%="
fnDecl     := "fn" IDENT "(" (IDENT ("," IDENT)*)? ")" block
ifStmt     := "if" "(" expression ")" block ("else" (block | ifStmt))?
whileStmt  := "while" "(" expression ")" block
forStmt    := "for" "(" "let" IDENT "=" expression ";" expression ";" forStep ")" block
forStep    := target assignOp expression
forInStmt  := "for" "(" IDENT "in" expression ")" block
tryStmt    := "try" block catchClause? finallyClause?    // at least one clause required
catchClause   := "catch" "(" IDENT ")" block
finallyClause := "finally" block
throwStmt  := "throw" expression ";"
returnStmt := "return" expression? ";"
breakStmt  := "break" ";"
continueStmt := "continue" ";"
block      := "{" statement* "}"
exprStmt   := expression ";"

expression := ternary
ternary    := orExpr ("?" ternary ":" ternary)?
orExpr     := andExpr ("||" andExpr)*
andExpr    := eqExpr ("&&" eqExpr)*
eqExpr     := relExpr (("==" | "!=") relExpr)*
relExpr    := addExpr (("<" | "<=" | ">" | ">=") addExpr)*
addExpr    := mulExpr (("+" | "-") mulExpr)*
mulExpr    := unary (("*" | "/" | "%") unary)*
unary      := ("-" | "!") unary | power
power      := postfix ("**" unary)?
postfix    := primary (callSuffix | indexSuffix | sliceSuffix)*
callSuffix := "(" (expression ("," expression)*)? ")"
indexSuffix := "[" expression "]"
sliceSuffix := "[" expression? ":" expression? "]"
primary    := INT | STRING | "true" | "false" | "nil" | IDENT
            | arrayLit | dictLit | "(" expression ")"
arrayLit   := "[" (expression ("," expression)*)? "]"
dictLit    := "{" (STRING ":" expression ("," STRING ":" expression)*)? "}"
```

Notes on the grammar:

- Braces are mandatory for `if`, `else`, `while`, `for`, `try`, `catch`,
  `finally`, and `fn` bodies. `if (c) print(1);` without braces is a
  `LangSyntaxError`. `else` takes either a block or another `if` statement
  (this is how `else if` chains work).
- **A `{` in statement position always starts a block, never a dict
  literal.** A dict literal used as an expression statement must be
  parenthesized: `{"a": 1};` is parsed as a block (and is a
  `LangSyntaxError`, since `"a": 1` is not a statement), while
  `({"a": 1});` is a legal expression statement. In any expression
  position (`let d = {"a": 1};`, inside an array literal, as a call
  argument) `{` starts a dict literal as usual.
- Assignment is a statement, not an expression. `=` (or any compound
  assignment operator) appearing inside an expression, e.g.
  `print(x = 1);`, is a `LangSyntaxError`.
- **Assignment targets**: the target of an assignment (plain or compound)
  is parsed as an expression and must then be either a bare identifier or
  a postfix chain ending in an *index* suffix. Anything else —
  `f() = 1;`, `s[0:1] = x;` (a slice), `(x) = 1;` if you treat parens as
  consumed, `1 = 2;` — is a `LangSyntaxError`. `a[0] = 1;`,
  `d["k"] += 2;`, `grid[1][2] = 9;`, `f()[0] = 3;` are all valid targets.
- No trailing commas anywhere: parameter lists, argument lists, array
  literals, dict literals.
- Dict literal keys are string literals only (`{"a": 1}`; `{a: 1}` and
  `{1: 2}` are `LangSyntaxError`s). Duplicate keys in one dict literal
  (`{"a": 1, "a": 2}`) are a `LangSyntaxError`.
- Duplicate parameter names in a `fn` declaration (`fn f(a, a)`) are a
  `LangSyntaxError`.
- `return` outside a function body, and `break`/`continue` outside a loop,
  are `LangSyntaxError`s, detected at parse time. `break`/`continue` must
  be lexically inside a loop *within the same function*: a `fn` body
  nested inside a loop does not count
  (`while (true) { fn f() { break; } }` is a `LangSyntaxError`). These
  placement rules apply unchanged inside `try`/`catch`/`finally` blocks:
  a `break` in a `finally` is legal only if the whole `try` statement is
  lexically inside a loop in the same function.
- A `try` with neither `catch` nor `finally` is a `LangSyntaxError`.
  `throw;` without an expression is a `LangSyntaxError`.
- The three clauses of a C-style `for` are all mandatory. The step is an
  assignment (plain or compound) *without* a trailing semicolon:
  `for (let i = 0; i < 3; i += 1) { ... }`.

## Values and types

MiniLang2 has exactly eight kinds of values:

- `int` — arbitrary-precision integers.
- `bool` — `true` and `false`. Bools are NOT ints: `true + 1` is a
  `LangTypeError`, and `true == 1` is `false`.
- `string` — immutable text.
- `nil` — the unit value.
- functions — first-class values.
- `array` — mutable ordered sequence of values.
- `dict` — mutable string-keyed map that remembers insertion order.
- `error` — an opaque caught-error value (only produced by `catch`; see
  try/catch below).

There are no implicit conversions of any kind and no truthiness:
`if`/`while`/`for` conditions, ternary conditions, and the operands of
`&&`, `||`, `!` must be bools, otherwise `LangTypeError`.

**Reference semantics**: arrays and dicts are mutable objects. Binding,
assignment, argument passing, and storing into containers never copy them:

```
let a = [1, 2];
let b = a;          // b is the SAME array
push(b, 3);
print(a);           // [1, 2, 3]
```

## Operators

Precedence from lowest to highest. All binary operators are
left-associative except `?:` and `**`, which are right-associative:

| Level | Operators | Semantics |
|---|---|---|
| 1 | `c ? a : b` | Ternary conditional, right-associative: `p ? a : q ? b : c` parses as `p ? a : (q ? b : c)`. `c` must be a bool, else `LangTypeError`. Lazy: only the selected branch is evaluated — `true ? 1 : 1 / 0` is `1`, no error. |
| 2 | `\|\|` | Operands must be bool. Short-circuits: if the left is `true`, the right is not evaluated. |
| 3 | `&&` | Operands must be bool. Short-circuits: if the left is `false`, the right is not evaluated and never type-checked — `false && 5` evaluates to `false`, no error. |
| 4 | `==` `!=` | Any two values. Values of different types are simply unequal (never an error): `1 == "1"` is `false`, `true == 1` is `false`, `nil == nil` is `true`. Ints, bools, strings compare by value. Functions, arrays, dicts, and error values compare by identity: `[] == []` is `false`; `let a = [1]; let b = a; a == b` is `true`. Identity equality does NOT recurse: `[1] == [1]` is `false`. |
| 5 | `<` `<=` `>` `>=` | Both operands must be ints, else `LangTypeError` (strings are not ordered: `"a" < "b"` is a `LangTypeError`). Left-associativity trap: `1 < 2 < 3` parses as `(1 < 2) < 3`, which is a `LangTypeError` (bool compared with int). |
| 6 | `+` `-` | `+` requires two ints (addition) or two strings (concatenation); anything else — including two arrays — is a `LangTypeError`. `-` requires two ints. |
| 7 | `*` `/` `%` | Ints only. `/` and `%` truncate toward zero (NOT Python floor semantics): `7 / 2 == 3`, `-7 / 2 == -3`, `7 / -2 == -3`, `-7 / -2 == 3`; `7 % 2 == 1`, `-7 % 2 == -1`, `7 % -2 == 1`, `-7 % -2 == -1`. The invariant `a == (a / b) * b + a % b` always holds. A right operand of 0 raises `LangZeroDivError`. |
| 8 | unary `-` `!` | `-` requires an int; `!` requires a bool. Else `LangTypeError`. |
| 9 | `**` | Exponentiation, ints only (else `LangTypeError`). Right-associative: `2 ** 3 ** 2` is `2 ** (3 ** 2)` = `512`. Binds tighter than unary minus on its left: `-2 ** 2` is `-(2 ** 2)` = `-4`. Its right operand may itself be unary: `2 ** -1` parses — and then raises `LangValueError`, because a negative exponent is a `LangValueError` at runtime. `0 ** 0` is `1`. |
| 10 | call `f(args)`, index `x[i]`, slice `x[a:b]` | Postfix, chainable in any mix: `f(1)[0]("x")`. See the sections below. |

Operands of every binary operator are evaluated left to right; both
operands are evaluated before the operator's type checks run (except for
the lazy operators `?:`, `&&`, `\|\|`).

## Indexing

`x[i]`:

- `x` must be an array, string, or dict; indexing any other value is a
  `LangTypeError`.
- Arrays and strings: `i` must be an int (a bool is NOT an int: `a[true]`
  is a `LangTypeError`). Valid indices are `0 <= i < len(x)`; anything
  else — **including negative indices; there is no Python-style
  wraparound** — is a `LangIndexError`. `s[i]` on a string yields a
  one-character string.
- Dicts: `i` must be a string, else `LangTypeError`. Reading a key that is
  not present is a `LangKeyError`.

## Slicing

`x[a:b]`, `x[:b]`, `x[a:]`, `x[:]` — arrays and strings only (slicing a
dict or anything else is a `LangTypeError`). There is no step.

- Present bounds must be ints, else `LangTypeError`. A missing lower bound
  means 0; a missing upper bound means `len(x)`.
- A **negative** bound is a `LangIndexError` (no wraparound).
- Bounds larger than `len(x)` **clamp** to `len(x)`: `"abc"[1:99]` is
  `"bc"`.
- If (after clamping) `a > b` the result is empty (`""` or `[]`).
- An array slice returns a NEW array — a **shallow** copy: the new array
  is a different object (`a[:] == a` is `false`), but elements that are
  themselves containers are shared:

```
let inner = [1];
let outer = [inner, 2];
let copy = outer[:];
push(copy, 3);        // does not affect outer
copy[0][0] = 99;      // DOES affect inner
print(outer);         // [[99], 2]
print(copy);          // [[99], 2, 3]
```

- Slices are not assignable: `a[0:1] = [9];` is a `LangSyntaxError` (see
  assignment targets).

## Assignment and compound assignment

`target = expr;` and `target op= expr;` for `op` in `+ - * / %`.

Evaluation order is exact and graded. For a target `c[i]`:

1. evaluate the container expression `c`;
2. evaluate the index expression `i`;
3. evaluate the right-hand side;
4. *(compound only)* read the current value `c[i]` — the container type
   check, index type check, and bounds/key check all happen at this read,
   AFTER the right-hand side has been evaluated — then apply the binary
   operator with exactly the semantics and errors of the corresponding
   binary expression;
5. write.

For a plain assignment the write in step 5 performs the container/index
checks instead (still after the RHS). For a bare identifier target the
same shape holds: the RHS is fully evaluated before the variable is read
(compound) or written (plain); assigning to an undeclared variable raises
`LangNameError` only after the RHS has been evaluated.

Consequences, all graded:

```
let a = [1, 2, 3];
fn loud() { print("side effect"); return 10; }
a[9] = loud();        // prints "side effect", THEN raises LangIndexError
a[9] += loud();       // prints "side effect", THEN raises LangIndexError
```

Writing to arrays: `a[i] = v` requires `0 <= i < len(a)` — there is no
append-by-assignment; `a[len(a)] = v` is a `LangIndexError` (use
`push`). Writing to a string index is a `LangTypeError` (strings are
immutable). Writing to a dict key inserts or updates: `d["new"] = 1;` is
always legal. But compound assignment READS first:

```
let d = {};
d["n"] = 1;           // ok: insert
d["n"] += 1;          // ok: d["n"] is now 2
d["missing"] += 1;    // LangKeyError: read-before-write
```

## Variables and scoping

- `let x = expr;` declares `x` in the innermost (current) scope. Declaring
  a name that already exists *in the same scope instance* is a
  `LangNameError` at runtime.
- `x = expr;` assigns to the nearest enclosing binding of `x`, searching
  outward through the scope chain. If no binding exists, `LangNameError`.
- Reading an undeclared variable is a `LangNameError`.
- A block `{ ... }` introduces a new scope; inner `let`s shadow outer
  bindings. Every *execution* of a block creates a fresh scope instance,
  so a `let` inside a loop body is legal on every iteration.
- `fn name(...) { ... }` declares `name` in the current scope exactly like
  `let` (so redeclaring it in the same scope is a `LangNameError`).

## `for` loops

### C-style `for` — per-iteration binding

`for (let i = INIT; COND; STEP) BODY` executes as the following
pseudocode, and the per-iteration binding is graded:

```
1. Evaluate INIT; create a fresh scope E holding the single binding i = INIT.
2. Loop:
   a. Evaluate COND in E. It must be a bool (else LangTypeError);
      if false, exit the loop.
   b. Execute BODY as a block in a fresh child scope of E. Closures
      created during this iteration capture THIS iteration's binding of i.
   c. Create a fresh scope E' whose binding i is initialized to the
      current value of i in E (so body mutations of i carry over); execute
      STEP in E'; let E := E'; go to (a).
3. `break` exits the loop. `continue` jumps to step (c) — the STEP always
   runs before the next condition check.
```

The graded consequence — closures capture one binding **per iteration**,
not one shared binding:

```
let fns = [];
for (let i = 0; i < 3; i += 1) {
  fn get() { return i; }
  push(fns, get);
}
print(fns[0](), fns[1](), fns[2]());   // 0 1 2   (NOT 2 2 2)
```

The loop variable is an ordinary binding: the body may read and assign it
(`i = i + 10;` inside the body affects the following STEP), and a `let i`
inside the body is legal shadowing (the body block is a child scope).

### `for (x in e)` — live iteration

- `e` is evaluated once. It must be an array or a string; anything else
  (including a dict — iterate `keys(d)` instead) is a `LangTypeError`.
- Iteration is **live and index-based**: conceptually
  `idx = 0; while (idx < len(e)) { let x = e[idx]; BODY; idx += 1; }`.
  Mutating an array while iterating it is observable — pushing during the
  loop extends the iteration, popping shortens it:

```
let a = [1, 2, 3];
for (v in a) {
  if (v == 2) { push(a, 99); }
  print(v);
}
// prints 1, 2, 3, 99
```

- `x` is a fresh binding per iteration (closures capture per-iteration
  values, same as C-style `for`). Assigning to `x` in the body never
  writes back into the container.
- Iterating a string yields one-character strings.
- `break`/`continue` behave as in `while`.

## Functions and closures

- Functions are declared with `fn name(params) { body }` and are
  first-class: they can be passed as arguments, returned, and stored in
  variables and containers.
- The declaration binds `name` when the declaration statement executes.
  There is no hoisting: calling a function before its declaration has
  executed is a `LangNameError`. (Mutual recursion works as long as both
  declarations execute before the first call, because names are resolved
  at call time.)
- A function captures its defining environment by reference (late
  binding): mutations of captured variables are visible through every
  closure sharing them; captured variables outlive the scope that created
  them.
- Parameters are declared in the function's body scope; a top-level `let`
  in the body reusing a parameter's name is a `LangNameError`.
- `return expr;` returns a value; `return;` returns `nil`; falling off the
  end of the body returns `nil`.
- Calls: the callee must be a function value, else `LangTypeError`.
  Argument count must match the parameter count exactly, else
  `LangArityError`. Arguments are evaluated left to right.
- Recursion is supported. Graded programs may reach a call depth of
  **1,000**. A recursive tree-walking evaluator in Python typically burns
  several Python stack frames per MiniLang2 call, so the default
  `sys.getrecursionlimit()` of 1000 is NOT enough — raise it to a
  moderate value (around 20,000). Do not set it absurdly high: if your
  evaluator recurses past the real C stack, the process dies with a
  segmentation fault and you lose every remaining test, not just one.

## `try` / `catch` / `finally` / `throw`

This section is heavily graded — implement it exactly.

**What is catchable.** A `catch` clause catches (a) values thrown by
`throw`, and (b) every *runtime* error: `LangNameError`, `LangTypeError`,
`LangArityError`, `LangZeroDivError`, `LangIndexError`, `LangKeyError`,
`LangValueError`. Syntax errors are raised before execution begins and
are never catchable. MiniLang2's internal control flow (`return`,
`break`, `continue`) is NOT an error and must never be intercepted by
`catch` — a `return` inside a `try` with a `catch` simply returns
(running any `finally` on the way out).

**What `catch (e)` binds.** If a runtime language error was caught, `e`
is bound to an opaque **error value**. The only operation on an error
value is the builtin `errkind(e)`, which returns one of the strings
`"name"`, `"type"`, `"arity"`, `"zerodiv"`, `"index"`, `"key"`,
`"value"`. If a user `throw v;` was caught, `e` is bound to exactly `v`
(the original value, not wrapped — `throw "boom";` is caught as the
string `"boom"`). The catch parameter is declared in the catch block's
own scope like a function parameter: a top-level `let e = ...;` inside
`catch (e) { ... }` is a `LangNameError`.

**Rethrow.** `throw x;` where `x` is an error value re-raises the
*original* error: it is catchable again (yielding the same error value
semantics), and if it reaches the top level, `run` raises the original
class (`LangZeroDivError`, etc.) — not `LangThrownError`.

**Uncaught throws.** A `throw` of any non-error value that reaches the
top level makes `run` raise `LangThrownError`.

**`finally` semantics — the pending-outcome rule.** After the `try` block
(and the `catch` block, if it ran) produce an outcome — normal
completion, `return v`, `break`, `continue`, or a propagating
throw/error — the `finally` block (if present) runs. If the `finally`
block completes normally, the pending outcome then resumes. If the
`finally` block itself exits via `return`/`break`/`continue`/`throw` (or
a runtime error), that new outcome **replaces** the pending one, which is
silently discarded. Worked examples, all graded:

```
fn f() {
  try { return 1; } finally { return 2; }
}
print(f());                       // 2

fn g() {
  let log = [];
  while (true) {
    try { break; } finally { push(log, "f"); }
  }
  return log;
}
print(g());                       // ["f"]   (finally ran before break took effect)

fn h() {
  try { throw "boom"; } finally { return "saved"; }
}
print(h());                       // saved   (pending throw discarded)

fn k() {
  let i = 0;
  while (i < 3) {
    i += 1;
    try { throw "x"; } finally { continue; }   // continue discards the throw
  }
  return i;
}
print(k());                       // 3
```

Further graded rules:

- If the `catch` block itself throws or raises a runtime error, the
  `finally` still runs, then the new error propagates (unless the
  `finally` replaces it).
- A `try` with `finally` but no `catch` runs the `finally`, then the
  original error continues to propagate.
- Throws unwind across function calls; when unwinding passes multiple
  `try` statements, their `finally` blocks run innermost-first.
- `errkind` of anything that is not an error value is a `LangTypeError`.
- Error values are ordinary values otherwise: storable, passable,
  comparable (identity), rethrowable. `str`/`print`/`len` of an error
  value is a `LangTypeError`.

## Built-in functions

Eleven builtins are pre-bound in an outer scope that encloses the global
scope. They are ordinary function values. Because they live in an *outer*
scope, `let print = 5;` at the top level is legal shadowing, not a
redeclaration error.

| Builtin | Arity | Semantics |
|---|---|---|
| `print(v, ...)` | any (including zero) | Converts each argument using the display rules below, joins them with a single space, and appends the result to the output as ONE list element. `print()` appends `""`. A string argument containing `\n` still produces one list element — elements are split per print call, never per newline. |
| `str(v)` | 1 | The display conversion below, returned as a string. |
| `len(x)` | 1 | Length of a string (characters), array (elements), or dict (keys). Anything else → `LangTypeError`. |
| `push(a, v)` | 2 | Appends `v` to array `a`, returns `nil`. `a` must be an array, else `LangTypeError`. |
| `pop(a)` | 1 | Removes and returns the LAST element of array `a`. Empty array → `LangValueError`. Non-array → `LangTypeError`. |
| `keys(d)` | 1 | Returns a NEW array of `d`'s keys in insertion order (mutating the returned array does not affect `d`). Non-dict → `LangTypeError`. |
| `has(d, k)` | 2 | `true` if string key `k` is present in dict `d`. `d` must be a dict and `k` a string, else `LangTypeError`. |
| `remove(d, k)` | 2 | Removes key `k` from dict `d` and returns the removed value. Missing key → `LangKeyError`. Type errors as for `has`. |
| `ord(s)` | 1 | Code point of a one-character string. Non-string → `LangTypeError`; a string whose length is not exactly 1 → `LangValueError`. |
| `chr(n)` | 1 | One-character string for code point `n`. Non-int → `LangTypeError`; `n` outside `0..1114111` → `LangValueError`. |
| `errkind(e)` | 1 | Kind string of an error value (see try/catch). Non-error-value → `LangTypeError`. |

Wrong argument counts for any fixed-arity builtin are `LangArityError`s.

**Dict insertion order** is observable through `keys` and display, and is
graded: updating an existing key keeps its position; `remove` then
re-insert moves the key to the end.

## Display rules (`str` and `print`)

Top level (a value passed directly to `str` or `print`):

- int → decimal digits (`"42"`, `"-7"`); bool → `"true"`/`"false"`;
  nil → `"nil"`; string → **unchanged, bare** (no quotes);
  array/dict → container form below;
  function or error value → `LangTypeError`.

Container form (a value nested inside an array or dict being displayed):

- Arrays: `[` + elements `", "`-separated + `]`; empty is `[]`.
- Dicts: `{` + `"key": value` entries `", "`-separated, insertion order +
  `}`; empty is `{}`. Keys are always double-quoted.
- **Nested strings are double-quoted, with exactly the four escapes
  re-escaped** (`\\`, `\"`, `\n`, `\t` — and nothing else escaped):
  `print(["a\nb"]);` prints the seven characters `["a\nb"]` — a literal
  backslash and `n`, not a newline. (This is NOT Python `repr`, which
  would use single quotes.)
- ints, bools, nil nested in containers render as at top level.
- A function or error value ANYWHERE inside a displayed container is a
  `LangTypeError`.

Worked example:

```
print({"xs": [1, "a\tb"], "empty": []});
// prints: {"xs": [1, "a\tb"], "empty": []}
// (one list element containing a literal backslash followed by t —
//  NOT a tab character)
print("a\tb");
// prints a TAB between a and b (top-level strings are bare)
```

## Error taxonomy summary

| Exception | Raised for |
|---|---|
| `LangSyntaxError` | Any lexing or parsing failure: bad characters, bad escapes, unterminated strings, missing `;`/braces/parens, keyword used as identifier, trailing comma, `=` in an expression, invalid assignment target (call/slice/literal), duplicate parameter, duplicate dict-literal key, non-string dict-literal key, misplaced `return`/`break`/`continue`, `try` without catch/finally, `throw` without expression. Always raised before execution begins. |
| `LangNameError` | Reading or assigning an undeclared variable; declaring (`let`, `fn`, parameter, catch parameter) a name already present in the same scope instance. |
| `LangTypeError` | Wrong operand type for any operator; non-bool condition (if/while/for/ternary) or logic operand; calling a non-function; indexing/slicing a non-indexable value; wrong index type (`a[true]`, `d[1]`); writing to a string index; `str`/`print` of a function or error value (directly or nested); `len`/`push`/`pop`/`keys`/`has`/`remove`/`ord`/`chr`/`errkind` type violations; `for (x in e)` over a non-array/string. |
| `LangArityError` | Calling any function (user-defined or builtin) with the wrong number of arguments. |
| `LangZeroDivError` | `/` or `%` with a zero right operand (also via `/=`, `%=`). |
| `LangIndexError` | Array/string index out of range, including ALL negative indices; negative slice bound; `a[len(a)] = v`. |
| `LangKeyError` | Reading, compound-assigning, or `remove`-ing a dict key that is not present. |
| `LangValueError` | `pop` of an empty array; negative exponent for `**`; `chr` code point out of range; `ord` of a string whose length ≠ 1. |
| `LangThrownError` | A user `throw` of a non-error value escaping the whole program. Raised only by `run` at the top level, never observable in-language. |

All are subclasses of `LangError`. Runtime errors are catchable with
`try`/`catch`; syntax errors are not.

## Error positions

Every `LangError` carries 1-based `e.line` and `e.col`. The following
anchors are graded exactly; each comes with a worked example. (For any
error not listed here the attributes must exist but their values are
implementation-defined.)

Syntax errors:

| Error | Anchor | Example |
|---|---|---|
| Unexpected character | that character | `let x = 1 @ 2;` → line 1, col 11 (the `@`) |
| Unterminated string | the opening `"` | `let s = "abc;` → line 1, col 9 |
| Invalid escape | the backslash | `let s = "ab\qcd";` → line 1, col 12 |
| Keyword used as identifier | the keyword token | `let while = 1;` → line 1, col 5 |
| Missing `;` (another token found where `;` was expected) | that token | `let a = 1 let b = 2;` → line 1, col 11 (the second `let`) |

Runtime errors:

| Error | Anchor | Example |
|---|---|---|
| Binary operator type error or `LangZeroDivError` | the operator token | `let x = 1 +\n"a";` → line 1, col 11 (the `+`); `print(1 / 0);` → col 9 |
| `LangArityError`, or calling a non-function | the `(` of that call | `fn f(a) { return a; }\nf(1, 2);` → line 2, col 2 |
| `LangIndexError` or `LangKeyError` | the `[` of that index | `let a = [1];\nprint(a[5]);` → line 2, col 8 |
| Undefined variable (read or assign) | the identifier token | `print(  missing);` → line 1, col 9 |

Multi-line note: positions refer to the line/column where the anchor
token STARTS. Newlines inside the program shift subsequent lines exactly
as you'd expect; there are graded multi-line cases.

## Performance requirements

These are requirements, not suggestions — the graded suite runs each
program under a hard per-test watchdog, and the following workloads must
each complete in about 1 second on modest hardware (the watchdog allows
a few seconds of slack, but an implementation that is 5× slower than a
plain tree-walker will fail these tests):

- A `while` loop of **200,000** iterations doing a few arithmetic
  operations and assignments per iteration.
- **100,000** function calls (a small function called in a loop).
- Reading a variable through ~30 levels of nested block scope,
  ~50,000 times.
- Building an array of **100,000** elements with `push`, then summing it
  with `for (v in a)`. (`push` must be amortized O(1); a copy-on-push
  array is O(n²) and will time out.)
- **30,000** iterations each performing a `throw` caught by a
  `try`/`catch` in the loop body.
- Accumulating a ~50,000-character string with repeated `+` of small
  chunks.

A straightforward tree-walking interpreter passes all of these
comfortably IF you avoid gratuitous inefficiency: parse once (never
re-tokenize/re-parse inside the evaluation loop), keep environment
lookup a simple chain walk over dicts, keep values as plain Python
objects, and don't deep-copy anything you don't have to.

Other grading guarantees: call depth ≤ 1,000; no graded program builds
cyclic containers (you need not handle printing a container that
contains itself); no graded program relies on garbage collection
behavior.

## Not in the language

There are no floats, no anonymous functions (`fn` is always a named
declaration), no `+` on arrays, no array/dict equality by value, no
string ordering (`"a" < "b"` is a `LangTypeError`), no negative or
stepped slices, no `+=` on slices, no increment/decrement operators, no
bitwise operators, no `for`-loop clause omission, no user-defined
exception classes, and no I/O besides `print`.

## Implementation constraints

- Python 3.10+, standard library only.
- Write the interpreter yourself: do not use `eval`, `exec`, `compile`,
  the `ast` module, or any parser-generator shortcuts.
- `run` must be self-contained per call: no global mutable state may leak
  between calls.

Write your own unit tests in `test_interp.py`. A reasonable self-test
checklist (the graded suite is finer-grained than this):

- Every value type through `print`/`str`, including nested container
  display and its escaping.
- Operator precedence and associativity, including `?:` and `**`.
- Truncating division/modulo sign cases.
- Indexing, slicing, clamping, and every index/slice error case.
- Reference semantics and shallow-copy slices.
- Compound assignment evaluation order (side effects before the error).
- Per-iteration `for` bindings observed through closures; live `for-in`.
- Every rule in the try/catch/finally section — especially the four
  worked examples.
- Every error class with at least two distinct triggers.
- The graded position anchors, including a multi-line case.
- Each builtin's happy path, type errors, and arity errors.
- The performance workloads above, timed.

File layout (required):
- Put the implementation in `interp.py` in the current working directory.
- Put your unit tests in `test_interp.py`.
- Put the design explanation, edge-case notes, and complexity analysis in
  `NOTES.md`.
