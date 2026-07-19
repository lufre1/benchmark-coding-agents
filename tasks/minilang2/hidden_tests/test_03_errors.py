"""T2: error taxonomy and graded position anchors. 29 cases."""

import pytest

from _harness import expect_error, run


# -- graded position anchors (9) ----------------------------------------------
# Anchors per the spec's Error positions table, with fresh literals.

@pytest.mark.parametrize("src,err,line,col", [
    # unexpected character -> that character
    ("let q = 4 $ 7;", "LangSyntaxError", 1, 11),
    # unexpected character, multi-line ('&' alone is not an operator)
    ("let ok = 1;\nlet bad = 2 & 3;", "LangSyntaxError", 2, 13),
    # unterminated string -> the opening quote
    ('let msg = "oops;', "LangSyntaxError", 1, 11),
    # invalid escape -> the backslash
    ('let a = 1;\nlet s = "xy\\wz";', "LangSyntaxError", 2, 12),
    # keyword used as identifier -> the keyword token
    ("fn try() { return 1; }", "LangSyntaxError", 1, 4),
    # missing ';' -> the token found where ';' was expected
    ("let p = 2\nprint(p);", "LangSyntaxError", 2, 1),
], ids=["unexpected-char", "unexpected-char-line2", "unterminated",
        "bad-escape-line2", "kw-as-ident", "missing-semi"])
def test_syntax_positions(src, err, line, col):
    expect_error(src, err, line=line, col=col)


@pytest.mark.parametrize("src,err,line,col", [
    # binary operator error -> the operator token
    ("let y = 2 *\ntrue;", "LangTypeError", 1, 11),
    # arity error -> the '(' of the call
    ('len("a", "b");', "LangArityError", 1, 4),
    # index error -> the '[' of the index (multi-line)
    ("let xs = [1, 2, 3];\nlet z = xs[\n  7\n];", "LangIndexError", 2, 11),
], ids=["binop-anchor", "arity-anchor", "index-anchor-multiline"])
def test_runtime_positions(src, err, line, col):
    expect_error(src, err, line=line, col=col)


# -- LangSyntaxError triggers (6) ----------------------------------------------

@pytest.mark.parametrize("src", [
    "if (true) print(1);",           # braces mandatory
    "print(2,);",                    # trailing comma
    "let x = 0; print(x = 1);",      # assignment inside expression
    "return 3;",                     # return outside function
    "if (true) { continue; }",       # continue outside loop
    "while (true) { fn f() { break; } }",  # break across fn boundary
], ids=["unbraced-if", "trailing-comma", "assign-in-expr", "return-toplevel",
        "continue-outside", "break-across-fn"])
def test_syntax_errors(src):
    expect_error(src, "LangSyntaxError")


# -- LangNameError (2) ----------------------------------------------------------

@pytest.mark.parametrize("src", [
    "ghost = 1;",                              # assign to undeclared
    "fn dup() { return 1; } fn dup() { return 2; }",  # fn redeclaration
], ids=["assign-undeclared", "fn-redeclare"])
def test_name_errors(src):
    expect_error(src, "LangNameError")


# -- LangTypeError (3) -----------------------------------------------------------

@pytest.mark.parametrize("src", [
    'print(3 + "3");',
    'print("aa" < "ab");',
    "let n = 7; n(2);",
], ids=["plus-mixed", "string-order", "call-int"])
def test_type_errors(src):
    expect_error(src, "LangTypeError")


# -- LangArityError (2) ----------------------------------------------------------

@pytest.mark.parametrize("src", [
    "fn two(a, b) { return a; } two(1);",
    "fn zero() { return 1; } zero(5, 6);",
], ids=["too-few", "too-many"])
def test_arity_errors(src):
    expect_error(src, "LangArityError")


# -- LangZeroDivError via compound assignment (1) ---------------------------------

def test_zerodiv_compound():
    expect_error("let x = 5; x %= 0;", "LangZeroDivError")


# -- LangIndexError (2) ------------------------------------------------------------

@pytest.mark.parametrize("src", [
    'let s = "abc"; print(s[3]);',
    "let a = [1, 2]; a[2] = 9;",     # no append-by-assignment
], ids=["string-oob", "write-oob"])
def test_index_errors(src):
    expect_error(src, "LangIndexError")


# -- LangKeyError (1) ---------------------------------------------------------------

def test_key_error_read():
    expect_error('let d = {"a": 1}; print(d["b"]);', "LangKeyError")


# -- LangValueError (2) --------------------------------------------------------------

@pytest.mark.parametrize("src", [
    "pop([]);",
    "print(chr(0 - 1));",
], ids=["pop-empty", "chr-negative"])
def test_value_errors(src):
    expect_error(src, "LangValueError")


# -- LangThrownError (1) ---------------------------------------------------------------

def test_thrown_error_top_level():
    expect_error('throw 41;', "LangThrownError")
