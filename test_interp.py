"""Unit tests for the MiniLang2 interpreter.

Covers every feature: literals, arithmetic, comparisons, logic, strings,
variables, scoping, control flow, functions, closures, arrays, dicts,
slices, indexing, for loops, for-in loops, ternary, power, try/catch/finally,
throw, error taxonomy (all classes, graded positions), builtins, display rules,
reference semantics, compound assignment evaluation order, per-iteration
bindings, live for-in, and performance workloads.
"""

import math
import unittest

import interp


def run(src):
    return interp.run(src)


class LangError(unittest.TestCase):
    """Verify the error class hierarchy and instance attributes."""

    def test_error_hierarchy(self):
        self.assertTrue(issubclass(interp.LangSyntaxError, interp.LangError))
        self.assertTrue(issubclass(interp.LangNameError, interp.LangError))
        self.assertTrue(issubclass(interp.LangTypeError, interp.LangError))
        self.assertTrue(issubclass(interp.LangArityError, interp.LangError))
        self.assertTrue(issubclass(interp.LangZeroDivError, interp.LangError))
        self.assertTrue(issubclass(interp.LangIndexError, interp.LangError))
        self.assertTrue(issubclass(interp.LangKeyError, interp.LangError))
        self.assertTrue(issubclass(interp.LangValueError, interp.LangError))
        self.assertTrue(issubclass(interp.LangThrownError, interp.LangError))
        self.assertTrue(issubclass(interp.LangError, Exception))

    def test_error_classes_distinct(self):
        names = [
            "LangSyntaxError", "LangNameError", "LangTypeError",
            "LangArityError", "LangZeroDivError", "LangIndexError",
            "LangKeyError", "LangValueError", "LangThrownError",
        ]
        classes = [getattr(interp, n) for n in names]
        self.assertEqual(len(set(classes)), len(classes))

    def test_all_errors_have_line_col(self):
        for exc_class in [
            interp.LangSyntaxError, interp.LangNameError, interp.LangTypeError,
            interp.LangArityError, interp.LangZeroDivError, interp.LangIndexError,
            interp.LangKeyError, interp.LangValueError, interp.LangThrownError,
        ]:
            with self.subTest(cls=exc_class.__name__):
                e = exc_class("msg", line=3, col=7)
                self.assertEqual(e.line, 3)
                self.assertEqual(e.col, 7)


class TestLiteralPrint(unittest.TestCase):
    def test_print_int(self):
        self.assertEqual(run("print(42);"), ["42"])
        self.assertEqual(run("print(0);"), ["0"])

    def test_leading_zeros(self):
        self.assertEqual(run("print(007);"), ["7"])
        self.assertEqual(run("print(000);"), ["0"])

    def test_print_bool_nil(self):
        self.assertEqual(run("print(true);"), ["true"])
        self.assertEqual(run("print(false);"), ["false"])
        self.assertEqual(run("print(nil);"), ["nil"])

    def test_print_multi_arg(self):
        self.assertEqual(run('print(1, 2, 3);'), ["1 2 3"])
        self.assertEqual(run('print("a", true, nil);'), ["a true nil"])
        self.assertEqual(run("print();"), [""])

    def test_print_multiple_calls(self):
        self.assertEqual(run('print(1); print("two");'), ["1", "two"])

    def test_string_escapes(self):
        self.assertEqual(run('print("a\\tb");'), ["a\tb"])
        self.assertEqual(run('print("say \\"yo\\"");'), ['say "yo"'])
        self.assertEqual(run('print("back\\\\slash");'), ["back\\slash"])
        self.assertEqual(run('print("p\\nq"); print("r");'), ["p\nq", "r"])

    def test_invalid_escape(self):
        for src in ['let s = "a\\q";', 'let s = "a\\xcd";']:
            with self.subTest(src=src):
                with self.assertRaises(interp.LangSyntaxError):
                    run(src)

    def test_unterminated_string(self):
        for src in ['let s = "abc;', 'let s = "abc']:
            with self.subTest(src=src):
                with self.assertRaises(interp.LangSyntaxError):
                    run(src)

    def test_newline_in_string(self):
        with self.assertRaises(interp.LangSyntaxError):
            run('let s = "a\nb";')

    def test_escape_newline_in_string(self):
        self.assertEqual(run('print("a\\nb");'), ["a\nb"])


class TestArithmetic(unittest.TestCase):
    def test_precedence(self):
        cases = [
            ("print(2 + 3 * 4);", ["14"]),
            ("print(30 - 8 / 2);", ["26"]),
            ("print(90 - 10 - 5);", ["75"]),
            ("print(2 * 3 % 4);", ["2"]),
        ]
        for src, expected in cases:
            with self.subTest(src=src):
                self.assertEqual(run(src), expected)

    def test_parentheses(self):
        self.assertEqual(run("print((2 + 3) * 4); print(2 * (3 + 4));"),
                         ["20", "14"])

    def test_unary_minus(self):
        cases = [
            ("print(-5);", ["-5"]),
            ("print(-2 * 3 + 1);", ["-5"]),
            ("print(- -6);", ["6"]),
            ("print(-(2 + 5));", ["-7"]),
        ]
        for src, expected in cases:
            with self.subTest(src=src):
                self.assertEqual(run(src), expected)

    def test_truncating_division(self):
        self.assertEqual(run("print(7 / 2); print(-7 / 2); print(7 / -2); print(-7 / -2);"),
                         ["3", "-3", "-3", "3"])

    def test_modulo_sign(self):
        self.assertEqual(run("print(7 % 2); print(-7 % 2); print(7 % -2); print(-7 % -2);"),
                         ["1", "-1", "1", "-1"])

    def test_divmod_invariant(self):
        self.assertEqual(run("let a = -17; let b = 5; print(a / b * b + a % b);"),
                         ["-17"])

    def test_bignum(self):
        self.assertEqual(run("print(99999999999999999999 + 10000000000000000000);"),
                         ["109999999999999999999"])

    def test_factorial_25(self):
        src = """
        let n = 25;
        let acc = 1;
        let i = 1;
        while (i <= n) { acc = acc * i; i = i + 1; }
        print(acc);
        """
        self.assertEqual(run(src), [str(math.factorial(25))])


