"""T2: arrays, dicts, strings, slices, for loops, try/catch happy paths. 25 cases."""

import pytest

from _harness import expect_error, run


# -- arrays (6) -----------------------------------------------------------------

def test_array_literal_print():
    assert run("print([7, true, nil]);") == ["[7, true, nil]"]


def test_array_index_read():
    assert run("let a = [10, 20, 30]; print(a[0], a[2]);") == ["10 30"]


def test_array_index_write():
    assert run("let a = [1, 2, 3]; a[1] = 22; print(a);") == ["[1, 22, 3]"]


def test_array_len():
    assert run("print(len([]), len([4, 5, 6]));") == ["0 3"]


def test_push_pop():
    src = """
    let a = [1];
    push(a, 2);
    push(a, 3);
    let last = pop(a);
    print(last, a);
    """
    assert run(src) == ["3 [1, 2]"]


def test_nested_arrays():
    assert run("let g = [[1, 2], [3]]; print(g[1][0], g);") == \
        ["3 [[1, 2], [3]]"]


# -- dicts (6) ------------------------------------------------------------------

def test_dict_literal_read():
    assert run('let d = {"a": 5, "b": 6}; print(d["b"], d["a"]);') == ["6 5"]


def test_dict_insert_update():
    src = 'let d = {"x": 1}; d["y"] = 2; d["x"] = 9; print(d);'
    assert run(src) == ['{"x": 9, "y": 2}']


def test_dict_keys():
    src = 'let d = {"p": 1, "q": 2}; d["r"] = 3; print(keys(d));'
    assert run(src) == ['["p", "q", "r"]']


def test_dict_has():
    assert run('let d = {"k": nil}; print(has(d, "k"), has(d, "z"));') == \
        ["true false"]


def test_dict_remove_returns_value():
    src = 'let d = {"a": 7, "b": 8}; let v = remove(d, "a"); print(v, keys(d));'
    assert run(src) == ['7 ["b"]']


def test_dict_len():
    assert run('print(len({}), len({"a": 1, "b": 2}));') == ["0 2"]


# -- strings (3) -------------------------------------------------------------------

def test_string_index():
    assert run('let s = "world"; print(s[0], s[4]);') == ["w d"]


def test_string_slice():
    assert run('let s = "minilang"; print(s[0:4], s[4:]);') == ["mini lang"]


def test_ord_chr_roundtrip():
    assert run('print(ord("Z"), chr(97), chr(ord("m") + 1));') == ["90 a n"]


# -- slices (2) ----------------------------------------------------------------------

def test_array_slice_middle():
    assert run("let a = [0, 1, 2, 3, 4]; print(a[1:4]);") == ["[1, 2, 3]"]


def test_slice_open_ends():
    assert run("let a = [5, 6, 7]; print(a[:2], a[1:], len(a[:]));") == \
        ["[5, 6] [6, 7] 3"]


# -- for loops (4) ----------------------------------------------------------------------

def test_for_accumulate():
    src = """
    let s = 0;
    for (let i = 0; i < 10; i += 1) { s += i * i; }
    print(s);
    """
    assert run(src) == [str(sum(i * i for i in range(10)))]


def test_forin_array_sum():
    src = "let s = 0; for (v in [3, 5, 8]) { s += v; } print(s);"
    assert run(src) == ["16"]


def test_forin_string_build():
    src = 'let out = ""; for (c in "abc") { out = c + out; } print(out);'
    assert run(src) == ["cba"]


def test_for_break_continue():
    src = """
    let picked = [];
    for (let i = 1; i < 100; i += 1) {
      if (i % 3 == 0) { continue; }
      if (i > 7) { break; }
      push(picked, i);
    }
    print(picked);
    """
    assert run(src) == ["[1, 2, 4, 5, 7]"]


# -- ternary and power (2) -----------------------------------------------------------------

def test_ternary_basic():
    src = "fn m(a, b) { return a > b ? a : b; } print(m(3, 9), m(10, 2));"
    assert run(src) == ["9 10"]


def test_power_basic():
    assert run("print(3 ** 4, 5 ** 0, 1 ** 100);") == ["81 1 1"]


# -- try/catch basics (2) --------------------------------------------------------------------

def test_catch_zerodiv_errkind():
    src = 'try { print(7 / 0); } catch (e) { print(errkind(e)); }'
    assert run(src) == ["zerodiv"]


def test_throw_catch_value_roundtrip():
    src = 'try { throw {"code": 42}; } catch (e) { print(e["code"]); }'
    assert run(src) == ["42"]
