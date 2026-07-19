"""T4 performance: documented workloads from the spec's Performance section.

Collected last (zz) so a slow implementation burns its watchdog seconds
after all functional tests have produced their score. Budgets are enforced
by the harness run() watchdog (4s: well under the conftest's 5s alarm, and
5x the reference implementation's worst observed time). 7 cases.
"""

from _harness import run


def test_perf_canary_10k_loop():
    # Hardware sanity check: if THIS fails, distrust the other perf results.
    src = """
    let s = 0;
    let i = 0;
    while (i < 10000) { s = s + i; i = i + 1; }
    print(s);
    """
    assert run(src, seconds=3.0) == [str(sum(range(10000)))]


def test_perf_200k_arith_loop():
    src = """
    let s = 0;
    let i = 0;
    while (i < 200000) {
      s = s + i * 2 - 1;
      i = i + 1;
    }
    print(s);
    """
    expected = sum(i * 2 - 1 for i in range(200000))
    assert run(src, seconds=4.0) == [str(expected)]


def test_perf_100k_calls():
    src = """
    fn inc(x) { return x + 1; }
    let i = 0;
    while (i < 100000) { i = inc(i); }
    print(i);
    """
    assert run(src, seconds=4.0) == ["100000"]


def test_perf_deep_scope_reads():
    depth = 30
    src = "let v0 = 7;\n" + "{\n" * depth + """
    let s = 0;
    let i = 0;
    while (i < 50000) { s = s + v0; i = i + 1; }
    print(s);
    """ + "}\n" * depth
    assert run(src, seconds=4.0) == [str(7 * 50000)]


def test_perf_100k_array_push_sum():
    src = """
    let a = [];
    for (let i = 0; i < 100000; i += 1) { push(a, i); }
    let s = 0;
    for (v in a) { s += v; }
    print(s);
    """
    assert run(src, seconds=4.0) == [str(sum(range(100000)))]


def test_perf_30k_try_throw_catch():
    src = """
    let n = 0;
    let i = 0;
    while (i < 30000) {
      try { throw 1; } catch (e) { n = n + e; }
      i = i + 1;
    }
    print(n);
    """
    assert run(src, seconds=4.0) == ["30000"]


def test_perf_string_concat_50k_chars():
    src = """
    let s = "";
    let i = 0;
    while (i < 10000) { s = s + "abcde"; i = i + 1; }
    print(len(s));
    """
    assert run(src, seconds=4.0) == ["50000"]