class TestComparisonsAndEquality(unittest.TestCase):
    def test_comparisons(self):
        cases = [
            ("print(1 < 2);", ["true"]),
            ("print(2 <= 2);", ["true"]),
            ("print(3 > 4);", ["false"]),
            ("print(5 >= 5);", ["true"]),
            ("print(2 < 2);", ["false"]),
        ]
        for src, expected in cases:
            with self.subTest(src=src):
                self.assertEqual(run(src), expected)

    def test_equality(self):
        cases = [
            ("print(1 == 1);", ["true"]),
            ("print(1 != 2);", ["true"]),
            ('print("a" == "a");', ["true"]),
            ('print(2 == "2");', ["false"]),
            ("print(false == 0);", ["false"]),
            ("print(nil == nil);", ["true"]),
            ("print(nil == false);", ["false"]),
        ]
        for src, expected in cases:
            with self.subTest(src=src):
                self.assertEqual(run(src), expected)

    def test_function_identity(self):
        src = ("fn a() { return nil; } fn b() { return nil; } let c = a;"
               " print(a == c, a == b, a != b);")
        self.assertEqual(run(src), ["true false true"])

    def test_relational_chain_type_error(self):
        with self.assertRaises(interp.LangTypeError):
            run("print(1 < 2 < 3);")


class TestShortCircuit(unittest.TestCase):
    def test_short_circuit_and(self):
        self.assertEqual(run("print(false && 1 / 0 == 0); print(false && 5);"),
                         ["false", "false"])

    def test_short_circuit_or(self):
        self.assertEqual(run("print(true || 1 / 0 == 0);"), ["true"])


class TestTernaryAndPower(unittest.TestCase):
    def test_ternary_basic(self):
        src = "fn m(a, b) { return a > b ? a : b; } print(m(3, 9), m(10, 2));"
        self.assertEqual(run(src), ["9 10"])

    def test_ternary_right_assoc(self):
        self.assertEqual(run("print(true ? 4 : false ? 5 : 6);"), ["4"])

    def test_ternary_lazy_else(self):
        self.assertEqual(run("print(false ? 1 / 0 : 7);"), ["7"])

    def test_power_basic(self):
        self.assertEqual(run("print(3 ** 4, 5 ** 0, 1 ** 100);"), ["81 1 1"])

    def test_power_binds_over_unary_minus(self):
        self.assertEqual(run("print(-3 ** 2);"), ["-9"])

    def test_power_right_assoc(self):
        self.assertEqual(run("print(2 ** 2 ** 3);"), ["256"])

    def test_power_negative_exponent(self):
        with self.assertRaises(interp.LangValueError):
            run("print(5 ** -2);")

    def test_power_zero_exponent(self):
        self.assertEqual(run("print(0 ** 0);"), ["1"])


class TestVariablesScoping(unittest.TestCase):
    def test_let_and_assign(self):
        self.assertEqual(run("let x = 2; x = x * 3; print(x);"), ["6"])

    def test_block_shadowing(self):
        src = "let v = 1; { let v = 8; print(v); } print(v);"
        self.assertEqual(run(src), ["8", "1"])

    def test_assign_nearest_enclosing(self):
        src = "let w = 1; { w = 4; { w = w + 2; } } print(w);"
        self.assertEqual(run(src), ["6"])

    def test_fresh_scope_per_iteration(self):
        src = """
        let i = 0;
        while (i < 3) { let q = i * 5; print(q); i = i + 1; }
        """
        self.assertEqual(run(src), ["0", "5", "10"])

    def test_undefined_read(self):
        with self.assertRaises(interp.LangNameError):
            run("print(never_defined);")

    def test_undefined_assign(self):
        with self.assertRaises(interp.LangNameError):
            run("ghost = 1;")

    def test_same_scope_redeclare(self):
        with self.assertRaises(interp.LangNameError):
            run("let z = 1; let z = 2;")

    def test_var_expires_outside_block(self):
        with self.assertRaises(interp.LangNameError):
            run("{ let inner = 1; } print(inner);")

    def test_shadow_three_deep(self):
        src = """
        let v = "a";
        { let v = "b"; { let v = "c"; print(v); } print(v); }
        print(v);
        """
        self.assertEqual(run(src), ["c", "b", "a"])

    def test_assign_through_levels(self):
        src = "let t = 0; { { { t = 5; } } } print(t);"
        self.assertEqual(run(src), ["5"])


class TestControlFlow(unittest.TestCase):
    def test_if_basic(self):
        self.assertEqual(run("if (true) { print(1); }"), ["1"])
        self.assertEqual(run("if (false) { print(1); }"), [])

    def test_if_else(self):
        self.assertEqual(run("if (true) { print(1); } else { print(2); }"), ["1"])
        self.assertEqual(run("if (false) { print(1); } else { print(2); }"), ["2"])

    def test_else_if_chain(self):
        src = """
        fn sign(n) {
            if (n < 0) { return "neg"; }
            else if (n == 0) { return "zero"; }
            else { return "pos"; }
        }
        print(sign(-3), sign(0), sign(11));
        """
        self.assertEqual(run(src), ["neg zero pos"])

    def test_while_accumulate(self):
        src = """
        let s = 0;
        let i = 1;
        while (i <= 12) { s = s + i; i = i + 1; }
        print(s);
        """
        self.assertEqual(run(src), [str(sum(range(1, 13)))])

    def test_break_continue(self):
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
        self.assertEqual(run(src), ["16 9"])

    def test_condition_type_errors(self):
        for src in ["if (1) { }", 'while ("x") { }', "if (nil) { }", "while (1) { }"]:
            with self.subTest(src=src):
                with self.assertRaises(interp.LangTypeError):
                    run(src)


