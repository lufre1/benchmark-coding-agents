"""T3: cross-feature precision traps. 40 cases."""

import pytest

from _harness import expect_error, run


# -- aliasing / reference semantics (3) -------------------------------------------

def test_alias_second_name():
    assert run("let a = [1]; let b = a; push(b, 2); b[0] = 9; print(a);") == \
        ["[9, 2]"]


def test_alias_through_param():
    src = """
    fn grow(xs) { push(xs, 99); return nil; }
    let a = [1, 2];
    grow(a);
    print(a);
    """
    assert run(src) == ["[1, 2, 99]"]


def test_alias_in_dict():
    src = """
    let a = [1];
    let d = {"ref": a};
    push(d["ref"], 2);
    print(a);
    """
    assert run(src) == ["[1, 2]"]


# -- slice = shallow copy (3) --------------------------------------------------------

def test_slice_copy_independent():
    src = """
    let a = [1, 2, 3];
    let c = a[:];
    push(c, 4);
    c[0] = 9;
    print(a);
    print(c);
    """
    assert run(src) == ["[1, 2, 3]", "[9, 2, 3, 4]"]


def test_slice_shallow_shares_nested():
    src = """
    let inner = [5];
    let outer = [inner, 6];
    let c = outer[0:2];
    c[0][0] = 55;
    print(outer);
    """
    assert run(src) == ["[[55], 6]"]


def test_slice_is_new_object():
    assert run("let a = [1, 2]; print(a[:] == a, a == a);") == ["false true"]


# -- display rules (6) -----------------------------------------------------------------

def test_nested_string_quoted_newline():
    assert run(r'print(["p\nq"]);') == [r'["p\nq"]']


def test_nested_string_all_escapes():
    # backslash, quote, newline, tab all re-escaped inside containers
    assert run(r'print(["a\\b\"c\nd\te"]);') == [r'["a\\b\"c\nd\te"]']


def test_dict_display_order_nested():
    src = 'let d = {"b": 2, "a": [1, "x"]}; print(d);'
    assert run(src) == ['{"b": 2, "a": [1, "x"]}']


def test_top_level_string_bare_nested_quoted():
    assert run('print("q"); print(["q"]);') == ["q", '["q"]']


def test_print_function_type_error():
    expect_error("fn f() { return 1; } print(f);", "LangTypeError")


def test_print_error_value_type_error():
    expect_error("try { print(1 / 0); } catch (e) { print(e); }",
                 "LangTypeError")


# -- statement-position '{' is a block (2) -----------------------------------------------

def test_dict_expression_statement_is_block():
    expect_error('{"a": 1};', "LangSyntaxError")


def test_parenthesized_dict_statement_ok():
    assert run('({"a": 1}); { } print("done");') == ["done"]


# -- assignment target validation (5) ------------------------------------------------------

@pytest.mark.parametrize("src", [
    "fn f() { return [1]; } f() = 1;",
    "let a = [1, 2]; a[0:1] = [9];",
    "let x = 1; (x) = 2;",
    "4 = 5;",
], ids=["call-target", "slice-target", "paren-target", "literal-target"])
def test_invalid_targets(src):
    expect_error(src, "LangSyntaxError")


def test_deep_chain_target():
    src = 'let d = {"k": [1, 2]}; d["k"][1] = 20; d["k"][0] += 4; print(d);'
    assert run(src) == ['{"k": [5, 20]}']


# -- compound assignment evaluation order (6) ------------------------------------------------

def test_plain_write_rhs_before_bounds():
    src = """
    let a = [1];
    fn loud() { print("effect"); return 10; }
    try { a[5] = loud(); } catch (e) { print(errkind(e)); }
    """
    assert run(src) == ["effect", "index"]


def test_compound_rhs_before_read():
    src = """
    let a = [1];
    fn loud() { print("effect"); return 10; }
    try { a[5] += loud(); } catch (e) { print(errkind(e)); }
    """
    assert run(src) == ["effect", "index"]


def test_dict_compound_read_before_write():
    expect_error('let d = {}; d["n"] += 1;', "LangKeyError")


def test_dict_plain_insert_ok():
    assert run('let d = {}; d["n"] = 1; d["n"] += 4; print(d["n"]);') == ["5"]


def test_index_evaluated_once():
    src = """
    let calls = 0;
    fn idx() { calls += 1; return 0; }
    let a = [10];
    a[idx()] += 5;
    print(a[0], calls);
    """
    assert run(src) == ["15 1"]


def test_ident_compound_rhs_before_name_check():
    src = """
    fn loud() { print("effect"); return 1; }
    try { phantom += loud(); } catch (e) { print(errkind(e)); }
    """
    assert run(src) == ["effect", "name"]


# -- for: per-iteration bindings (4) -----------------------------------------------------------

def test_for_closures_capture_per_iteration():
    src = """
    let fns = [];
    for (let i = 0; i < 3; i += 1) {
      fn get() { return i * 10; }
      push(fns, get);
    }
    print(fns[0](), fns[1](), fns[2]());
    """
    assert run(src) == ["0 10 20"]


def test_continue_runs_step():
    src = """
    let seen = [];
    for (let i = 0; i < 6; i += 1) {
      if (i % 2 == 1) { continue; }
      push(seen, i);
    }
    print(seen);
    """
    assert run(src) == ["[0, 2, 4]"]


def test_body_mutation_carries_to_step():
    src = """
    let seen = [];
    for (let i = 0; i < 10; i += 1) {
      push(seen, i);
      if (i == 2) { i = 7; }
    }
    print(seen);
    """
    assert run(src) == ["[0, 1, 2, 8, 9]"]


def test_forin_closures_capture_per_iteration():
    src = """
    let fns = [];
    for (v in [4, 8]) {
      fn get() { return v; }
      push(fns, get);
    }
    print(fns[0](), fns[1]());
    """
    assert run(src) == ["4 8"]


# -- live for-in (3) -------------------------------------------------------------------------------

def test_forin_push_extends():
    src = """
    let a = [1, 2];
    let seen = [];
    for (v in a) {
      if (v == 1) { push(a, 3); }
      push(seen, v);
    }
    print(seen);
    """
    assert run(src) == ["[1, 2, 3]"]


def test_forin_pop_shortens():
    src = """
    let a = [1, 2, 3, 4];
    let seen = [];
    for (v in a) {
      push(seen, v);
      pop(a);
    }
    print(seen);
    """
    assert run(src) == ["[1, 2]"]


def test_forin_var_assign_no_writeback():
    assert run("let a = [1, 2]; for (v in a) { v = 0; } print(a);") == \
        ["[1, 2]"]


# -- operator precision (8) --------------------------------------------------------------------------

def test_power_binds_over_unary_minus():
    assert run("print(-3 ** 2);") == ["-9"]


def test_power_right_assoc():
    assert run("print(2 ** 2 ** 3);") == ["256"]


def test_power_negative_exponent():
    expect_error("print(5 ** -2);", "LangValueError")


def test_ternary_right_assoc():
    # left-associative parsing would compute (true ? 4 : false) ? 5 : 6
    # and fail with a type error on the int condition
    assert run("print(true ? 4 : false ? 5 : 6);") == ["4"]


def test_ternary_lazy_else():
    assert run("print(false ? 1 / 0 : 7);") == ["7"]


def test_relational_chain_type_error():
    expect_error("print(2 < 3 < 9);", "LangTypeError")


def test_bool_index_type_error():
    expect_error("let a = [1, 2]; print(a[true]);", "LangTypeError")


def test_negative_index_error():
    expect_error("let a = [1, 2]; print(a[0 - 1]);", "LangIndexError")
