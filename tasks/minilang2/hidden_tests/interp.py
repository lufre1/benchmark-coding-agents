"""MiniLang2 interpreter - tree walking with tokenizer, recursive descent parser, evaluator."""

import sys

sys.setrecursionlimit(20000)


class LangError(Exception):
    def __init__(self, msg="", line=None, col=None):
        super().__init__(msg)
        self.line = line
        self.col = col


class LangSyntaxError(LangError):
    pass


class LangNameError(LangError):
    pass


class LangTypeError(LangError):
    pass


class LangArityError(LangError):
    pass


class LangZeroDivError(LangError):
    pass


class LangIndexError(LangError):
    pass


class LangKeyError(LangError):
    pass


class LangValueError(LangError):
    pass


class LangThrownError(LangError):
    pass


def _stamp(exc, pos):
    if exc.line is None:
        exc.line, exc.col = pos
    return exc


KEYWORDS = {
    "let", "fn", "return", "if", "else", "while", "for", "in",
    "break", "continue", "true", "false", "nil",
    "try", "catch", "finally", "throw",
}

TWO_CHAR_OPS = {"==", "!=", "<=", ">=", "&&", "||", "**", "+=", "-=", "*=", "/=", "%="}
ONE_CHAR_OPS = set("+-*/%<>=!(){}[],;:?")

ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t"}


def _is_digit(c):
    return "0" <= c <= "9"


def _is_ident_start(c):
    return c == "_" or "a" <= c <= "z" or "A" <= c <= "Z"


def _is_ident_char(c):
    return _is_ident_start(c) or _is_digit(c)