class TestFunctionsClosures(unittest.TestCase):
    def test_decl_and_call(self):
        self.assertEqual(run("fn mul(a, b) { return a * b; } print(mul(6, 7));"),
                         ["42"])

    def test_return_nil_forms(self):
        src = "fn f() { return; } fn g() { let x = 1; } print(f(), g());"
        self.assertEqual(run(src), ["nil nil"])

    def test_recursion_fib(self):
        src = """
        fn fib(n) { if (n < 2) { return n; } return fib(n - 1) + fib(n - 2); }
        print(fib(16));
        """
        self.assertEqual(run(src), ["987"])

    def test_mutual_recursion(self):
        src = """
        fn even(n) { if (n == 0) { return true; } return odd(n - 1); }
        fn odd(n) { if (n == 0) { return false; } return even(n - 1); }
        print(even(14), odd(9));
        """
        self.assertEqual(run(src), ["true true"])

    def test_counter_factory(self):
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
        self.assertEqual(run(src), ["1 2 1 3"])

    def test_shared_mutable_capture(self):
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
        self.assertEqual(run(src), ["106"])

    def test_closure_over_param(self):
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
        self.assertEqual(run(src), ["51 53", "7 56"])

    def test_late_binding(self):
        src = "let x = 5; fn get() { return x; } x = 6; print(get());"
        self.assertEqual(run(src), ["6"])

    def test_no_hoisting(self):
        with self.assertRaises(interp.LangNameError):
            run("print(later()); fn later() { return 1; }")

    def test_fn_calls_itself_by_name(self):
        src = "fn down(n) { if (n == 0) { return 0; } return down(n - 1); } print(down(5));"
        self.assertEqual(run(src), ["0"])

    def test_param_shadows_outer(self):
        src = "let n = 1; fn f(n) { return n * 10; } print(f(3), n);"
        self.assertEqual(run(src), ["30 1"])

    def test_function_in_array(self):
        src = "fn sq(x) { return x * x; } let a = [sq]; print(a[0](9));"
        self.assertEqual(run(src), ["81"])

    def test_function_in_dict(self):
        src = 'fn hi() { return "hi"; } let d = {"f": hi}; print(d["f"]());'
        self.assertEqual(run(src), ["hi"])

    def test_deep_recursion(self):
        src = """
        fn sum(n) {
            if (n == 0) { return 0; }
            return n + sum(n - 1);
        }
        print(sum(1000));
        """
        self.assertEqual(run(src), [str(sum(range(1001)))])


class TestArrays(unittest.TestCase):
    def test_array_literal_print(self):
        self.assertEqual(run("print([7, true, nil]);"), ["[7, true, nil]"])

    def test_array_empty_print(self):
        self.assertEqual(run("print([]);"), ["[]"])

    def test_array_index_read(self):
        self.assertEqual(run("let a = [10, 20, 30]; print(a[0], a[2]);"), ["10 30"])

    def test_array_index_write(self):
        self.assertEqual(run("let a = [1, 2, 3]; a[1] = 22; print(a);"), ["[1, 22, 3]"])

    def test_array_len(self):
        self.assertEqual(run("print(len([]), len([4, 5, 6]));"), ["0 3"])

    def test_push_pop(self):
        src = """
        let a = [1];
        push(a, 2);
        push(a, 3);
        let last = pop(a);
        print(last, a);
        """
        self.assertEqual(run(src), ["3 [1, 2]"])

    def test_nested_arrays(self):
        self.assertEqual(run("let g = [[1, 2], [3]]; print(g[1][0], g);"),
                         ["3 [[1, 2], [3]]"])


class TestDicts(unittest.TestCase):
    def test_dict_literal_read(self):
        self.assertEqual(run('let d = {"a": 5, "b": 6}; print(d["b"], d["a"]);'),
                         ["6 5"])

    def test_dict_insert_update(self):
        src = 'let d = {"x": 1}; d["y"] = 2; d["x"] = 9; print(d);'
        self.assertEqual(run(src), ['{"x": 9, "y": 2}'])

    def test_dict_keys(self):
        src = 'let d = {"p": 1, "q": 2}; d["r"] = 3; print(keys(d));'
        self.assertEqual(run(src), ['["p", "q", "r"]'])

    def test_dict_has(self):
        self.assertEqual(run('let d = {"k": nil}; print(has(d, "k"), has(d, "z"));'),
                         ["true false"])

    def test_dict_remove_returns_value(self):
        src = 'let d = {"a": 7, "b": 8}; let v = remove(d, "a"); print(v, keys(d));'
        self.assertEqual(run(src), ['7 ["b"]'])

    def test_dict_len(self):
        self.assertEqual(run('print(len({}), len({"a": 1, "b": 2}));'), ["0 2"])

    def test_dict_insertion_order_update_keeps_position(self):
        src = 'let d = {"a": 1, "b": 2, "c": 3}; d["b"] = 99; print(keys(d));'
        self.assertEqual(run(src), ['["a", "b", "c"]'])

    def test_dict_insertion_order_remove_reinsert(self):
        src = 'let d = {"a": 1, "b": 2}; remove(d, "a"); d["a"] = 3; print(keys(d));'
        self.assertEqual(run(src), ['["b", "a"]'])


class TestStrings(unittest.TestCase):
    def test_string_index(self):
        self.assertEqual(run('let s = "world"; print(s[0], s[4]);'), ["w d"])

    def test_string_slice(self):
        self.assertEqual(run('let s = "minilang"; print(s[0:4], s[4:]);'), ["mini lang"])

    def test_ord_chr_roundtrip(self):
        self.assertEqual(run('print(ord("Z"), chr(97), chr(ord("m") + 1));'),
                         ["90 a n"])


class TestSlices(unittest.TestCase):
    def test_slice_middle(self):
        self.assertEqual(run("let a = [0, 1, 2, 3, 4]; print(a[1:4]);"),
                         ["[1, 2, 3]"])

    def test_slice_open_ends(self):
        self.assertEqual(run("let a = [5, 6, 7]; print(a[:2], a[1:], len(a[:]));"),
                         ["[5, 6] [6, 7] 3"])

    def test_slice_empty(self):
        self.assertEqual(run("let a = [1, 2, 3]; print(a[2:1]);"), ["[]"])
        self.assertEqual(run('let s = "abc"; print(s[2:1]);'), [""])

    def test_slice_clamp_hi(self):
        self.assertEqual(run('let s = "abc"; print(s[1:99]);'), ["bc"])

    def test_slice_clamp_lo(self):
        self.assertEqual(run('let a = [1, 2]; print(a[99:]);'), ["[]"])

    def test_slice_copy_independent(self):
        src = """
        let a = [1, 2, 3];
        let c = a[:];
        push(c, 4);
        c[0] = 9;
        print(a);
        print(c);
        """
        self.assertEqual(run(src), ["[1, 2, 3]", "[9, 2, 3, 4]"])

    def test_slice_shallow_shares_nested(self):
        src = """
        let inner = [5];
        let outer = [inner, 6];
        let c = outer[0:2];
        c[0][0] = 55;
        print(outer);
        """
        self.assertEqual(run(src), ["[[55], 6]"])

    def test_slice_is_new_object(self):
        self.assertEqual(run("let a = [1, 2]; print(a[:] == a, a == a);"),
                         ["false true"])

    def test_slice_negative_bound(self):
        with self.assertRaises(interp.LangIndexError):
            run("let a = [1]; print(a[-1:]);")
        with self.assertRaises(interp.LangIndexError):
            run("let a = [1]; print(a[:-1]);")


