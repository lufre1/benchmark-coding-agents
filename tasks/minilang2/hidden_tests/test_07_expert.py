"""T4: hardest semantic corners — finally x control flow, unwinding, depth. 13 cases."""

from _harness import expect_error, run


def test_finally_overrides_return():
    src = 'fn f() { try { return "try"; } finally { return "fin"; } } print(f());'
    assert run(src) == ["fin"]


def test_finally_break_replaces_return():
    src = """
    fn f() {
      while (true) {
        try { return 1; } finally { break; }
      }
      return 9;
    }
    print(f());
    """
    assert run(src) == ["9"]


def test_finally_return_discards_throw():
    src = 'fn f() { try { throw "gone"; } finally { return "kept"; } } print(f());'
    assert run(src) == ["kept"]


def test_finally_continue_discards_throw():
    src = """
    let i = 0;
    let survived = 0;
    while (i < 4) {
      i += 1;
      try { throw i; } finally { continue; }
    }
    survived = 1;
    print(i, survived);
    """
    assert run(src) == ["4 1"]


def test_rethrow_preserves_class_at_top():
    src = "try { let a = []; print(a[0]); } catch (e) { throw e; }"
    expect_error(src, "LangIndexError")


def test_rethrow_caught_again_same_kind():
    src = """
    try {
      try { print(1 % 0); } catch (e) { throw e; }
    } catch (e2) { print(errkind(e2)); }
    """
    assert run(src) == ["zerodiv"]


def test_error_in_catch_after_finally():
    src = """
    let log = [];
    try {
      try { throw "a"; }
      catch (e) { push(log, "c"); throw "b"; }
      finally { push(log, "f"); }
    } catch (e2) { push(log, e2); }
    print(log);
    """
    assert run(src) == ['["c", "f", "b"]']


def test_finally_without_catch_propagates():
    src = """
    let log = [];
    try {
      try { throw "z"; } finally { push(log, "fin"); }
    } catch (e) { push(log, e); }
    print(log);
    """
    assert run(src) == ['["fin", "z"]']


def test_unwinding_runs_finallys_innermost_first():
    src = """
    let log = [];
    fn inner() {
      try { throw "deep"; } finally { push(log, "i"); }
      return nil;
    }
    fn outer() {
      try { inner(); } finally { push(log, "o"); }
      return nil;
    }
    try { outer(); } catch (e) { push(log, e); }
    print(log);
    """
    assert run(src) == ['["i", "o", "deep"]']


def test_catch_does_not_swallow_return():
    src = "fn f() { try { return 5; } catch (e) { return 9; } } print(f());"
    assert run(src) == ["5"]


def test_catch_does_not_swallow_break():
    src = """
    let n = 0;
    while (true) {
      try { break; } catch (e) { n = 1; }
    }
    print(n);
    """
    assert run(src) == ["0"]


def test_errkind_full_mapping():
    src = """
    let kinds = [];
    fn trap(f) { try { f(); } catch (e) { push(kinds, errkind(e)); } return nil; }
    fn eName() { let x = missing_thing; return nil; }
    fn eType() { let x = 1 + "a"; return nil; }
    fn eArity() { len(); return nil; }
    fn eZero() { let x = 1 / 0; return nil; }
    fn eIndex() { let a = []; let x = a[0]; return nil; }
    fn eKey() { let d = {}; let x = d["k"]; return nil; }
    fn eValue() { pop([]); return nil; }
    trap(eName); trap(eType); trap(eArity); trap(eZero);
    trap(eIndex); trap(eKey); trap(eValue);
    print(kinds);
    """
    assert run(src) == \
        ['["name", "type", "arity", "zerodiv", "index", "key", "value"]']


def test_recursion_depth_1000():
    src = """
    fn sum(n) { if (n == 0) { return 0; } return n + sum(n - 1); }
    print(sum(1000));
    """
    assert run(src, seconds=2.0) == [str(sum(range(1001)))]
