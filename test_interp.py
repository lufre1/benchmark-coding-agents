"""Unit tests for the MiniLang interpreter."""

import unittest

import interp


def run(src):
    return interp.run(src)


class TestLiteralsAndPrint(unittest.TestCase):
    def test_print_int(self):
        self.assertEqual(run("print(42);"), ["42"])
        self.assertEqual(run("print(0);"), ["0"])
        self.assertEqual(run("print(007);"), ["7"])

    def test_print_bool_nil(self):
        self.assertEqual(
            run("print(true); print(false); print(nil);"),
            ["true", "false", "nil"],
        )

    def test_print_multi_arg(self):
        self.assertEqual(
            run('print(1, 2, 3); print("a", true, nil); print();'),
            ["1 2 3", "a true nil", ""],
        )

    def test_string_escapes(self):
        self.assertEqual(run('print("a\\tb");'), ["a\tb"])
        self.assertEqual(run('print("say \\"hi\\"");'), ['say "hi"'])
        self.assertEqual(run('print("back\\\\slash");'), ["back\\slash"])
        self.assertEqual(run(r'print("a\nb");'), ["a\nb"])

    def test_rejected_string_escapes(self):
        for src in [r'let s = "a\qb";', r'let s = "a\x";']:
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

    def test_newline_escape_in_string(self):
        self.assertEqual(run(r'print("a\nb");'), ["a\nb"])
        self.assertEqual(run(r'print("a\nb"); print("c");'), ["a\nb", "c"])


class TestArithmetic(unittest.TestCase):
    def test_precedence(self):
        cases = [
            ("print(2 + 3 * 4);", ["14"]),
            ("print(20 - 6 / 2);", ["17"]),
            ("print(2 * 3 % 4);", ["2"]),
            ("print(100 - 10 - 5);", ["85"]),
        ]
        for src, expected in cases:
            with self.subTest(src=src):
                self.assertEqual(run(src), expected)

    def test_parentheses(self):
        self.assertEqual(run("print((2 + 3) * 4); print(2 * (3 + 4));"), ["20", "14"])

    def test_unary_minus(self):
        cases = [
            ("print(-5);", ["-5"]),
            ("print(-2 * 3 + 1);", ["-5"]),
            ("print(- -5);", ["5"]),
            ("print(-(2 + 3));", ["-5"]),
        ]
        for src, expected in cases:
            with self.subTest(src=src):
                self.assertEqual(run(src), expected)

    def test_truncating_division(self):
        self.assertEqual(
            run("print(7 / 2); print(-7 / 2); print(7 / -2); print(-7 / -2);"),
            ["3", "-3", "-3", "3"],
        )

    def test_modulo_sign(self):
        self.assertEqual(
            run("print(7 % 2); print(-7 % 2); print(7 % -2); print(-7 % -2);"),
            ["1", "-1", "1", "-1"],
        )
        self.assertEqual(
            run("let a = -17; let b = 5; print(a / b * b + a % b);"),
            ["-17"],
        )

    def test_bignum_factorial(self):
        src = """
        let n = 25;
        let acc = 1;
        let i = 1;
        while (i <= n) {
          acc = acc * i;
          i = i + 1;
        }
        print(acc);
        """
        self.assertEqual(run(src), ["15511210043330985984000000"])

    def test_large_numbers(self):
        src = "let x = 99999999999999999999; let y = 10000000000000000000; print(x + y);"
        self.assertEqual(run(src), ["109999999999999999999"])


class TestComparisonLogic(unittest.TestCase):
    def test_comparisons(self):
        cases = [
            ("print(1 < 2);", ["true"]),
            ("print(2 <= 2);", ["true"]),
            ("print(3 > 4);", ["false"]),
            ("print(5 >= 5);", ["true"]),
            ("print(2 < 2);", ["false"]),
            ("print(3 >= 4);", ["false"]),
        ]
        for src, expected in cases:
            with self.subTest(src=src):
                self.assertEqual(run(src), expected)

    def test_equality(self):
        cases = [
            ("print(1 == 1);", ["true"]),
            ("print(1 != 2);", ["true"]),
            ('print("a" == "a");', ["true"]),
            ('print(1 == "1");', ["false"]),
            ("print(true == 1);", ["false"]),
            ("print(nil == nil);", ["true"]),
            ("print(nil == false);", ["false"]),
            ("fn f() { } let g = f; print(f == g);", ["true"]),
            ("fn a() { } fn b() { } print(a == b);", ["false"]),
            ("print(true != false);", ["true"]),
            ("print(42 != 42);", ["false"]),
        ]
        for src, expected in cases:
            with self.subTest(src=src):
                self.assertEqual(run(src), expected)

    def test_short_circuit_and(self):
        self.assertEqual(
            run("print(false && 1 / 0 == 0);"),
            ["false"],
        )
        self.assertEqual(
            run("print(true && false);"),
            ["false"],
        )

    def test_short_circuit_or(self):
        self.assertEqual(
            run("print(true || 1 / 0 == 0);"),
            ["true"],
        )
        self.assertEqual(
            run("print(false || true);"),
            ["true"],
        )

    def test_short_circuit_combined(self):
        self.assertEqual(
            run("print(false && 1 / 0 == 0); print(true || 1 / 0 == 0); print(false && 5);"),
            ["false", "true", "false"],
        )

    def test_logic_type_errors(self):
        cases = ["print(1 && true);", "print(!1);", "print(true && 5);",
                 "print(nil || false);", "print(1 || 2);"]
        for src in cases:
            with self.subTest(src=src):
                with self.assertRaises(interp.LangTypeError):
                    run(src)

    def test_comparison_chain_type_error(self):
        with self.assertRaises(interp.LangTypeError):
            run("print(1 < 2 < 3);")
        self.assertEqual(run("print((1 < 2) == true);"), ["true"])