class TestForLoops(unittest.TestCase):
    def test_for_accumulate(self):
        src = """
        let s = 0;
        for (let i = 0; i < 10; i += 1) { s += i * i; }
        print(s);
        """
        self.assertEqual(run(src), [str(sum(i * i for i in range(10)))])

    def test_for_break_continue(self):
        src = """
        let picked = [];
        for (let i = 1; i < 100; i += 1) {
            if (i % 3 == 0) { continue; }
            if (i > 7) { break; }
            push(picked, i);
        }
        print(picked);
        """
        self.assertEqual(run(src), ["[1, 2, 4, 5, 7]"])

    def test_for_closures_capture_per_iteration(self):
        src = """
        let fns = [];
        for (let i = 0; i < 3; i += 1) {
            fn get() { return i * 10; }
            push(fns, get);
        }
        print(fns[0](), fns[1](), fns[2]());
        """
        self.assertEqual(run(src), ["0 10 20"])

    def test_continue_runs_step(self):
        src = """
        let seen = [];
        for (let i = 0; i < 6; i += 1) {
            if (i % 2 == 1) { continue; }
            push(seen, i);
        }
        print(seen);
        """
        self.assertEqual(run(src), ["[0, 2, 4]"])

    def test_body_mutation_carries_to_step(self):
        src = """
        let seen = [];
        for (let i = 0; i < 10; i += 1) {
            push(seen, i);
            if (i == 2) { i = 7; }
        }
        print(seen);
        """
        self.assertEqual(run(src), ["[0, 1, 2, 8, 9]"])

    def test_for_var_expires(self):
        with self.assertRaises(interp.LangNameError):
            run("for (let i = 0; i < 1; i += 1) { } print(i);")

    def test_for_var_body_shadow_legal(self):
        src = """
        let out = [];
        for (let i = 0; i < 2; i += 1) {
            let i = 90;
            push(out, i);
        }
        print(out);
        """
        self.assertEqual(run(src), ["[90, 90]"])

    def test_forin_array_sum(self):
        src = "let s = 0; for (v in [3, 5, 8]) { s += v; } print(s);"
        self.assertEqual(run(src), ["16"])

    def test_forin_string_build(self):
        src = 'let out = ""; for (c in "abc") { out = c + out; } print(out);'
        self.assertEqual(run(src), ["cba"])

    def test_forin_closures_capture_per_iteration(self):
        src = """
        let fns = [];
        for (v in [4, 8]) {
            fn get() { return v; }
            push(fns, get);
        }
        print(fns[0](), fns[1]());
        """
        self.assertEqual(run(src), ["4 8"])

    def test_forin_var_expires(self):
        with self.assertRaises(interp.LangNameError):
            run("for (v in [1]) { } print(v);")

    def test_forin_push_extends(self):
        src = """
        let a = [1, 2];
        let seen = [];
        for (v in a) {
            if (v == 1) { push(a, 3); }
            push(seen, v);
        }
        print(seen);
        """
        self.assertEqual(run(src), ["[1, 2, 3]"])

    def test_forin_pop_shortens(self):
        src = """
        let a = [1, 2, 3, 4];
        let seen = [];
        for (v in a) {
            push(seen, v);
            pop(a);
        }
        print(seen);
        """
        self.assertEqual(run(src), ["[1, 2]"])

    def test_forin_var_assign_no_writeback(self):
        self.assertEqual(run("let a = [1, 2]; for (v in a) { v = 0; } print(a);"),
                         ["[1, 2]"])

    def test_forin_type_error(self):
        with self.assertRaises(interp.LangTypeError):
            run("for (v in 42) { }")


class TestTryCatchFinally(unittest.TestCase):
    def test_catch_zerodiv_errkind(self):
        src = 'try { print(7 / 0); } catch (e) { print(errkind(e)); }'
        self.assertEqual(run(src), ["zerodiv"])

    def test_throw_catch_value_roundtrip(self):
        src = 'try { throw {"code": 42}; } catch (e) { print(e["code"]); }'
        self.assertEqual(run(src), ["42"])

    def test_finally_overrides_return(self):
        src = 'fn f() { try { return "try"; } finally { return "fin"; } } print(f());'
        self.assertEqual(run(src), ["fin"])

    def test_finally_break_replaces_return(self):
        src = """
        fn f() {
            while (true) {
                try { return 1; } finally { break; }
            }
            return 9;
        }
        print(f());
        """
        self.assertEqual(run(src), ["9"])

    def test_finally_return_discards_throw(self):
        src = 'fn f() { try { throw "gone"; } finally { return "kept"; } } print(f());'
        self.assertEqual(run(src), ["kept"])

    def test_finally_continue_discards_throw(self):
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
        self.assertEqual(run(src), ["4 1"])

    def test_rethrow_preserves_class_at_top(self):
        src = "try { let a = []; print(a[0]); } catch (e) { throw e; }"
        with self.assertRaises(interp.LangIndexError):
            run(src)

    def test_rethrow_caught_again_same_kind(self):
        src = """
        try {
            try { print(1 % 0); } catch (e) { throw e; }
        } catch (e2) { print(errkind(e2)); }
        """
        self.assertEqual(run(src), ["zerodiv"])

    def test_error_in_catch_after_finally(self):
        src = """
        let log = [];
        try {
            try { throw "a"; }
            catch (e) { push(log, "c"); throw "b"; }
            finally { push(log, "f"); }
        } catch (e2) { push(log, e2); }
        print(log);
        """
        self.assertEqual(run(src), ['["c", "f", "b"]'])

    def test_finally_without_catch_propagates(self):
        src = """
        let log = [];
        try {
            try { throw "z"; } finally { push(log, "fin"); }
        } catch (e) { push(log, e); }
        print(log);
        """
        self.assertEqual(run(src), ['["fin", "z"]'])

    def test_unwinding_runs_finallys_innermost_first(self):
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
        self.assertEqual(run(src), ['["i", "o", "deep"]'])

    def test_catch_does_not_swallow_return(self):
        src = "fn f() { try { return 5; } catch (e) { return 9; } } print(f());"
        self.assertEqual(run(src), ["5"])

    def test_catch_does_not_swallow_break(self):
        src = """
        let n = 0;
        while (true) {
            try { break; } catch (e) { n = 1; }
        }
        print(n);
        """
        self.assertEqual(run(src), ["0"])

    def test_errkind_full_mapping(self):
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
        self.assertEqual(run(src),
                         ['["name", "type", "arity", "zerodiv", "index", "key", "value"]'])


