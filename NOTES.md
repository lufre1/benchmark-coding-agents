# MiniLang2 Interpreter — Design and Implementation Notes

## Architecture

The interpreter is a classic tree-walking design with three phases:

1. **Tokenizer** (`tokenize`): Linear scan producing a list of `(kind, value, line, col)` tuples. Uses maximal munch (two-char ops checked before single-char). Tracks 1-based line/col for every token.

2. **Recursive-descent parser** (`Parser`): Produces an AST as nested tuples tagged by the first element. Each node carries a `pos` tuple `(line, col)` representing the error-anchor token for that sub-expression/statement. Operator precedence is encoded in the parsing methods (lowest to highest: ternary, `||`, `&&`, `==`/`!=`, `<`/`<=`/`>`/`>=`, `+`/`-`, `*`/`/`/`%`, unary, `**`, postfix).

3. **Evaluator** (`_eval`/`_exec`): Walks the AST, using an `Env` chain for scoping. Internal control flow (`_Return`, `_Break`, `_Continue`) is implemented as Python exceptions to naturally unwind through the call stack and `try`/`finally` blocks.

## Key Design Decisions

### Error Position Tracking

Every `LangError` subclass constructor accepts `line` and `col` (1-based). The `_stamp(exc, pos)` helper fills in a missing position — deeper (more specific) error anchors take precedence over higher-level ones. This allows the evaluator to raise type errors at the operator position while the parser can raise syntax errors at the specific offending token.

### Source Position Anchors

Graded anchors per the spec:

| Error | Anchor |
|---|---|
| Syntax: unexpected char | that character position |
| Syntax: unterminated string | opening `"` position |
| Syntax: invalid escape | the backslash position |
| Syntax: keyword as identifier | the keyword token position |
| Syntax: missing `;` | the token found where `;` expected |
| Runtime: binary op type/zerodiv | the operator token |
| Runtime: arity/call-non-function | the `(` of the call |
| Runtime: index/key error | the `[` of the index |
| Runtime: undefined variable | the identifier token |

### For-loop Per-iteration Bindings

The C-style `for` creates a fresh scope `env_i` for the loop variable. On each iteration:
1. Body executes in a child scope of `env_i` (capturing `env_i` for closures).
2. After the body (or `continue`), a new `env = Env(outer)` is created with just the loop variable's current value copied in.
3. The step assignment runs in this new env.
4. `env_i` is replaced with the new env for the next iteration.

This ensures closures created in iteration `i` close over that iteration's binding, not a shared one.

The `for-in` variant creates a fresh per-iteration `ienv` with the element bound as the loop variable, also ensuring per-iteration capture.

### Try/Catch/Finally

The pending-outcome rule is implemented in `_exec_try`:
- The `try` block runs; any outcome (normal, `_Return`, `_Break`, `_Continue`, error, or `_Thrown`) is stored as `pending`.
- If a `catch` clause exists and the pending outcome is a catchable error/throw, the `catch` block runs (possibly replacing the outcome).
- The `finally` block (if present) always runs in its own scope. Its outcome replaces any pending outcome.
- The final pending outcome is raised.

### Rethrow

`throw` on an `ErrorValue` re-raises the *original* exception (stored as `exc`). This preserves the original error class so a rethrown `LangIndexError` propagates as `LangIndexError`, not `LangThrownError`.

### Truncating Division and Modulo

Match C/Java semantics (truncation toward zero). Python's `//` floors toward negative infinity, so we compute:

```python
q = abs(l) // abs(r)
if (l < 0) != (r < 0):
    q = -q
```

For modulo: `a % b = a - (a / b) * b`, which with truncating division matches the sign of the dividend.

### Bool vs Int

Python's `bool` is a subclass of `int`, but MiniLang2 explicitly distinguishes them. The `_is_int(v)` helper checks `isinstance(v, int) and not isinstance(v, bool)`.

### Display Rules

- Top-level strings are bare (no quotes).
- Nested strings inside containers are double-quoted with `\\`, `\"`, `\n`, `\t` re-escaped.
- Functions and error values cannot be displayed (raise `LangTypeError`).
- Dict display preserves insertion order.

### Recursion Limit

`sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))` — the default 1000 is insufficient for the graded 1000-call-depth tests (each MiniLang2 call burns multiple Python frames). 20000 is safe against segfaults on CPython 3.10.

## Complexity Analysis

| Operation | Complexity |
|---|---|
| Tokenization | O(n) source chars |
| Parsing | O(t) tokens (recursive descent is linear) |
| Variable lookup | O(d) where d is scope chain depth |
| Variable assignment | O(d) where d is scope chain depth |
| Binary `+`/`-`/`*`/`**` | O(1) (Python big-int arithmetic) |
| String concatenation | O(k) per `+`, can be O(n²) overall (as specified) |
| Array `push` | Amortized O(1) (Python list append) |
| Array `pop` | O(1) |
| Dict operations | O(1) average |
| `for (x in e)` | O(n) where n is final container length (live iteration) |
| `for (let i=...; ...; ...)` | O(n) iterations |
| `try`/`catch` | O(1) overhead in absence of control flow |
| `_exec`/`_eval` dispatch | O(1) per AST node (dict lookup) |
| Closure capture | O(1) (env reference, no copying) |

## Edge Cases

- `0 ** 0` returns 1 (per spec).
- Negative exponent for `**` raises `LangValueError`.
- Negative slice bounds raise `LangIndexError` (no wraparound).
- `-3 ** 2` parses as `-(3 ** 2)` = `-9` (unary binds less tightly than `**`).
- `a[len(a)] = v` is a `LangIndexError` (no append-by-assignment).
- `d["missing"] += 1` is a `LangKeyError` (read-before-write in compound assignment).
- `pop([])` is a `LangValueError`.
- `break`/`continue` across `fn` boundary is a parse-time error.
- `try` without `catch` or `finally` is a parse-time error.
- Dict literal keys must be string literals only (parse-time).
- Dict literal duplicate keys are parse-time errors.
- Assignment inside expression (`print(x = 1)`) is parse-time error.
- `for` step creates a fresh scope per iteration with only the loop variable: the step `i += 1` cannot mutate outer scope bindings directly.
- `for-in` with live iteration: the container is evaluated once; `len(container)` is checked each iteration (index-based), so mutations (push/pop) during iteration are observable.
- `for-in` loop variable is a fresh binding per iteration (no writeback to container).
- `throw` of an `ErrorValue` re-raises the original error class (not `LangThrownError`).
- `catch` does NOT intercept `return`, `break`, or `continue` — these propagate past the catch clause.
- `finally` always runs, and its outcome (return/break/continue/throw/error) replaces any pending outcome.
- Dict insertion order is preserved: updating an existing key keeps its position; `remove` + re-insert moves key to end.
- Slices are shallow copies: elements that are containers are shared between original and copy.
- Identity equality (`==`) for arrays, dicts, functions, and error values compares by identity, not value.
- Bool is NOT int: `true + 1` is `LangTypeError`, `true == 1` is `false`, `a[true]` is `LangTypeError`.
- String ordering is `LangTypeError`: `"a" < "b"` is not allowed.
- Dict reading with non-string key is `LangTypeError`.
- All negative indices (including slice bounds) raise `LangIndexError`; no Python-style wraparound.
- Slice bounds larger than `len(x)` clamp to `len(x)`; if `lo > hi` after clamping, result is empty.
- Assignment targets must be an identifier or an index chain (`a[i][j]`); call results and slices are invalid.
- Compound assignment on dict: the read step checks key existence even though the write step would insert.