class TestVariablesScoping(unittest.TestCase):
    def test_let_and_assign(self):
        self.assertEqual(run("let x = 1; x = x + 1; print(x);"), ["2"])

    def test_block_shadowing(self):
        src = """
        let x = 1;
        {
          let x = 2;
          print(x);
        }
        print(x);
        """
        self.assertEqual(run(src), ["2", "1"])

    def test_deeply_nested_shadowing(self):
        src = """
        let x = 0;
        { let x = 1; { let x = 2; { let x = 3; print(x); } print(x); } print(x); }
        print(x);
        """
        self.assertEqual(run(src), ["3", "2", "1", "0"])

    def test_assign_nearest_enclosing(self):
        src = """
        let x = 1;
        {
          x = 5;
          { x = x + 1; }
        }
        print(x);
        """
        self.assertEqual(run(src), ["6"])

    def test_redeclaration_same_scope(self):
        cases = [
            "let x = 1; let x = 2;",
            "{ let y = 1; let y = 2; }",
            "fn f(a) { let a = 2; } f(1);",
            "fn g() { } fn g() { }",
        ]
        for src in cases:
            with self.subTest(src=src):
                with self.assertRaises(interp.LangNameError):
                    run(src)

    def test_fresh_scope_per_iteration(self):
        src = """
        let i = 0;
        while (i < 3) {
          let x = i * 10;
          print(x);
          i = i + 1;
        }
        """
        self.assertEqual(run(src), ["0", "10", "20"])

    def test_undefined_variable_read(self):
        with self.assertRaises(interp.LangNameError):
            run("print(x);")

    def test_undefined_variable_assign(self):
        with self.assertRaises(interp.LangNameError):
            run("x = 1;")

    def test_scope_boundary(self):
        with self.assertRaises(interp.LangNameError):
            run("{ let y = 1; } print(y);")


class TestControlFlow(unittest.TestCase):
    def test_if_basic(self):
        self.assertEqual(run("if (true) { print(1); }"), ["1"])
        self.assertEqual(run("if (false) { print(1); }"), [])

    def test_if_else(self):
        src = """
        let x = true;
        if (x) { print(1); } else { print(2); }
        """
        self.assertEqual(run(src), ["1"])
        self.assertEqual(run("if (false) { print(1); } else { print(2); }"), ["2"])

    def test_else_if_chain(self):
        src = """
        fn classify(n) {
          if (n < 0) {
            return "negative";
          } else if (n == 0) {
            return "zero";
          } else {
            return "positive";
          }
        }
        print(classify(-5)); print(classify(0)); print(classify(7));
        """
        self.assertEqual(run(src), ["negative", "zero", "positive"])

    def test_while(self):
        src = """
        let s = 0;
        let i = 1;
        while (i <= 10) {
          s = s + i;
          i = i + 1;
        }
        print(s);
        """
        self.assertEqual(run(src), ["55"])

    def test_while_false_body_not_executed(self):
        self.assertEqual(run("while (false) { print(999); } print(1);"), ["1"])

    def test_break(self):
        src = """
        let i = 0;
        while (i < 10) {
          i = i + 1;
          if (i == 5) { break; }
        }
        print(i);
        """
        self.assertEqual(run(src), ["5"])

    def test_continue(self):
        src = """
        let i = 0;
        let s = 0;
        while (i < 10) {
          i = i + 1;
          if (i % 2 == 0) { continue; }
          s = s + i;
        }
        print(s);
        """
        self.assertEqual(run(src), ["25"])

    def test_break_continue_combined(self):
        src = """
        let i = 0;
        let s = 0;
        while (true) {
          i = i + 1;
          if (i > 10) { break; }
          if (i % 2 == 0) { continue; }
          s = s + i;
        }
        print(s); print(i);
        """
        self.assertEqual(run(src), ["25", "11"])

    def test_condition_type_errors(self):
        cases = ["if (1) { }", 'while ("x") { }', "if (nil) { }", "while (1) { }"]
        for src in cases:
            with self.subTest(src=src):
                with self.assertRaises(interp.LangTypeError):
                    run(src)

    def test_nested_break_continue(self):
        src = """
        let i = 0;
        while (i < 3) {
          let j = 0;
          while (j < 3) {
            j = j + 1;
            if (j == 2) { break; }
          }
          i = i + 1;
        }
        print(i);
        """
        self.assertEqual(run(src), ["3"])


