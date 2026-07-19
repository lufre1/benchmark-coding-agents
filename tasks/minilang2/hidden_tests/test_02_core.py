"""T1 core: v1-level semantics every viable submission should pass. 48 cases."""

import math

import pytest

from _harness import expect_error, run


# -- literals and print (6) --------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ("print(31);", ["31"]),
    ("print(0052);", ["52"]),
    ("print(true, false, nil);", ["true false nil"]),
    ('print(9, "q", true);', ["9 q true"]),
    ("print();", [""]),
    ('print(4); print("two");', ["4", "two"]),
], ids=["int", "leading-zeros", "bool-nil", "join", "empty", "two-calls"])
def test_print(src, expected):
    assert run(src) == expected


# -- string escapes (4) ------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    (r'print("x\ty");', ["x\ty"]),
    (r'print("say \"yo\"");', ['say "yo"']),
    (r'print("back\\slash");', ["back\\slash"]),
    (r'print("p\nq"); print("r");', ["p\nq", "r"]),
], ids=["tab", "quote", "backslash", "newline-one-element"])
def test_escapes(src, expected):
    assert run(src) == expected


# -- arithmetic (6) ----------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ("print(3 + 4 * 5);", ["23"]),
    ("print(30 - 8 / 2);", ["26"]),
    ("print((3 + 4) * 5);", ["35"]),
    ("print(- -6);", ["6"]),
    ("print(-(2 + 5));", ["-7"]),
    ("print(90 - 10 - 5);", ["75"]),
], ids=["mul-prec", "div-prec", "parens", "double-neg", "neg-group",
        "sub-left-assoc"])
def test_arithmetic(src, expected):
    assert run(src) == expected


def test_bignum_factorial():
    src = """
    let n = 20;
    let acc = 1;
    let i = 1;
    while (i <= n) { acc = acc * i; i = i + 1; }
    print(acc);
    """
    assert run(src) == [str(math.factorial(20))]


# -- truncating division and modulo (6) --------------------------------------

@pytest.mark.parametrize("src,expected", [
    ("print(9 / 2);", ["4"]),
    ("print(-9 / 2);", ["-4"]),
    ("print(9 / -2);", ["-4"]),
    ("print(-9 / -2);", ["4"]),
], ids=["pp", "np", "pn", "nn"])
def test_trunc_div(src, expected):
    assert run(src) == expected


def test_trunc_mod_signs():
    src = "print(9 % 2); print(-9 % 2); print(9 % -2); print(-9 % -2);"
    assert run(src) == ["1", "-1", "1", "-1"]


def test_divmod_invariant():
    src = "let a = -23; let b = 7; print(a / b * b + a % b);"
    assert run(src) == ["-23"]


# -- comparisons and equality (7) --------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ("print(3 < 4);", ["true"]),
    ("print(4 <= 3);", ["false"]),
    ("print(5 >= 5);", ["true"]),
    ('print(2 == "2");', ["false"]),
    ("print(false == 0);", ["false"]),
    ("print(nil == nil, nil == false);", ["true false"]),
], ids=["lt", "le", "ge", "int-vs-string", "bool-vs-int", "nil"])
def test_compare_eq(src, expected):
    assert run(src) == expected


def test_function_identity():
    src = ("fn a() { return nil; } fn b() { return nil; } let c = a;"
           " print(a == c, a == b, a != b);")
    assert run(src) == ["true false true"]


# -- short circuit (2) --------------------------------------------------------

def test_short_circuit_and():
    assert run("print(false && 1 / 0 == 0); print(false && 5);") == \
        ["false", "false"]


def test_short_circuit_or():
    assert run("print(true || 1 / 0 == 0);") == ["true"]


# -- scoping (6) ---------------------------------------------------------------

def test_let_assign():
    assert run("let x = 2; x = x * 3; print(x);") == ["6"]


def test_block_shadowing():
    src = "let v = 1; { let v = 8; print(v); } print(v);"
    assert run(src) == ["8", "1"]


def test_assign_nearest_enclosing():
    src = "let w = 1; { w = 4; { w = w + 2; } } print(w);"
    assert run(src) == ["6"]


def test_fresh_scope_per_iteration():
    src = """
    let i = 0;
    while (i < 3) { let q = i * 5; print(q); i = i + 1; }
    """
    assert run(src) == ["0", "5", "10"]


def test_undefined_read():
    expect_error("print(never_defined);", "LangNameError")


def test_same_scope_redeclaration():
    expect_error("let z = 1; let z = 2;", "LangNameError")


# -- control flow (4) ----------------------------------------------------------

def test_else_if_chain():
    src = """
    fn sign(n) {
      if (n < 0) { return "neg"; } else if (n == 0) { return "zero"; }
      else { return "pos"; }
    }
    print(sign(-3), sign(0), sign(11));
    """
    assert run(src) == ["neg zero pos"]


def test_while_accumulate():
    src = """
    let s = 0;
    let i = 1;
    while (i <= 12) { s = s + i; i = i + 1; }
    print(s);
    """
    assert run(src) == [str(sum(range(1, 13)))]


def test_break_continue():
    src = """
    let i = 0;
    let s = 0;
    while (true) {
      i = i + 1;
      if (i > 8) { break; }
      if (i % 2 == 0) { continue; }
      s = s + i;
    }
    print(s, i);
    """
    assert run(src) == ["16 9"]


def test_if_condition_type():
    expect_error("if (3) { print(1); }", "LangTypeError")


# -- functions and closures (7) ------------------------------------------------

def test_decl_and_call():
    assert run("fn mul(a, b) { return a * b; } print(mul(6, 7));") == ["42"]


def test_return_nil_forms():
    src = "fn f() { return; } fn g() { let x = 1; } print(f(), g());"
    assert run(src) == ["nil nil"]


def test_recursion_fib():
    src = """
    fn fib(n) { if (n < 2) { return n; } return fib(n - 1) + fib(n - 2); }
    print(fib(16));
    """
    assert run(src) == ["987"]


def test_mutual_recursion():
    src = """
    fn even(n) { if (n == 0) { return true; } return odd(n - 1); }
    fn odd(n) { if (n == 0) { return false; } return even(n - 1); }
    print(even(14), odd(9));
    """
    assert run(src) == ["true true"]


def test_counter_factory_independent():
    src = """
    fn mk() {
      let n = 0;
      fn inc() { n = n + 1; return n; }
      return inc;
    }
    let c1 = mk();
    let c2 = mk();
    print(c1(), c1(), c2(), c1());
    """
    assert run(src) == ["1 2 1 3"]


def test_late_binding():
    src = "let x = 5; fn get() { return x; } x = 6; print(get());"
    assert run(src) == ["6"]


def test_no_hoisting():
    expect_error("print(later()); fn later() { return 1; }", "LangNameError")