def tokenize(source):
    tokens = []
    i = 0
    n = len(source)
    line = 1
    col = 1

    def adv(k=1):
        nonlocal i, line, col
        for _ in range(k):
            if source[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < n:
        c = source[i]
        if c in " \t\r\n":
            adv()
            continue
        if c == "/" and i + 1 < n and source[i + 1] == "/":
            while i < n and source[i] != "\n":
                adv()
            continue
        tok_line, tok_col = line, col
        if _is_digit(c):
            j = i
            while j < n and _is_digit(source[j]):
                j += 1
            tokens.append(("int", int(source[i:j]), tok_line, tok_col))
            adv(j - i)
            continue
        if _is_ident_start(c):
            j = i
            while j < n and _is_ident_char(source[j]):
                j += 1
            word = source[i:j]
            kind = "kw" if word in KEYWORDS else "ident"
            tokens.append((kind, word, tok_line, tok_col))
            adv(j - i)
            continue
        if c == '"':
            adv()
            parts = []
            while True:
                if i >= n:
                    raise LangSyntaxError("unterminated string literal", tok_line, tok_col)
                ch = source[i]
                if ch == '"':
                    adv()
                    break
                if ch == "\n":
                    raise LangSyntaxError("newline in string literal", tok_line, tok_col)
                if ch == "\\":
                    esc_line, esc_col = line, col
                    if i + 1 >= n:
                        raise LangSyntaxError("unterminated string literal", tok_line, tok_col)
                    esc = ESCAPES.get(source[i + 1])
                    if esc is None:
                        raise LangSyntaxError("invalid escape \\%s" % source[i + 1], esc_line, esc_col)
                    parts.append(esc)
                    adv(2)
                    continue
                parts.append(ch)
                adv()
            tokens.append(("string", "".join(parts), tok_line, tok_col))
            continue
        two = source[i:i + 2]
        if two in TWO_CHAR_OPS:
            tokens.append(("op", two, tok_line, tok_col))
            adv(2)
            continue
        if c in ONE_CHAR_OPS:
            tokens.append(("op", c, tok_line, tok_col))
            adv()
            continue
        raise LangSyntaxError("unexpected character %r" % c, tok_line, tok_col)
    tokens.append(("eof", None, line, col))
    return tokens


ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%="}


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0
        self.fn_depth = 0
        self.loop_depth = 0

    def peek(self, offset=0):
        return self.toks[self.pos + offset]

    def advance(self):
        tok = self.toks[self.pos]
        self.pos += 1
        return tok

    def match_op(self, op):
        kind, value = self.peek()[:2]
        if kind == "op" and value == op:
            self.pos += 1
            return True
        return False

    def at_op(self, op):
        kind, value = self.peek()[:2]
        return kind == "op" and value == op

    def expect_op(self, op):
        kind, value, ln, cl = self.advance()
        if kind != "op" or value != op:
            raise LangSyntaxError("expected %r, got %r" % (op, value), ln, cl)

    def expect_kw(self, kw):
        kind, value, ln, cl = self.advance()
        if kind != "kw" or value != kw:
            raise LangSyntaxError("expected %r, got %r" % (kw, value), ln, cl)

    def expect_ident(self):
        kind, value, ln, cl = self.advance()
        if kind != "ident":
            raise LangSyntaxError("expected identifier, got %r" % (value,), ln, cl)
        return value, (ln, cl)

    def at_kw(self, kw):
        kind, value = self.peek()[:2]
        return kind == "kw" and value == kw

    def parse_program(self):
        stmts = []
        while self.peek()[0] != "eof":
            stmts.append(self.statement())
        return stmts

    def statement(self):
        kind, value, ln, cl = self.peek()
        if kind == "kw":
            if value == "let":
                return self.let_stmt()
            if value == "fn":
                return self.fn_decl()
            if value == "if":
                return self.if_stmt()
            if value == "while":
                return self.while_stmt()
            if value == "for":
                return self.for_stmt()
            if value == "try":
                return self.try_stmt()
            if value == "throw":
                return self.throw_stmt()
            if value == "return":
                return self.return_stmt()
            if value == "break":
                if self.loop_depth == 0:
                    raise LangSyntaxError("'break' outside loop", ln, cl)
                self.advance()
                self.expect_op(";")
                return ("break",)
            if value == "continue":
                if self.loop_depth == 0:
                    raise LangSyntaxError("'continue' outside loop", ln, cl)
                self.advance()
                self.expect_op(";")
                return ("continue",)
            if value in ("true", "false", "nil"):
                return self.expr_or_assign_stmt()
            raise LangSyntaxError("unexpected keyword %r" % value, ln, cl)
        if kind == "op" and value == "{":
            return self.block()
        return self.expr_or_assign_stmt()

    def expr_or_assign_stmt(self):
        expr = self.expression()
        kind, value, ln, cl = self.peek()
        if kind == "op" and value in ASSIGN_OPS:
            self.advance()
            target = self._validate_target(expr, (ln, cl))
            rhs = self.expression()
            self.expect_op(";")
            op = None if value == "=" else value[0]
            return ("assign", target, op, rhs, (ln, cl))
        self.expect_op(";")
        return ("expr", expr)

    def _validate_target(self, expr, op_pos):
        if expr[0] in ("var", "index"):
            return expr
        raise LangSyntaxError("invalid assignment target", *op_pos)

    def let_stmt(self):
        self.expect_kw("let")
        name, npos = self.expect_ident()
        self.expect_op("=")
        expr = self.expression()
        self.expect_op(";")
        return ("let", name, expr, npos)

    def fn_decl(self):
        self.expect_kw("fn")
        name, npos = self.expect_ident()
        self.expect_op("(")
        params = []
        if not self.match_op(")"):
            while True:
                param, ppos = self.expect_ident()
                if param in params:
                    raise LangSyntaxError("duplicate parameter %r" % param, *ppos)
                params.append(param)
                if self.match_op(")"):
                    break
                self.expect_op(",")
        saved_loop = self.loop_depth
        self.loop_depth = 0
        self.fn_depth += 1
        body = self.block()
        self.fn_depth -= 1
        self.loop_depth = saved_loop
        return ("fn", name, params, body[1], npos)

    def if_stmt(self):
        _, _, ln, cl = self.peek()
        self.expect_kw("if")
        self.expect_op("(")
        cond = self.expression()
        self.expect_op(")")
        then = self.block()
        otherwise = None
        if self.at_kw("else"):
            self.advance()
            if self.at_kw("if"):
                otherwise = self.if_stmt()
            else:
                otherwise = self.block()
        return ("if", cond, then, otherwise, (ln, cl))

    def while_stmt(self):
        _, _, ln, cl = self.peek()
        self.expect_kw("while")
        self.expect_op("(")
        cond = self.expression()
        self.expect_op(")")
        self.loop_depth += 1
        body = self.block()
        self.loop_depth -= 1
        return ("while", cond, body, (ln, cl))

    def for_stmt(self):
        _, _, ln, cl = self.peek()
        pos = (ln, cl)
        self.expect_kw("for")
        self.expect_op("(")
        if self.at_kw("let"):
            self.advance()
            name, _ = self.expect_ident()
            self.expect_op("=")
            init = self.expression()
            self.expect_op(";")
            cond = self.expression()
            self.expect_op(";")
            step = self.for_step()
            self.expect_op(")")
            self.loop_depth += 1
            body = self.block()
            self.loop_depth -= 1
            return ("for", name, init, cond, step, body[1], pos)
        name, _ = self.expect_ident()
        self.expect_kw("in")
        iter_expr = self.expression()
        self.expect_op(")")
        self.loop_depth += 1
        body = self.block()
        self.loop_depth -= 1
        return ("forin", name, iter_expr, body[1], pos)

    def for_step(self):
        expr = self.expression()
        kind, value, ln, cl = self.peek()
        if kind == "op" and value in ASSIGN_OPS:
            self.advance()
            target = self._validate_target(expr, (ln, cl))
            rhs = self.expression()
            op = None if value == "=" else value[0]
            return ("assign", target, op, rhs, (ln, cl))
        raise LangSyntaxError("for step must be an assignment", ln, cl)

    def try_stmt(self):
        _, _, ln, cl = self.peek()
        pos = (ln, cl)
        self.expect_kw("try")
        try_stmts = self.block()[1]
        catch_name = None
        catch_stmts = None
        finally_stmts = None
        if self.at_kw("catch"):
            self.advance()
            self.expect_op("(")
            catch_name, _ = self.expect_ident()
            self.expect_op(")")
            catch_stmts = self.block()[1]
        if self.at_kw("finally"):
            self.advance()
            finally_stmts = self.block()[1]
        if catch_name is None and finally_stmts is None:
            raise LangSyntaxError("'try' requires 'catch' or 'finally'", *pos)
        return ("try", try_stmts, catch_name, catch_stmts, finally_stmts, pos)

    def throw_stmt(self):
        _, _, ln, cl = self.peek()
        pos = (ln, cl)
        self.expect_kw("throw")
        kind, value, sln, scl = self.peek()
        if kind == "op" and value == ";":
            raise LangSyntaxError("'throw' requires an expression", sln, scl)
        expr = self.expression()
        self.expect_op(";")
        return ("throw", expr, pos)

    def return_stmt(self):
        kind, value, ln, cl = self.peek()
        if self.fn_depth == 0:
            raise LangSyntaxError("'return' outside function", ln, cl)
        self.expect_kw("return")
        if self.match_op(";"):
            return ("return", None)
        expr = self.expression()
        self.expect_op(";")
        return ("return", expr)

    def block(self):
        kind, value, ln, cl = self.peek()
        if kind != "op" or value != "{":
            raise LangSyntaxError("expected '{', got %r" % (value,), ln, cl)
        self.advance()
        stmts = []
        while not self.match_op("}"):
            if self.peek()[0] == "eof":
                _, _, eln, ecl = self.peek()
                raise LangSyntaxError("unterminated block", eln, ecl)
            stmts.append(self.statement())
        return ("block", stmts)

    def expression(self):
        return self.ternary()

    def ternary(self):
        cond = self.or_expr()
        kind, value, ln, cl = self.peek()
        if kind == "op" and value == "?":
            self.advance()
            a = self.ternary()
            self.expect_op(":")
            b = self.ternary()
            return ("ternary", cond, a, b, (ln, cl))
        return cond

    def or_expr(self):
        left = self.and_expr()
        while True:
            kind, value, ln, cl = self.peek()
            if kind == "op" and value == "||":
                self.advance()
                left = ("or", left, self.and_expr(), (ln, cl))
            else:
                return left

    def and_expr(self):
        left = self.eq_expr()
        while True:
            kind, value, ln, cl = self.peek()
            if kind == "op" and value == "&&":
                self.advance()
                left = ("and", left, self.eq_expr(), (ln, cl))
            else:
                return left

    def eq_expr(self):
        left = self.rel_expr()
        while True:
            kind, value, ln, cl = self.peek()
            if kind == "op" and value in ("==", "!="):
                self.advance()
                left = ("bin", value, left, self.rel_expr(), (ln, cl))
            else:
                return left

    def rel_expr(self):
        left = self.add_expr()
        while True:
            kind, value, ln, cl = self.peek()
            if kind == "op" and value in ("<", "<=", ">", ">="):
                self.advance()
                left = ("bin", value, left, self.add_expr(), (ln, cl))
            else:
                return left

    def add_expr(self):
        left = self.mul_expr()
        while True:
            kind, value, ln, cl = self.peek()
            if kind == "op" and value in ("+", "-"):
                self.advance()
                left = ("bin", value, left, self.mul_expr(), (ln, cl))
            else:
                return left

    def mul_expr(self):
        left = self.unary()
        while True:
            kind, value, ln, cl = self.peek()
            if kind == "op" and value in ("*", "/", "%"):
                self.advance()
                left = ("bin", value, left, self.unary(), (ln, cl))
            else:
                return left

    def unary(self):
        kind, value, ln, cl = self.peek()
        if kind == "op" and value in ("-", "!"):
            self.advance()
            return ("un", value, self.unary(), (ln, cl))
        return self.power()

    def power(self):
        base = self.postfix()
        kind, value, ln, cl = self.peek()
        if kind == "op" and value == "**":
            self.advance()
            return ("bin", "**", base, self.unary(), (ln, cl))
        return base

    def postfix(self):
        expr = self.primary()
        while True:
            kind, value, ln, cl = self.peek()
            if kind == "op" and value == "(":
                self.advance()
                args = []
                if not self.match_op(")"):
                    while True:
                        args.append(self.expression())
                        if self.match_op(")"):
                            break
                        self.expect_op(",")
                expr = ("call", expr, args, (ln, cl))
            elif kind == "op" and value == "[":
                self.advance()
                if self.match_op(":"):
                    hi = None if self.at_op("]") else self.expression()
                    self.expect_op("]")
                    expr = ("slice", expr, None, hi, (ln, cl))
                else:
                    first = self.expression()
                    if self.match_op(":"):
                        hi = None if self.at_op("]") else self.expression()
                        self.expect_op("]")
                        expr = ("slice", expr, first, hi, (ln, cl))
                    else:
                        self.expect_op("]")
                        expr = ("index", expr, first, (ln, cl))
            else:
                return expr

    def primary(self):
        kind, value, ln, cl = self.advance()
        if kind == "int" or kind == "string":
            return ("lit", value)
        if kind == "kw":
            if value == "true":
                return ("lit", True)
            if value == "false":
                return ("lit", False)
            if value == "nil":
                return ("lit", None)
            raise LangSyntaxError("unexpected keyword %r" % value, ln, cl)
        if kind == "ident":
            return ("var", value, (ln, cl))
        if kind == "op" and value == "(":
            expr = self.expression()
            self.expect_op(")")
            return ("group", expr)
        if kind == "op" and value == "[":
            elems = []
            if not self.match_op("]"):
                while True:
                    elems.append(self.expression())
                    if self.match_op("]"):
                        break
                    self.expect_op(",")
            return ("array", elems)
        if kind == "op" and value == "{":
            entries = []
            seen = set()
            if not self.match_op("}"):
                while True:
                    kkind, kvalue, kln, kcl = self.advance()
                    if kkind != "string":
                        raise LangSyntaxError("dict key must be a string literal", kln, kcl)
                    if kvalue in seen:
                        raise LangSyntaxError("duplicate dict key %r" % kvalue, kln, kcl)
                    seen.add(kvalue)
                    self.expect_op(":")
                    entries.append((kvalue, self.expression()))
                    if self.match_op("}"):
                        break
                    self.expect_op(",")
            return ("dict", entries)
        raise LangSyntaxError("unexpected token %r" % (value,), ln, cl)


class Env:
    __slots__ = ("vars", "parent")

    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def declare(self, name, value):
        if name in self.vars:
            raise LangNameError("duplicate declaration of %r" % name)
        self.vars[name] = value

    def get(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise LangNameError("undefined variable %r" % name)

    def assign(self, name, value):
        env = self
        while env is not None:
            if name in env.vars:
                env.vars[name] = value
                return
            env = env.parent
        raise LangNameError("undefined variable %r" % name)


class Function:
    __slots__ = ("name", "params", "body", "closure")

    def __init__(self, name, params, body, closure):
        self.name = name
        self.params = params
        self.body = body
        self.closure = closure


class Builtin:
    __slots__ = ("name", "fn", "arity")

    def __init__(self, name, fn, arity):
        self.name = name
        self.fn = fn
        self.arity = arity


class ErrorValue:
    __slots__ = ("kind", "exc")

    def __init__(self, kind, exc):
        self.kind = kind
        self.exc = exc


_KIND = {
    LangNameError: "name",
    LangTypeError: "type",
    LangArityError: "arity",
    LangZeroDivError: "zerodiv",
    LangIndexError: "index",
    LangKeyError: "key",
    LangValueError: "value",
}


class _Return(Exception):
    def __init__(self, value):
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _Thrown(Exception):
    def __init__(self, value, pos):
        self.value = value
        self.pos = pos


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _type_name(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, str):
        return "string"
    if v is None:
        return "nil"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "dict"
    if isinstance(v, ErrorValue):
        return "error"
    return "function"


def _escape(s):
    return (s.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\t", "\\t"))


def _display(v, nested=False):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return '"%s"' % _escape(v) if nested else v
    if v is None:
        return "nil"
    if isinstance(v, list):
        return "[%s]" % ", ".join(_display(e, True) for e in v)
    if isinstance(v, dict):
        return "{%s}" % ", ".join(
            '"%s": %s' % (_escape(k), _display(e, True))
            for k, e in v.items())
    raise LangTypeError("cannot convert a %s value to a string"
                        % _type_name(v))


def _equals(a, b):
    ta = _type_name(a)
    if ta != _type_name(b):
        return False
    if ta in ("function", "array", "dict", "error"):
        return a is b
    return a == b


def _require_bool(v, context):
    if not isinstance(v, bool):
        raise LangTypeError("%s must be a bool, got %s"
                            % (context, _type_name(v)))
    return v


def _bin_op(op, l, r):
    if op == "==":
        return _equals(l, r)
    if op == "!=":
        return not _equals(l, r)
    if op in ("<", "<=", ">", ">="):
        if not _is_int(l) or not _is_int(r):
            raise LangTypeError("comparison requires ints, got %s and %s"
                                % (_type_name(l), _type_name(r)))
        if op == "<":
            return l < r
        if op == "<=":
            return l <= r
        if op == ">":
            return l > r
        return l >= r
    if op == "+":
        if _is_int(l) and _is_int(r):
            return l + r
        if isinstance(l, str) and isinstance(r, str):
            return l + r
        raise LangTypeError("'+' requires two ints or two strings, "
                            "got %s and %s" % (_type_name(l), _type_name(r)))
    if not _is_int(l) or not _is_int(r):
        raise LangTypeError("%r requires ints, got %s and %s"
                            % (op, _type_name(l), _type_name(r)))
    if op == "-":
        return l - r
    if op == "*":
        return l * r
    if op == "**":
        if r < 0:
            raise LangValueError("negative exponent")
        return l ** r
    if r == 0:
        raise LangZeroDivError("division or modulo by zero")
    q = abs(l) // abs(r)
    if (l < 0) != (r < 0):
        q = -q
    if op == "/":
        return q
    return l - q * r


def _index_read(obj, idx):
    if isinstance(obj, (list, str)) and not isinstance(obj, bool):
        if not _is_int(idx):
            raise LangTypeError("array/string index must be an int, got %s"
                                % _type_name(idx))
        if idx < 0 or idx >= len(obj):
            raise LangIndexError("index %d out of range" % idx)
        return obj[idx]
    if isinstance(obj, dict):
        if not isinstance(idx, str):
            raise LangTypeError("dict key must be a string, got %s"
                                % _type_name(idx))
        if idx not in obj:
            raise LangKeyError("missing key %r" % idx)
        return obj[idx]
    raise LangTypeError("cannot index a %s value" % _type_name(obj))


def _index_write(obj, idx, value):
    if isinstance(obj, list):
        if not _is_int(idx):
            raise LangTypeError("array index must be an int, got %s"
                                % _type_name(idx))
        if idx < 0 or idx >= len(obj):
            raise LangIndexError("index %d out of range" % idx)
        obj[idx] = value
        return
    if isinstance(obj, str):
        raise LangTypeError("strings are immutable")
    if isinstance(obj, dict):
        if not isinstance(idx, str):
            raise LangTypeError("dict key must be a string, got %s"
                                % _type_name(idx))
        obj[idx] = value
        return
    raise LangTypeError("cannot index a %s value" % _type_name(obj))


def _slice(obj, lo, hi):
    if not isinstance(obj, (list, str)) or isinstance(obj, bool):
        raise LangTypeError("cannot slice a %s value" % _type_name(obj))
    if lo is None:
        lo = 0
    elif not _is_int(lo):
        raise LangTypeError("slice bound must be an int, got %s"
                            % _type_name(lo))
    if hi is None:
        hi = len(obj)
    elif not _is_int(hi):
        raise LangTypeError("slice bound must be an int, got %s"
                            % _type_name(hi))
    if lo < 0 or hi < 0:
        raise LangIndexError("negative slice bound")
    lo = min(lo, len(obj))
    hi = min(hi, len(obj))
    if lo > hi:
        return [] if isinstance(obj, list) else ""
    if isinstance(obj, list):
        return list(obj[lo:hi])
    return obj[lo:hi]


def _call(callee, args):
    if isinstance(callee, Builtin):
        if callee.arity is not None and len(args) != callee.arity:
            raise LangArityError("%s() takes %d argument(s), got %d"
                                 % (callee.name, callee.arity, len(args)))
        return callee.fn(args)
    if not isinstance(callee, Function):
        raise LangTypeError("cannot call a %s value" % _type_name(callee))
    if len(args) != len(callee.params):
        raise LangArityError("%s() takes %d argument(s), got %d"
                             % (callee.name, len(callee.params), len(args)))
    env = Env(callee.closure)
    for param, arg in zip(callee.params, args):
        env.declare(param, arg)
    try:
        for stmt in callee.body:
            _exec(stmt, env)
    except _Return as ret:
        return ret.value
    return None


def _eval(node, env):
    tag = node[0]
    if tag == "lit":
        return node[1]
    if tag == "var":
        try:
            return env.get(node[1])
        except LangError as e:
            raise _stamp(e, node[2])
    if tag == "group":
        return _eval(node[1], env)
    if tag == "bin":
        l = _eval(node[2], env)
        r = _eval(node[3], env)
        try:
            return _bin_op(node[1], l, r)
        except LangError as e:
            raise _stamp(e, node[4])
    if tag == "and":
        try:
            left = _require_bool(_eval(node[1], env), "'&&' operand")
        except LangError as e:
            raise _stamp(e, node[3])
        if not left:
            return False
        try:
            return _require_bool(_eval(node[2], env), "'&&' operand")
        except LangError as e:
            raise _stamp(e, node[3])
    if tag == "or":
        try:
            left = _require_bool(_eval(node[1], env), "'||' operand")
        except LangError as e:
            raise _stamp(e, node[3])
        if left:
            return True
        try:
            return _require_bool(_eval(node[2], env), "'||' operand")
        except LangError as e:
            raise _stamp(e, node[3])
    if tag == "un":
        value = _eval(node[2], env)
        try:
            if node[1] == "-":
                if not _is_int(value):
                    raise LangTypeError("unary '-' requires an int, got %s"
                                        % _type_name(value))
                return -value
            return not _require_bool(value, "'!' operand")
        except LangError as e:
            raise _stamp(e, node[3])
    if tag == "ternary":
        cond = _eval(node[1], env)
        if not isinstance(cond, bool):
            raise LangTypeError("ternary condition must be a bool, got %s"
                                % _type_name(cond), *node[4])
        return _eval(node[2] if cond else node[3], env)
    if tag == "call":
        callee = _eval(node[1], env)
        args = [_eval(a, env) for a in node[2]]
        try:
            return _call(callee, args)
        except LangError as e:
            raise _stamp(e, node[3])
    if tag == "index":
        obj = _eval(node[1], env)
        idx = _eval(node[2], env)
        try:
            return _index_read(obj, idx)
        except LangError as e:
            raise _stamp(e, node[3])
    if tag == "slice":
        obj = _eval(node[1], env)
        lo = None if node[2] is None else _eval(node[2], env)
        hi = None if node[3] is None else _eval(node[3], env)
        try:
            return _slice(obj, lo, hi)
        except LangError as e:
            raise _stamp(e, node[4])
    if tag == "array":
        return [_eval(e, env) for e in node[1]]
    if tag == "dict":
        result = {}
        for key, expr in node[1]:
            result[key] = _eval(expr, env)
        return result


def _exec_assign(node, env):
    _, target, op, rhs_expr, op_pos = node
    if target[0] == "var":
        name = target[1]
        rhs = _eval(rhs_expr, env)
        if op is None:
            try:
                env.assign(name, rhs)
            except LangError as e:
                raise _stamp(e, target[2])
        else:
            try:
                cur = env.get(name)
            except LangError as e:
                raise _stamp(e, target[2])
            try:
                new = _bin_op(op, cur, rhs)
            except LangError as e:
                raise _stamp(e, op_pos)
            env.assign(name, new)
        return
    obj = _eval(target[1], env)
    idx = _eval(target[2], env)
    rhs = _eval(rhs_expr, env)
    if op is None:
        try:
            _index_write(obj, idx, rhs)
        except LangError as e:
            raise _stamp(e, target[3])
    else:
        try:
            cur = _index_read(obj, idx)
        except LangError as e:
            raise _stamp(e, target[3])
        try:
            new = _bin_op(op, cur, rhs)
        except LangError as e:
            raise _stamp(e, op_pos)
        try:
            _index_write(obj, idx, new)
        except LangError as e:
            raise _stamp(e, target[3])


def _run_catch(name, stmts, env, bound):
    cenv = Env(env)
    cenv.declare(name, bound)
    try:
        for s in stmts:
            _exec(s, cenv)
        return None
    except (_Thrown, LangError, _Return, _Break, _Continue) as exc:
        return exc


def _exec_try(node, env):
    _, try_stmts, catch_name, catch_stmts, finally_stmts, _pos = node
    pending = None
    try:
        child = Env(env)
        for s in try_stmts:
            _exec(s, child)
    except _Thrown as exc:
        if catch_name is not None:
            pending = _run_catch(catch_name, catch_stmts, env, exc.value)
        else:
            pending = exc
    except LangError as exc:
        if catch_name is not None:
            kind = _KIND.get(type(exc))
            if kind is None:
                pending = exc
            else:
                pending = _run_catch(catch_name, catch_stmts, env,
                                     ErrorValue(kind, exc))
        else:
            pending = exc
    except (_Return, _Break, _Continue) as cf:
        pending = cf
    if finally_stmts is not None:
        fenv = Env(env)
        for s in finally_stmts:
            _exec(s, fenv)
    if pending is not None:
        raise pending


def _exec(node, env):
    tag = node[0]
    if tag == "expr":
        _eval(node[1], env)
    elif tag == "let":
        value = _eval(node[2], env)
        try:
            env.declare(node[1], value)
        except LangError as e:
            raise _stamp(e, node[3])
    elif tag == "assign":
        _exec_assign(node, env)
    elif tag == "block":
        child = Env(env)
        for stmt in node[1]:
            _exec(stmt, child)
    elif tag == "if":
        cond = _eval(node[1], env)
        if not isinstance(cond, bool):
            raise LangTypeError("'if' condition must be a bool, got %s"
                                % _type_name(cond), *node[4])
        if cond:
            _exec(node[2], env)
        elif node[3] is not None:
            _exec(node[3], env)
    elif tag == "while":
        while True:
            cond = _eval(node[1], env)
            if not isinstance(cond, bool):
                raise LangTypeError("'while' condition must be a bool, got %s"
                                    % _type_name(cond), *node[3])
            if not cond:
                break
            try:
                _exec(node[2], env)
            except _Break:
                break
            except _Continue:
                continue
    elif tag == "for":
        _, name, init, cond, step, body, pos = node
        env_i = Env(env)
        env_i.declare(name, _eval(init, env))
        while True:
            c = _eval(cond, env_i)
            if not isinstance(c, bool):
                raise LangTypeError("'for' condition must be a bool, got %s"
                                    % _type_name(c), *pos)
            if not c:
                break
            try:
                child = Env(env_i)
                for s in body:
                    _exec(s, child)
            except _Break:
                break
            except _Continue:
                pass
            new_env = Env(env)
            new_env.vars[name] = env_i.vars[name]
            _exec(step, new_env)
            env_i = new_env
    elif tag == "forin":
        _, name, iter_expr, body, pos = node
        container = _eval(iter_expr, env)
        if not isinstance(container, (list, str)) or isinstance(container, bool):
            raise LangTypeError("'for (x in e)' requires an array or string, "
                                "got %s" % _type_name(container), *pos)
        idx = 0
        while idx < len(container):
            ienv = Env(env)
            ienv.vars[name] = container[idx]
            try:
                child = Env(ienv)
                for s in body:
                    _exec(s, child)
            except _Break:
                break
            except _Continue:
                pass
            idx += 1
    elif tag == "try":
        _exec_try(node, env)
    elif tag == "throw":
        value = _eval(node[1], env)
        if isinstance(value, ErrorValue):
            raise value.exc
        raise _Thrown(value, node[2])
    elif tag == "fn":
        try:
            env.declare(node[1], Function(node[1], node[2], node[3], env))
        except LangError as e:
            raise _stamp(e, node[4])
    elif tag == "return":
        raise _Return(None if node[1] is None else _eval(node[1], env))
    elif tag == "break":
        raise _Break()
    else:
        raise _Continue()


def run(source):
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))
    program = Parser(tokenize(source)).parse_program()

    out = []

    def _b_print(args):
        out.append(" ".join(_display(a) for a in args))
        return None

    def _b_str(args):
        return _display(args[0])

    def _b_len(args):
        x = args[0]
        if isinstance(x, bool) or not isinstance(x, (str, list, dict)):
            raise LangTypeError("len() requires a string, array, or dict, "
                                "got %s" % _type_name(x))
        return len(x)

    def _b_push(args):
        a, v = args
        if not isinstance(a, list):
            raise LangTypeError("push() requires an array, got %s"
                                % _type_name(a))
        a.append(v)
        return None

    def _b_pop(args):
        a = args[0]
        if not isinstance(a, list):
            raise LangTypeError("pop() requires an array, got %s"
                                % _type_name(a))
        if not a:
            raise LangValueError("pop() of an empty array")
        return a.pop()

    def _b_keys(args):
        d = args[0]
        if not isinstance(d, dict):
            raise LangTypeError("keys() requires a dict, got %s"
                                % _type_name(d))
        return list(d.keys())

    def _b_has(args):
        d, k = args
        if not isinstance(d, dict):
            raise LangTypeError("has() requires a dict, got %s"
                                % _type_name(d))
        if not isinstance(k, str):
            raise LangTypeError("has() key must be a string, got %s"
                                % _type_name(k))
        return k in d

    def _b_remove(args):
        d, k = args
        if not isinstance(d, dict):
            raise LangTypeError("remove() requires a dict, got %s"
                                % _type_name(d))
        if not isinstance(k, str):
            raise LangTypeError("remove() key must be a string, got %s"
                                % _type_name(k))
        if k not in d:
            raise LangKeyError("missing key %r" % k)
        return d.pop(k)

    def _b_ord(args):
        s = args[0]
        if not isinstance(s, str):
            raise LangTypeError("ord() requires a string, got %s"
                                % _type_name(s))
        if len(s) != 1:
            raise LangValueError("ord() requires a one-character string")
        return ord(s)

    def _b_chr(args):
        n = args[0]
        if not _is_int(n):
            raise LangTypeError("chr() requires an int, got %s"
                                % _type_name(n))
        if n < 0 or n > 1114111:
            raise LangValueError("chr() code point out of range")
        return chr(n)

    def _b_errkind(args):
        e = args[0]
        if not isinstance(e, ErrorValue):
            raise LangTypeError("errkind() requires an error value, got %s"
                                % _type_name(e))
        return e.kind

    builtins_env = Env()
    builtins_env.declare("print", Builtin("print", _b_print, None))
    builtins_env.declare("str", Builtin("str", _b_str, 1))
    builtins_env.declare("len", Builtin("len", _b_len, 1))
    builtins_env.declare("push", Builtin("push", _b_push, 2))
    builtins_env.declare("pop", Builtin("pop", _b_pop, 1))
    builtins_env.declare("keys", Builtin("keys", _b_keys, 1))
    builtins_env.declare("has", Builtin("has", _b_has, 2))
    builtins_env.declare("remove", Builtin("remove", _b_remove, 2))
    builtins_env.declare("ord", Builtin("ord", _b_ord, 1))
    builtins_env.declare("chr", Builtin("chr", _b_chr, 1))
    builtins_env.declare("errkind", Builtin("errkind", _b_errkind, 1))

    globals_env = Env(builtins_env)
    try:
        for stmt in program:
            _exec(stmt, globals_env)
    except _Thrown as t:
        raise LangThrownError("uncaught throw of a %s value"
                              % _type_name(t.value), *t.pos)
    return out