class TestFunctions(unittest.TestCase):
    def test_decl_and_call(self):
        self.assertEqual(
            run("fn add(a, b) { return a + b; } print(add(2, 3));"),
            ["5"],
        )

    def test_return_nil(self):
        self.assertEqual(
            run("fn f() { return; } fn g() { } print(f()); print(g());"),
            ["nil", "nil"],
        )

    def test_fib_recursion(self):
        src = """
        fn fib(n) {
          if (n < 2) { return n; }
          return fib(n - 1) + fib(n - 2);
        }
        print(fib(15));
        """
        self.assertEqual(run(src), ["610"])

    def test_mutual_recursion(self):
        src = """
        fn isEven(n) { if (n == 0) { return true; } return isOdd(n - 1); }
        fn isOdd(n) { if (n == 0) { return false; } return isEven(n - 1); }
        print(isEven(10)); print(isOdd(7));
        """
        self.assertEqual(run(src), ["true", "true"])

    def test_first_class_chained(self):
        src = """
        fn adder(n) {
          fn add(m) { return n + m; }
          return add;
        }
        print(adder(1)(2));
        fn apply(f, x) { return f(x); }
        print(apply(adder(10), 5));
        """
        self.assertEqual(run(src), ["3", "15"])

    def test_no_hoisting(self):
        with self.assertRaises(interp.LangNameError):
            run("print(f()); fn f() { return 1; }")

    def test_deep_recursion(self):
        src = """
        fn sum(n) {
          if (n == 0) { return 0; }
          return n + sum(n - 1);
        }
        print(sum(100));
        """
        self.assertEqual(run(src), ["5050"])

    def test_multi_param(self):
        src = "fn f(a, b, c) { return a + b + c; } print(f(1, 2, 3));"
        self.assertEqual(run(src), ["6"])

    def test_zero_param(self):
        src = "fn f() { return 42; } print(f());"
        self.assertEqual(run(src), ["42"])


class TestClosures(unittest.TestCase):
    def test_counter_factory(self):
        src = """
        fn makeCounter() {
          let n = 0;
          fn inc() { n = n + 1; return n; }
          return inc;
        }
        let c1 = makeCounter();
        let c2 = makeCounter();
        print(c1()); print(c1()); print(c2()); print(c1());
        """
        self.assertEqual(run(src), ["1", "2", "1", "3"])

    def test_shared_mutable_capture(self):
        src = """
        fn makeCell() {
          let n = 0;
          fn inc() { n = n + 1; return nil; }
          fn get() { return n; }
          fn pick(i) { if (i == 0) { return inc; } return get; }
          return pick;
        }
        let pick = makeCell();
        let inc = pick(0);
        let get = pick(1);
        inc(); inc(); inc();
        print(get());
        """
        self.assertEqual(run(src), ["3"])

    def test_late_binding(self):
        self.assertEqual(
            run("let x = 1; fn get() { return x; } x = 2; print(get());"),
            ["2"],
        )

    def test_closure_survives_scope(self):
        src = """
        fn make() {
          let secret = 41;
          fn reveal() { return secret + 1; }
          return reveal;
        }
        let f = make();
        print(f());
        """
        self.assertEqual(run(src), ["42"])

    def test_closure_over_param(self):
        src = """
        fn adder(n) {
          fn add(m) { n = n + m; return n; }
          return add;
        }
        let a = adder(100);
        print(a(1)); print(a(2));
        let b = adder(0);
        print(b(5)); print(a(3));
        """
        self.assertEqual(run(src), ["101", "103", "5", "106"])


