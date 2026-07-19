"""T2: scoping, closures, builtin shadowing, catch/for-variable scopes. 25 cases."""

import pytest

from _harness import expect_error, run


# -- closures (6) ---------------------------------------------------------------

def test_shared_mutable_capture():
    src = """
    fn cell() {
      let n = 100;
      fn bump() { n = n + 3; return nil; }
      fn read() { return n; }
      fn pick(i) { if (i == 0) { return bump; } return read; }
      return pick;
    }
    let pick = cell();
    let bump = pick(0);
    let read = pick(1);
    bump(); bump();
    print(read());
    """
    assert run(src) == ["106"]


def test_closure_over_param():
    src = """
    fn adder(n) {
      fn add(m) { n = n + m; return n; }
      return add;
    }
    let a = adder(50);
    print(a(1), a(2));
    let b = adder(0);
    print(b(7), a(3));
    """
    assert run(src) == ["51 53", "7 56"]


def test_closure_survives_scope():
    src = """
    fn make() {
      let secret = 20;
      fn reveal() { return secret * 2 + 2; }
      return reveal;
    }
    let f = make();
    print(f());
    """
    assert run(src) == ["42"]


def test_late_binding_two_closures():
    src = """
    let x = 1;
    fn getA() { return x; }
    fn setB(v) { x = v; return nil; }
    setB(9);
    print(getA());
    """
    assert run(src) == ["9"]


def test_sibling_closures_share():
    src = """
    fn pair() {
      let v = 0;
      fn setv(n) { v = n; return nil; }
      fn getv() { return v; }
      setv(13);
      return getv;
    }
    print(pair()());
    """
    assert run(src) == ["13"]


def test_independent_instances():
    src = """
    fn box(v) {
      fn get() { return v; }
      return get;
    }
    let g1 = box("one");
    let g2 = box("two");
    print(g1(), g2());
    """
    assert run(src) == ["one two"]


# -- builtin shadowing (4) --------------------------------------------------------

def test_shadow_builtin_global():
    assert run("let len = 44; print(len);") == ["44"]


def test_shadow_builtin_in_block():
    assert run('{ let print = 1; } print("still works");') == ["still works"]


def test_shadowed_builtin_redeclare():
    expect_error("let str = 1; let str = 2;", "LangNameError")


def test_builtin_as_value():
    assert run('let p = print; p("via alias");') == ["via alias"]


# -- parameters and function names (3) -----------------------------------------------

def test_param_let_conflict():
    expect_error("fn f(a) { let a = 2; return a; } f(1);", "LangNameError")


def test_fn_calls_itself_by_name():
    src = "fn down(n) { if (n == 0) { return 0; } return down(n - 1); } print(down(5));"
    assert run(src) == ["0"]


def test_param_shadows_outer():
    src = "let n = 1; fn f(n) { return n * 10; } print(f(3), n);"
    assert run(src) == ["30 1"]


# -- block scoping depth (3) -----------------------------------------------------------

def test_shadow_three_deep():
    src = """
    let v = "a";
    {
      let v = "b";
      {
        let v = "c";
        print(v);
      }
      print(v);
    }
    print(v);
    """
    assert run(src) == ["c", "b", "a"]


def test_assign_through_levels():
    src = "let t = 0; { { { t = 5; } } } print(t);"
    assert run(src) == ["5"]


def test_block_scope_expires():
    expect_error("{ let inner = 1; } print(inner);", "LangNameError")


# -- catch parameter scope (3) ------------------------------------------------------------

def test_catch_param_dup():
    expect_error("try { throw 1; } catch (e) { let e = 2; }", "LangNameError")


def test_catch_param_shadows_outer():
    src = 'let e = "outer"; try { throw "inner"; } catch (e) { print(e); } print(e);'
    assert run(src) == ["inner", "outer"]


def test_catch_param_expires():
    expect_error("try { throw 1; } catch (c) { } print(c);", "LangNameError")


# -- for-loop variable scope (3) ------------------------------------------------------------

def test_for_var_body_shadow_legal():
    src = """
    let out = [];
    for (let i = 0; i < 2; i += 1) {
      let i = 90;
      push(out, i);
    }
    print(out);
    """
    assert run(src) == ["[90, 90]"]


def test_for_var_expires():
    expect_error("for (let i = 0; i < 1; i += 1) { } print(i);",
                 "LangNameError")


def test_forin_var_expires():
    expect_error("for (v in [1]) { } print(v);", "LangNameError")


# -- functions as container values (3) -----------------------------------------------------

def test_function_in_array():
    src = "fn sq(x) { return x * x; } let a = [sq]; print(a[0](9));"
    assert run(src) == ["81"]


def test_function_in_dict():
    src = 'fn hi() { return "hi"; } let d = {"f": hi}; print(d["f"]());'
    assert run(src) == ["hi"]


def test_higher_order_compose():
    src = """
    fn twice(f, x) { return f(f(x)); }
    fn inc(n) { return n + 1; }
    print(twice(inc, 10));
    """
    assert run(src) == ["12"]
