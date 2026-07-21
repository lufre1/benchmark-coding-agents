# MiniLang2 Interpreter — Design Notes

## Architecture

The interpreter is a classic three-stage pipeline:

1. **Tokenizer** (`tokenize`) — reads source text, emits a flat list of tokens.
2. **Parser** (`Parser`) — recursive-descent, one-token lookahead, produces an AST.
3. **Evaluator** (`_eval`/`_exec`) — tree-walking, operates on plain Python objects.

## Tokenizer

- Maximal munch: two-character operators (`<=`, `**`, `+=`, etc.) are matched before single-character ones.
- String literals are scanned inline with a table of valid escapes (`\\`, `\"`, `\n`, `\t`); any other escape, unterminated string, or raw newline → `LangSyntaxError`.
- Comments (`//` to end of line) are skipped during tokenization; `//` inside a string literal is not a comment.
- Source positions (line, col) are tracked as 1-based integers during scanning.

## Parser

Recursive-descent parser following the grammar exactly. Key design decisions:

- **Statement/expression split**: Assignment (`=`, `+=`, etc.) is a statement-level construct, never parsed inside an expression. The `expr_or_assign_stmt` method parses an expression, then checks if the next token is an assignment operator.
- **Assignment target validation**: After parsing the target expression, `_validate_target` checks it is a `var` or `index` node. Function calls, slices, parenthesized expressions, and literals are rejected.
- **Right-associativity**: `**` parses its right operand with `unary` (which includes `power` in its chain); `?:` parses the middle and right operands with recursive calls to `ternary`.
- **Braces in statement vs expression position**: `{` in statement position calls `self.block()`, which expects `}` only after parsing statements. In expression position (via `primary`), `{` starts a dict literal. The distinction emerges naturally from the grammar: `primary` is only reached from expression parsing.
- **`break`/`continue` guards**: The parser tracks `loop_depth` (incremented for `while`, `for`, `forin`, reset to 0 inside `fn` bodies) to detect `break`/`continue` outside a loop within the same function at parse time.
- **`return` guard**: `fn_depth` is tracked; `return` outside a function is a parse error.
- **Duplicate detection**: Duplicate parameter names and duplicate dict literal keys are detected during parsing and raise `LangSyntaxError`.

## Evaluator

### Values

All MiniLang2 values are plain Python objects:
- `int` ← Python `int` (but `bool` is checked with `isinstance(v, bool)` to distinguish from int)
- `bool` ← Python `bool`
- `string` ← Python `str`
- `nil` ← `None`
- `function` ← `Function` (closure: params + body AST + environment)
- `builtin function` ← `Builtin` (name + Python callable + arity)
- `array` ← Python `list`
- `dict` ← Python `dict` (which preserves insertion order since Python 3.7)
- `error` ← `ErrorValue` (kind string + original exception)

Type identity tests use `_type_name()` which explicitly checks `bool` before `int`.

### Environment chain

`Env` objects form a linked list (`parent` pointer). Each scope instance is a separate `Env` with its own `vars` dict:

- `get(name)` walks the chain upward
- `assign(name, value)` walks the chain upward looking for an existing binding
- `declare(name, value)` adds to the current scope (raises `LangNameError` if already present)

Builtins live in an `Env` at the bottom of the chain (outermost scope), so top-level `let print = 5;` shadows without redeclaration error.

### Control flow signals

Python exceptions are used for internal control flow:

- `_Return(value)` — function return
- `_Break()` — break from loop
- `_Continue()` — continue loop
- `_Thrown(value, pos)` — uncaught user throw

These are `BaseException` subclasses (via inheriting from `Exception`) that are never caught by `try`/`catch` in the language — only by the loop machinery, function call machinery, and the `finally` handler.

### For loops — per-iteration binding

C-style `for (let i = INIT; COND; STEP) BODY`:

1. A fresh `Env` `E` is created with `i` declared to the evaluated INIT.
2. Each iteration: COND is evaluated in `E`; BODY runs in a child scope of `E`; a new `Env` `E'` is created (parent = outer scope of the loop, not `E`) with `i` initialized to `E.vars['i']`, then STEP runs in `E'`. `E'` becomes `E` for the next iteration.
3. This ensures closures created in each iteration capture that iteration's binding of `i` (the `Env` object) via `E`.

For-in `for (x in e)`:
1. `e` is evaluated once.
2. Iteration is index-based: `idx = 0; while idx < len(container): { let x = container[idx]; BODY; idx += 1; }`.
3. Each iteration creates a fresh `Env` for `x`, so closures capture per-iteration values.
4. `break`/`continue` behave as in `while`.

### Try/Catch/Finally

The `_exec_try` function implements the pending-outcome rule:

1. The `try` block executes.
2. If it raises `_Thrown` or `LangError`, the `catch` handler (if present) runs; the result (None for normal, or the exception/signal) becomes the "pending" outcome.
3. Any `_Return`/`_Break`/`_Continue` from the `try` block becomes the pending outcome (catch does NOT intercept these).
4. If `finally` is present, it always runs.
5. If `finally` completes normally, the pending outcome is re-raised.
6. If `finally` exits via `return`/`break`/`continue`/`throw`/error, that replaces the pending outcome.

Error values (`ErrorValue`) wrap caught runtime errors; `errkind` maps to the kind string. Rethrowing an `ErrorValue` raises the original exception (not `LangThrownError`).

### Display rules

- Top-level: int→str, bool→"true"/"false", nil→"nil", string→bare, array→`[e, ...]`, dict→`{k: v, ...}`.
- Nested: strings get double-quoted with four escapes re-escaped (`\\`, `\"`, `\n`, `\t`).
- Function or error value anywhere in display → `LangTypeError`.

## Error positions

Error anchor positions are propagated through the AST:
- Binary operator errors: the operator token position is stored in the AST node.
- Call errors (`LangArityError`, calling a non-function): the `(` position.
- Index/key errors: the `[` position.
- Undefined variable: the identifier token position.
- Syntax errors: positions of the offending token.

All positions are 1-based (line, col).

## Performance considerations

- Single pass tokenization, single pass parsing, tree-walking evaluation — never retokenize or reparse.
- Environment lookup is a simple linked-list walk: O(depth) per access.
- No deep copying of values; arrays/dicts are Python lists/dicts with reference semantics.
- `sys.setrecursionlimit` is raised to 20000 at the start of `run` to handle 1000-level recursive MiniLang2 calls (each MiniLang2 call uses several Python stack frames).
- Arithmetic operations, comparison, and control flow are all O(1) Python operations.