class TestDisplay(unittest.TestCase):
    def test_top_level_string_bare(self):
        self.assertEqual(run('print("q");'), ["q"])

    def test_nested_string_quoted(self):
        self.assertEqual(run('print(["q"]);'), ['["q"]'])

    def test_nested_string_escapes(self):
        self.assertEqual(run('print(["p\\nq"]);'), ['["p\\nq"]'])

    def test_nested_string_all_escapes(self):
        self.assertEqual(run('print(["a\\\\b\\"c\\nd\\te"]);'),
                         ['["a\\\\b\\"c\\nd\\te"]'])

    def test_dict_display_order(self):
        src = 'let d = {"b": 2, "a": [1, "x"]}; print(d);'
        self.assertEqual(run(src), ['{"b": 2, "a": [1, "x"]}'])

    def test_print_function_type_error(self):
        with self.assertRaises(interp.LangTypeError):
            run("fn f() { return 1; } print(f);")

    def test_print_error_value_type_error(self):
        with self.assertRaises(interp.LangTypeError):
            run("try { print(1 / 0); } catch (e) { print(e); }")

    def test_str_function_type_error(self):
        with self.assertRaises(interp.LangTypeError):
            run("fn f() { } print(str(f));")


class TestReferenceSemantics(unittest.TestCase):
    def test_alias_second_name(self):
        self.assertEqual(run("let a = [1]; let b = a; push(b, 2); b[0] = 9; print(a);"),
                         ["[9, 2]"])

    def test_alias_through_param(self):
        src = """
        fn grow(xs) { push(xs, 99); return nil; }
        let a = [1, 2];
        grow(a);
        print(a);
        """
        self.assertEqual(run(src), ["[1, 2, 99]"])

    def test_alias_in_dict(self):
        src = """
        let a = [1];
        let d = {"ref": a};
        push(d["ref"], 2);
        print(a);
        """
        self.assertEqual(run(src), ["[1, 2]"])


class TestCompoundAssignmentEvalOrder(unittest.TestCase):
    def test_plain_write_rhs_before_bounds(self):
        src = """
        let a = [1];
        fn loud() { print("effect"); return 10; }
        try { a[5] = loud(); } catch (e) { print(errkind(e)); }
        """
        self.assertEqual(run(src), ["effect", "index"])

    def test_compound_rhs_before_read(self):
        src = """
        let a = [1];
        fn loud() { print("effect"); return 10; }
        try { a[5] += loud(); } catch (e) { print(errkind(e)); }
        """
        self.assertEqual(run(src), ["effect", "index"])

    def test_dict_compound_read_before_write(self):
        with self.assertRaises(interp.LangKeyError):
            run('let d = {}; d["n"] += 1;')

    def test_dict_plain_insert_ok(self):
        self.assertEqual(run('let d = {}; d["n"] = 1; d["n"] += 4; print(d["n"]);'),
                         ["5"])

    def test_index_evaluated_once(self):
        src = """
        let calls = 0;
        fn idx() { calls += 1; return 0; }
        let a = [10];
        a[idx()] += 5;
        print(a[0], calls);
        """
        self.assertEqual(run(src), ["15 1"])

    def test_ident_compound_rhs_before_name_check(self):
        src = """
        fn loud() { print("effect"); return 1; }
        try { phantom += loud(); } catch (e) { print(errkind(e)); }
        """
        self.assertEqual(run(src), ["effect", "name"])


class TestStatementPositionDict(unittest.TestCase):
    def test_dict_expression_statement_is_block(self):
        with self.assertRaises(interp.LangSyntaxError):
            run('{"a": 1};')

    def test_parenthesized_dict_statement_ok(self):
        self.assertEqual(run('({"a": 1}); { } print("done");'), ["done"])


