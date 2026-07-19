# MiniLang Interpreter — Design Notes

## Architecture

The interpreter follows a classic three-phase pipeline:

```
source → tokenizer → tokens → parser → AST → evaluator → output
```

All phases are implemented in a single file (`interp.py`) with no external
dependencies. Each call to `run()` is self-contained (fresh token list, fresh
parser, fresh environment) — no global state leaks between calls.

## Phase 1: Tokenizer

Single-pass iterative scanner over the source string. Produces a flat list of
`(kind, value)` tuples. Token kinds are `int`, `string`, `ident`, `kw`, `op`,
and `eof`.

Key design decisions:
- **Maximal munch**: two-character operators (`<=`, `>=`, `==`, `!=`, `&&`, `||`)
  are checked before single-character operators.
- **String escapes**: a dictionary maps escape sequences to their target
  characters. Unknown escapes, unterminated strings, and raw newlines within
  string literals raise `LangSyntaxError`.
- **Comments**: `//` discards everything to end-of-line. Only detected when
  not inside a string literal (the tokenizer never re-enters character classes
  once inside a string).
- **Keywords**: a set used on each identifier to classify it as `kw` or `ident`.
  Keywords are reserved and cannot be used as identifiers.

Complexity: O(n) where n = source length.

## Phase 2: Recursive-Descent Parser

Takes the token list, produces an AST as nested tuples. The first element of
each tuple is a symbol tag.

### AST node tags

| Tag | Structure | Role |
|---|---|---|
| `let` | `("let", name, expr)` | Variable declaration |
| `assign` | `("assign", name, expr)` | Variable assignment |
| `fn` | `("fn", name, params[], body[])` | Function declaration |
| `if` | `("if", cond, then, else_or_none)` | Conditional |
| `while` | `("while", cond, body[])` | Loop |
| `return` | `("return", expr_or_None)` | Return statement |
| `break` | `("break",)` | Break statement |
| `continue` | `("continue",)` | Continue statement |
| `block` | `("block", stmts[])` | Block scope |
| `expr` | `("expr", expr)` | Expression statement |
| `lit` | `("lit", value)` | Literal (int, string, bool, nil) |
| `var` | `("var", name)` | Variable reference |
| `bin` | `("bin", op, l, r)` | Binary operator |
| `and` | `("and", l, r)` | Logical AND (short-circuit) |
| `or` | `("or", l, r)` | Logical OR (short-circuit) |
| `un` | `("un", op, e)` | Unary operator |
| `call` | `("call", callee, args[])` | Function call |

### Grammar handling

The parser tracks two counters:
- `fn_depth`: how many function declarations deep (for `return` placement)
- `loop_depth`: how many loops deep (for `break`/`continue` placement)

When entering a function body (`fn_decl`), `loop_depth` is saved and reset
to 0, because `break`/`continue` must not cross function boundaries. This is
restored on exit.

### Statement disambiguation

Assignment (`IDENT = expr;`) is detected by peeking ahead: if the current
token is an `ident` and the next is `op("=")`, this is an assign statement.
Otherwise, it falls through to expression-statement (which would produce
`LangSyntaxError` if `=` appears inside an expression, since `=` is not a
valid operator at any precedence level).

### Parse-time errors

All syntax errors (misplaced `return`/`break`/`continue`, bad characters,
string errors, missing semicolons, duplicate params, no-brace `if`/`while`,
keyword-as-identifier, trailing commas, `=` in expression) are raised during
parsing, before any statement executes.

Complexity: O(n) where n = token count.

## Phase 3: Tree-Walking Evaluator

### Environment chain (`Env`)

Each `Env` holds a `vars` dict and a `parent` pointer. Scopes form a linked
list from the innermost scope outward:
- `declare(name, value)` → adds to `self.vars` only; `LangNameError` if
  the name is already in `self.vars`.
- `get(name)` → walks the chain; `LangNameError` if not found.
- `assign(name, value)` → walks the chain; `LangNameError` if not found.

### Values

MiniLang has five types, represented as Python values:
- `int` → Python `int`, checked with `isinstance(v, int) and not isinstance(v, bool)`
- `bool` → Python `bool`
- `string` → Python `str`
- `nil` → Python `None`
- function → `Function` object (name, params, body, closure env)

Python's `bool` is a subclass of `int`, so the `_is_int` helper enforces the
distinction: `_is_int(True)` is `False`.

### Closures

When a `Function` is created, it captures the current `Env` as its `closure`.
At call time, a new `Env` is created with `closure` as parent. This gives:
- **Late binding**: variable lookups walk the closure chain, so mutations
  to captured variables are visible.
- **Independent instances**: each function call creates a fresh chain.
- **Shared capture**: closures created in the same scope share the same `Env`,
  so mutations through one are visible through all.

### Truncating division and modulo

Python's `//` floors toward negative infinity, but MiniLang requires truncation
toward zero. The implementation:
1. Computes `abs(l) // abs(r)` (positive quotient)
2. Negates if signs differ (for trunc-toward-zero)
3. Modulo = `l - q * r` (satisfies `a == (a/b)*b + a%b`)

### Control flow via exceptions

Control flow signals use Python exceptions to unwind the evaluator stack:
- `_Return(value)` — caught in `_call()`, returns the value (or None)
- `_Break` — caught in `_exec("while")`, exits the loop
- `_Continue` — caught in `_exec("while")`, continues the loop

This avoids threading a control-flow flag through every `_exec`/`_eval` call.

### Short-circuit evaluation

`&&` and `||` are handled with explicit tags (`"and"`/`"or"`) in the AST,
distinct from `"bin"`. The evaluator only evaluates the right operand when
necessary:
- `&&`: if left is `false`, return `false` immediately (skip right eval)
- `||`: if left is `true`, return `true` immediately (skip right eval)
- The right operand is type-checked only if evaluated.

### Built-in functions

Three `Builtin` objects are created in an env above the global scope:
- `print(args)`: variadic; converts each arg via `_display`, joins with space,
  appends to output list.
- `str(args)`: arity 1; converts arg via `_display`.
- `len(args)`: arity 1; returns `len()` of a string arg.

Because builtins live in a parent env, `let print = 5;` at the top level
creates a new binding in the global `Env` that shadows the outer one, without
triggering a redeclaration error.

Complexity: O(n) per `_eval`/`_exec` call. Each environment chain lookup is
O(d) where d = scope depth. Overall O(program size) for a straight-line
program, O(iterations × body size) for loops.

## Edge Cases

| Case | Handling |
|---|---|
| `bool is int` in Python | `_is_int` checks `not isinstance(v, bool)` |
| `true == 1` | Different types → `False`, no error |
| `false && 5` (type error in RHS) | Short-circuit: never evaluate RHS, return `false` |
| `1 < 2 < 3` | Parsed as `(1 < 2) < 3`; `1 < 2` is bool, so `< 3` fails |
| `fn f() { }` func identity | compared by `is` (reference equality) |
| `break` inside nested `fn` inside loop | Parse-time: fn body resets loop_depth to 0 |
| `let x = 1; let x = 2;` | Runtime redeclaration error |
| `fn f(a) { let a = 2; }` | Parameter `a` declared in body scope, `let a` redeclares |
| Builtin shadowing | Builtins in outer env; global `Env` parented to builtin `Env` |
| `print()` | Variadic builtin with arity=None; produces `[""]` |
| `007` | Lexed as digits → `int("007")` → Python int 7 |
| Empty program | `parse_program()` returns `[]`; `run()` returns `[]` |
| `return;` vs `return expr;` | `return_stmt` uses `match_op(";")` to decide |