class TestErrors(unittest.TestCase):
    def test_api_surface(self):
        self.assertTrue(issubclass(interp.LangSyntaxError, interp.LangError))
        self.assertTrue(issubclass(interp.LangNameError, interp.LangError))
        self.assertTrue(issubclass(interp.LangTypeError, interp.LangError))
        self.assertTrue(issubclass(interp.LangArityError, interp.LangError))
        self.assertTrue(issubclass(interp.LangZeroDivError, interp.LangError))
        self.assertTrue(issubclass(interp.LangError, Exception))
        self.assertTrue(callable(interp.run))

    def test_syntax_missing_semicolon(self):
        for src in ["let x = 1", "print(1)"]:
            with self.subTest(src=src):
                with self.assertRaises(interp.LangSyntaxError):
                    run(src)

    def test_syntax_structure(self):
        cases = [
            "if (true) print(1);",
            "let while = 1;",
            "print(1,)",
            "let x = 0; print(x = 1);",
            "fn f(a, a) { }",
        ]
        for src in cases:
            with self.subTest(src=src):
                with self.assertRaises(interp.LangSyntaxError):
                    run(src)

    def test_syntax_placement(self):
        cases = [
            "return 1;",
            "break;",
            "continue;",
            "if (true) { break; }",
            "while (true) { fn f() { break; } }",
        ]
        for src in cases:
            with self.subTest(src=src):
                with self.assertRaises(interp.LangSyntaxError):
                    run(src)

    def test_return_outside_fn(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("return;")

    def test_break_outside_loop(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("break;")

    def test_continue_outside_loop(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("continue;")

    def test_break_in_fn_inside_loop(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("while (true) { fn f() { break; } }")

    def test_continue_in_fn_inside_loop(self):
        with self.assertRaises(interp.LangSyntaxError):
            run("while (true) { fn f() { continue; } }")

    def test_type_errors(self):
        cases = [
            'print(1 + "a");',
            'print("a" < "b");',
            "print(-true);",
            "print(5(1));",
            'print("a" - "b");',
            "print(true + true);",
            'let x = "s"; x();',
        ]
        for src in cases:
            with self.subTest(src=src):
                with self.assertRaises(interp.LangTypeError):
                    run(src)

    def test_arity_errors(self):
        arity_cases = [
            "fn f(a, b) { return a; } f(1);",
            "fn f(a, b) { return a; } f(1, 2, 3);",
            "fn f() { return 1; } f(9);",
        ]
        for src in arity_cases:
            with self.subTest(src=src):
                with self.assertRaises(interp.LangArityError):
                    run(src)

    def test_zerodiv_errors(self):
        zerodiv_cases = [
            "print(1 / 0);",
            "print(1 % 0);",
            "let x = 5 / (3 - 3);",
        ]
        for src in zerodiv_cases:
            with self.subTest(src=src):
                with self.assertRaises(interp.LangZeroDivError):
                    run(src)

    def test_comment_in_program(self):
        src = (
            "// leading comment\n"
            "let x = 1; // trailing\n"
            'let s = "not // a comment";\n'
            "print(s);\n"
            "// print(999);\n"
            "print(x);\n"
        )
        self.assertEqual(run(src), ["not // a comment", "1"])

    def test_no_whitespace_program(self):
        self.assertEqual(run("let a=1;a=a+2;print(a);"), ["3"])

    def test_builtin_shadowing(self):
        self.assertEqual(run("let len = 10; print(len);"), ["10"])
        self.assertEqual(run('{ let print = 99; } print("ok");'), ["ok"])
        with self.assertRaises(interp.LangNameError):
            run("let print = 1; let print = 2;")

    def test_print_function_type_error(self):
        with self.assertRaises(interp.LangTypeError):
            run("fn f() { } print(f);")

    def test_str_function_type_error(self):
        with self.assertRaises(interp.LangTypeError):
            run("fn f() { } print(str(f));")

    def test_len_type_error(self):
        with self.assertRaises(interp.LangTypeError):
            run("print(len(5));")

    def test_len_arity_error(self):
        with self.assertRaises(interp.LangArityError):
            run('print(len("a", "b"));')

    def test_str_arity_error(self):
        with self.assertRaises(interp.LangArityError):
            run("print(str());")

    def test_builtin_print_as_value(self):
        self.assertEqual(run('let p = print; p("hi");'), ["hi"])

    def test_builtin_str_conversion(self):
        self.assertEqual(run('print(str(42) + "!");'), ["42!"])
        self.assertEqual(run("print(str(true), str(nil));"), ["true nil"])

    def test_builtin_len(self):
        self.assertEqual(run('print(len("hello"));'), ["5"])
        self.assertEqual(run('print(len(""));'), ["0"])


class TestPerformance(unittest.TestCase):
    def test_loop_100k(self):
        src = """
        let s = 0;
        let i = 0;
        while (i < 100000) {
          s = s + i;
          i = i + 1;
        }
        print(s);
        """
        self.assertEqual(run(src), ["4999950000"])

    def test_fib20(self):
        src = """
        fn fib(n) {
          if (n < 2) { return n; }
          return fib(n - 1) + fib(n - 2);
        }
        print(fib(20));
        """
        self.assertEqual(run(src), ["6765"])


if __name__ == "__main__":
    unittest.main()