class TestAssignmentTargets(unittest.TestCase):
    def test_call_target(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("fn f() { return [1]; } f() = 1;")

    def test_slice_target(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("let a = [1, 2]; a[0:1] = [9];")

    def test_paren_target(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("let x = 1; (x) = 2;")

    def test_literal_target(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("4 = 5;")

    def test_deep_chain_target(self):
        src = 'let d = {"k": [1, 2]}; d["k"][1] = 20; d["k"][0] += 4; print(d);'
        self.assertEqual(run(src), ['{"k": [5, 20]}'])


class TestErrorPositions(unittest.TestCase):
    def _check_pos(self, src, err_cls, line, col):
        try:
            run(src)
            self.fail("expected %s" % err_cls.__name__)
        except err_cls as e:
            self.assertEqual((e.line, e.col), (line, col))

    def test_unexpected_char(self):
        self._check_pos("let x = 1 @ 2;", interp.LangSyntaxError, 1, 11)

    def test_unterminated_string(self):
        self._check_pos('let s = "abc;', interp.LangSyntaxError, 1, 9)

    def test_invalid_escape(self):
        self._check_pos('let s = "ab\\qcd";', interp.LangSyntaxError, 1, 12)

    def test_keyword_as_ident(self):
        self._check_pos("let while = 1;", interp.LangSyntaxError, 1, 5)

    def test_missing_semicolon(self):
        self._check_pos("let a = 1 let b = 2;", interp.LangSyntaxError, 1, 11)

    def test_binop_type_error_pos(self):
        self._check_pos("let x = 1 +\n\"a\";", interp.LangTypeError, 1, 11)

    def test_zerodiv_pos(self):
        self._check_pos("print(1 / 0);", interp.LangZeroDivError, 1, 9)

    def test_arity_pos(self):
        self._check_pos('len("a", "b");', interp.LangArityError, 1, 4)

    def test_call_non_function_pos(self):
        self._check_pos("let n = 7; n(2);", interp.LangTypeError, 1, 13)

    def test_index_error_pos(self):
        self._check_pos("let a = [1];\nprint(a[5]);", interp.LangIndexError, 2, 8)

    def test_undefined_var_pos(self):
        self._check_pos("print(  missing);", interp.LangNameError, 1, 9)

    def test_unexpected_char_line2(self):
        self._check_pos("let ok = 1;\nlet bad = 2 & 3;", interp.LangSyntaxError, 2, 13)

    def test_bad_escape_line2(self):
        self._check_pos('let a = 1;\nlet s = "xy\\wz";', interp.LangSyntaxError, 2, 12)

    def test_index_anchor_multiline(self):
        self._check_pos("let xs = [1, 2, 3];\nlet z = xs[\n  7\n];",
                         interp.LangIndexError, 2, 11)


class TestSyntaxErrors(unittest.TestCase):
    def test_unbraced_if(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("if (true) print(1);")

    def test_trailing_comma(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("print(2,);")

    def test_assign_in_expr(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("let x = 0; print(x = 1);")

    def test_return_toplevel(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("return 3;")

    def test_continue_outside(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("if (true) { continue; }")

    def test_break_across_fn(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("while (true) { fn f() { break; } }")

    def test_compound_in_expr(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("print(let x = 1);")

    def test_no_catch_or_finally(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("try { 1; }")

    def test_throw_no_expr(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("throw;")

    def test_duplicate_param(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("fn f(a, a) { }")

    def test_duplicate_dict_key(self):
        with self.assertRaises(interp.LangSyntaxError):
            run('let d = {"a": 1, "a": 2};')

    def test_non_string_dict_key(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("let d = {1: 2};")


class TestRuntimeErrors(unittest.TestCase):
    def test_type_plus_mixed(self):
        with self.assertRaises(interp.LangTypeError):
            run('print(3 + "3");')

    def test_type_string_order(self):
        with self.assertRaises(interp.LangTypeError):
            run('print("aa" < "ab");')

    def test_type_bool_index(self):
        with self.assertRaises(interp.LangTypeError):
            run("let a = [1, 2]; print(a[true]);")

    def test_zerodiv_compound(self):
        with self.assertRaises(interp.LangZeroDivError):
            run("let x = 5; x %= 0;")

    def test_index_oob(self):
        with self.assertRaises(interp.LangIndexError):
            run('let s = "abc"; print(s[3]);')

    def test_index_negative(self):
        with self.assertRaises(interp.LangIndexError):
            run("let a = [1, 2]; print(a[0 - 1]);")

    def test_write_oob(self):
        with self.assertRaises(interp.LangIndexError):
            run("let a = [1, 2]; a[2] = 9;")

    def test_key_error_read(self):
        with self.assertRaises(interp.LangKeyError):
            run('let d = {"a": 1}; print(d["b"]);')

    def test_pop_empty(self):
        with self.assertRaises(interp.LangValueError):
            run("pop([]);")

    def test_chr_negative(self):
        with self.assertRaises(interp.LangValueError):
            run("print(chr(0 - 1));")

    def test_chr_too_large(self):
        with self.assertRaises(interp.LangValueError):
            run("print(chr(1114112));")

    def test_ord_not_one_char(self):
        with self.assertRaises(interp.LangValueError):
            run('print(ord("ab"));')

    def test_thrown_top_level(self):
        with self.assertRaises(interp.LangThrownError):
            run("throw 41;")

    def test_print_function_direct(self):
        with self.assertRaises(interp.LangTypeError):
            run("fn f() { } print(f);")

    def test_str_error_value(self):
        with self.assertRaises(interp.LangTypeError):
            run("try { 1 / 0; } catch (e) { print(str(e)); }")

    def test_len_on_int(self):
        with self.assertRaises(interp.LangTypeError):
            run("print(len(5));")

    def test_push_non_array(self):
        with self.assertRaises(interp.LangTypeError):
            run("push(1, 2);")

    def test_pop_non_array(self):
        with self.assertRaises(interp.LangTypeError):
            run("pop(1);")

    def test_keys_non_dict(self):
        with self.assertRaises(interp.LangTypeError):
            run("keys(1);")

    def test_has_non_dict(self):
        with self.assertRaises(interp.LangTypeError):
            run('has(1, "k");')

    def test_has_non_string_key(self):
        with self.assertRaises(interp.LangTypeError):
            run("let d = {}; has(d, 1);")

    def test_remove_non_dict(self):
        with self.assertRaises(interp.LangTypeError):
            run('remove(1, "k");')

    def test_remove_key_error(self):
        with self.assertRaises(interp.LangKeyError):
            run('let d = {}; remove(d, "k");')

    def test_ord_non_string(self):
        with self.assertRaises(interp.LangTypeError):
            run("print(ord(1));")

    def test_chr_non_int(self):
        with self.assertRaises(interp.LangTypeError):
            run('print(chr("a"));')

    def test_errkind_non_error(self):
        with self.assertRaises(interp.LangTypeError):
            run('print(errkind(1));')

    def test_index_dict_with_non_string(self):
        with self.assertRaises(interp.LangTypeError):
            run("let d = {}; d[1] = 2;")

    def test_slice_non_array_or_string(self):
        with self.assertRaises(interp.LangTypeError):
            run("let d = {}; print(d[:]);")

    def test_call_non_function(self):
        with self.assertRaises(interp.LangTypeError):
            run("let n = 7; n(2);")


class TestBuiltinArity(unittest.TestCase):
    def test_str_arity(self):
        with self.assertRaises(interp.LangArityError):
            run("print(str());")

    def test_len_arity(self):
        with self.assertRaises(interp.LangArityError):
            run('print(len("a", "b"));')

    def test_push_arity(self):
        with self.assertRaises(interp.LangArityError):
            run("push([1]);")

    def test_pop_arity(self):
        with self.assertRaises(interp.LangArityError):
            run("pop();")

    def test_keys_arity(self):
        with self.assertRaises(interp.LangArityError):
            run("keys({}, {});")


class TestBuiltinShadowing(unittest.TestCase):
    def test_shadow_builtin_global(self):
        self.assertEqual(run("let len = 44; print(len);"), ["44"])

    def test_shadow_builtin_in_block(self):
        self.assertEqual(run('{ let print = 1; } print("still works");'), ["still works"])

    def test_shadowed_builtin_redeclare(self):
        with self.assertRaises(interp.LangNameError):
            run("let str = 1; let str = 2;")

    def test_builtin_as_value(self):
        self.assertEqual(run('let p = print; p("via alias");'), ["via alias"])

    def test_print_pass_to_higher_order(self):
        src = """
        fn apply(f, x) { return f(x); }
        apply(print, "hello");
        """
        self.assertEqual(run(src), ["hello"])


class TestCatchParameterScope(unittest.TestCase):
    def test_catch_param_dup(self):
        with self.assertRaises(interp.LangNameError):
            run("try { throw 1; } catch (e) { let e = 2; }")

    def test_catch_param_shadows_outer(self):
        src = 'let e = "outer"; try { throw "inner"; } catch (e) { print(e); } print(e);'
        self.assertEqual(run(src), ["inner", "outer"])

    def test_catch_param_expires(self):
        with self.assertRaises(interp.LangNameError):
            run("try { throw 1; } catch (c) { } print(c);")


class TestParamLetConflict(unittest.TestCase):
    def test_param_let_conflict(self):
        with self.assertRaises(interp.LangNameError):
            run("fn f(a) { let a = 2; return a; } f(1);")


class TestPerformance(unittest.TestCase):
    def test_loop_10k_canary(self):
        src = """
        let s = 0;
        let i = 0;
        while (i < 10000) { s = s + i; i = i + 1; }
        print(s);
        """
        self.assertEqual(run(src), [str(sum(range(10000)))])

    def test_loop_200k_arith(self):
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
        self.assertEqual(run(src), [str(expected)])

    def test_100k_calls(self):
        src = """
        fn inc(x) { return x + 1; }
        let i = 0;
        while (i < 100000) { i = inc(i); }
        print(i);
        """
        self.assertEqual(run(src), ["100000"])

    def test_100k_array_push_sum(self):
        src = """
        let a = [];
        for (let i = 0; i < 100000; i += 1) { push(a, i); }
        let s = 0;
        for (v in a) { s += v; }
        print(s);
        """
        self.assertEqual(run(src), [str(sum(range(100000)))])

    def test_30k_try_throw_catch(self):
        src = """
        let n = 0;
        let i = 0;
        while (i < 30000) {
            try { throw 1; } catch (e) { n = n + e; }
            i = i + 1;
        }
        print(n);
        """
        self.assertEqual(run(src), ["30000"])

    def test_50k_string_concat(self):
        src = """
        let s = "";
        let i = 0;
        while (i < 10000) { s = s + "abcde"; i = i + 1; }
        print(len(s));
        """
        self.assertEqual(run(src), ["50000"])

    def test_deep_scope_reads(self):
        depth = 30
        src = "let v0 = 7;\n" + "{\n" * depth + """
        let s = 0;
        let i = 0;
        while (i < 50000) { s = s + v0; i = i + 1; }
        print(s);
        """ + "}\n" * depth
        self.assertEqual(run(src), [str(7 * 50000)])


class TestComments(unittest.TestCase):
    def test_comments(self):
        src = (
            "// leading comment\n"
            "let x = 1; // trailing\n"
            'let s = "not // a comment";\n'
            "print(s);\n"
            "// print(999);\n"
            "print(x);\n"
        )
        self.assertEqual(run(src), ["not // a comment", "1"])


class TestSpecExamples(unittest.TestCase):
    def test_tally_example(self):
        src = """
        fn tally() {
          let total = 0;
          fn add(xs) {
            for (v in xs) { total += v; }
            return total;
          }
          return add;
        }
        let t = tally();
        print(t([3, 4]));
        print(t([10]));
        """
        self.assertEqual(run(src), ["7", "17"])

    def test_slice_shallow_copy_example(self):
        src = """
        let inner = [1];
        let outer = [inner, 2];
        let copy = outer[:];
        push(copy, 3);
        copy[0][0] = 99;
        print(outer);
        print(copy);
        """
        self.assertEqual(run(src), ["[[99], 2]", "[[99], 2, 3]"])

    def test_compound_eval_order_example(self):
        src = """
        let a = [1, 2, 3];
        fn loud() { print("side effect"); return 10; }
        try { a[9] = loud(); } catch (e) { }
        try { a[9] += loud(); } catch (e) { }
        """
        self.assertEqual(run(src), ["side effect", "side effect"])

    def test_live_forin_example(self):
        src = """
        let a = [1, 2, 3];
        for (v in a) {
            if (v == 2) { push(a, 99); }
            print(v);
        }
        """
        self.assertEqual(run(src), ["1", "2", "3", "99"])

    def test_try_finally_continue_example(self):
        src = """
        fn k() {
            let i = 0;
            while (i < 3) {
                i += 1;
                try { throw "x"; } finally { continue; }
            }
            return i;
        }
        print(k());
        """
        self.assertEqual(run(src), ["3"])


class TestEdgeCases(unittest.TestCase):
    """Additional edge-case tests covering spec requirements."""

    def test_zero_pow_zero(self):
        self.assertEqual(run("print(0 ** 0);"), ["1"])

    def test_power_negative_exponent(self):
        with self.assertRaises(interp.LangValueError):
            run("print(5 ** -2);")

    def test_mixed_equality_diff_types(self):
        self.assertEqual(run("print(nil == false);"), ["false"])
        self.assertEqual(run('print("" == false);'), ["false"])
        self.assertEqual(run("print(0 == false);"), ["false"])

    def test_array_identity_equality(self):
        self.assertEqual(run("let a = [1]; let b = [1]; print(a == b);"), ["false"])
        self.assertEqual(run("let a = [1]; let b = a; print(a == b);"), ["true"])

    def test_dict_identity_equality(self):
        src = 'let d = {"a": 1}; let e = {"a": 1}; print(d == e);'
        self.assertEqual(run(src), ["false"])

    def test_forin_empty_array(self):
        self.assertEqual(run("for (v in []) { print(v); }"), [])

    def test_forin_empty_string(self):
        self.assertEqual(run('for (c in "") { print(c); }'), [])

    def test_slice_empty_array(self):
        self.assertEqual(run("print([][:]);"), ["[]"])
        self.assertEqual(run("print([][0:0]);"), ["[]"])

    def test_slice_empty_string(self):
        self.assertEqual(run('print(""[:]);'), [""])

    def test_slice_lo_greater_than_hi(self):
        self.assertEqual(run("let a = [1, 2, 3]; print(a[2:1]);"), ["[]"])
        self.assertEqual(run('print("abc"[2:1]);'), [""])

    def test_len_empty(self):
        self.assertEqual(run('print(len(""), len([]), len({}));'), ["0 0 0"])

    def test_dict_insertion_order_update(self):
        src = 'let d = {"a": 1, "b": 2}; d["a"] = 99; print(keys(d));'
        self.assertEqual(run(src), ['["a", "b"]'])

    def test_dict_insertion_order_remove_reinsert(self):
        src = 'let d = {"a": 1, "b": 2}; remove(d, "a"); d["a"] = 3; print(keys(d));'
        self.assertEqual(run(src), ['["b", "a"]'])

    def test_nested_slice_shallow_copy(self):
        src = """
        let inner = [1];
        let outer = [inner, 2];
        let c = outer[:];
        c[0][0] = 99;
        print(inner[0]);
        """
        self.assertEqual(run(src), ["99"])

    def test_compound_assign_chained_index(self):
        src = 'let d = {"a": [1, 2]}; d["a"][0] += 5; print(d["a"][0]);'
        self.assertEqual(run(src), ["6"])

    def test_string_concat(self):
        self.assertEqual(run('print("a" + "b" + "c");'), ["abc"])

    def test_string_index_oob(self):
        with self.assertRaises(interp.LangIndexError):
            run('let s = "ab"; print(s[2]);')

    def test_string_negative_index(self):
        with self.assertRaises(interp.LangIndexError):
            run('let s = "ab"; print(s[0 - 1]);')

    def test_for_step_scope_isolation(self):
        src = """
        let seen = [];
        for (let i = 0; i < 3; i += 1) {
            push(seen, i);
        }
        print(seen);
        """
        self.assertEqual(run(src), ["[0, 1, 2]"])

    def test_forin_type_error_non_iterable(self):
        with self.assertRaises(interp.LangTypeError):
            run("for (v in true) { }")

    def test_pop_returns_value(self):
        self.assertEqual(run("let a = [1, 2, 3]; print(pop(a), pop(a));"), ["3 2"])

    def test_push_returns_nil(self):
        self.assertEqual(run("let a = []; let r = push(a, 1); print(r);"), ["nil"])

    def test_remove_returns_value(self):
        src = 'let d = {"x": 99}; print(remove(d, "x"));'
        self.assertEqual(run(src), ["99"])

    def test_keys_returns_new_array(self):
        src = 'let d = {"a": 1}; let k = keys(d); push(k, 99); print(has(d, "99"));'
        self.assertEqual(run(src), ["false"])

    def test_forin_break(self):
        src = """
        let seen = [];
        for (v in [1, 2, 3, 4]) {
            if (v == 3) { break; }
            push(seen, v);
        }
        print(seen);
        """
        self.assertEqual(run(src), ["[1, 2]"])

    def test_forin_continue(self):
        src = """
        let seen = [];
        for (v in [1, 2, 3]) {
            if (v == 2) { continue; }
            push(seen, v);
        }
        print(seen);
        """
        self.assertEqual(run(src), ["[1, 3]"])

    def test_throw_non_error_top_level(self):
        with self.assertRaises(interp.LangThrownError):
            run('throw "uncaught";')

    def test_catch_syntax_error_not_catchable(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("try { let x = ; } catch (e) { }")

    def test_finally_break_in_for_loop(self):
        src = """
        let seen = [];
        for (let i = 0; i < 5; i += 1) {
            try {
                if (i == 2) { break; }
                push(seen, i);
            } finally { }
        }
        print(seen);
        """
        self.assertEqual(run(src), ["[0, 1]"])

    def test_finally_continue_in_for_loop(self):
        src = """
        let seen = [];
        for (let i = 0; i < 5; i += 1) {
            try {
                if (i % 2 == 0) { continue; }
                push(seen, i);
            } finally { }
        }
        print(seen);
        """
        self.assertEqual(run(src), ["[1, 3]"])

    def test_errkind_on_caught_error(self):
        src = """
        let ev = nil;
        fn trap_err() { try { 1 / 0; } catch (e) { ev = e; } }
        trap_err();
        print(errkind(ev));
        """
        self.assertEqual(run(src), ["zerodiv"])

    def test_print_builtin_variable_args(self):
        self.assertEqual(run("print();"), [""])
        self.assertEqual(run("print(1);"), ["1"])
        self.assertEqual(run("print(1, 2, 3, 4, 5);"), ["1 2 3 4 5"])

    def test_string_with_escapes_in_container(self):
        src = r'print(["tab\there", "new\nline"]);'
        expected = r'["tab\there", "new\nline"]'
        self.assertEqual(run(src), [expected])

    def test_bigint_arithmetic(self):
        src = "print(99999999999999999999 * 10000000000000000000);"
        self.assertEqual(run(src), ["999999999999999999990000000000000000000"])

    def test_while_true_break(self):
        src = """
        let n = 0;
        while (true) {
            n = n + 1;
            if (n > 3) { break; }
        }
        print(n);
        """
        self.assertEqual(run(src), ["4"])

    def test_nested_block_scopes_deep(self):
        src = "let a = 1;\n" + "{\n" * 10 + "let a = 99;\n" + "}\n" * 10 + "print(a);\n"
        self.assertEqual(run(src), ["1"])

    def test_call_with_side_effect_args(self):
        src = """
        let log = [];
        fn side(v) { push(log, v); return v; }
        fn add(a, b) { return a + b; }
        print(add(side(1), side(2)));
        print(log);
        """
        self.assertEqual(run(src), ["3", "[1, 2]"])


if __name__ == "__main__":
    unittest.main()
