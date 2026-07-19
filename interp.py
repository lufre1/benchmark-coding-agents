import sys


class LangError(Exception):
    pass


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


KEYWORDS = {
    "let", "fn", "return", "if", "else", "while",
    "break", "continue", "true", "false", "nil",
}

TWO_CHAR_OPS = {"==", "!=", "<=", ">=", "&&", "||"}
ONE_CHAR_OPS = set("+-*/%<>=!(){};,",)

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
    while i < n:
        c = source[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "/" and i + 1 < n and source[i + 1] == "/":
            while i < n and source[i] != "\n":
                i += 1
            continue
        if _is_digit(c):
            j = i
            while j < n and _is_digit(source[j]):
                j += 1
            tokens.append(("int", int(source[i:j])))
            i = j
            continue
        if _is_ident_start(c):
            j = i
            while j < n and _is_ident_char(source[j]):
                j += 1
            word = source[i:j]
            tokens.append(("kw" if word in KEYWORDS else "ident", word))
            i = j
            continue
        if c == '"':
            i += 1
            parts = []
            while True:
                if i >= n:
                    raise LangSyntaxError("unterminated string literal")
                ch = source[i]
                if ch == '"':
                    i += 1
                    break
                if ch == "\n":
                    raise LangSyntaxError("newline in string literal")
                if ch == "\\":
                    if i + 1 >= n:
                        raise LangSyntaxError("unterminated string literal")
                    esc = ESCAPES.get(source[i + 1])
                    if esc is None:
                        raise LangSyntaxError(
                            "invalid escape \\%s" % source[i + 1])
                    parts.append(esc)
                    i += 2
                    continue
                parts.append(ch)
                i += 1
            tokens.append(("string", "".join(parts)))
            continue
        two = source[i:i + 2]
        if two in TWO_CHAR_OPS:
            tokens.append(("op", two))
            i += 2
            continue
        if c in ONE_CHAR_OPS:
            tokens.append(("op", c))
            i += 1
            continue
        raise LangSyntaxError("unexpected character %r" % c)
    tokens.append(("eof", None))
    return tokens


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
        kind, value = self.peek()
        if kind == "op" and value == op:
            self.pos += 1
            return True
        return False

    def expect_op(self, op):
        kind, value = self.advance()
        if kind != "op" or value != op:
            raise LangSyntaxError("expected %r, got %r" % (op, value))

    def expect_kw(self, kw):
        kind, value = self.advance()
        if kind != "kw" or value != kw:
            raise LangSyntaxError("expected %r, got %r" % (kw, value))

    def expect_ident(self):
        kind, value = self.advance()
        if kind != "ident":
            raise LangSyntaxError("expected identifier, got %r" % (value,))
        return value

    def at_kw(self, kw):
        kind, value = self.peek()
        return kind == "kw" and value == kw

    def parse_program(self):
        stmts = []
        while self.peek()[0] != "eof":
            stmts.append(self.statement())
        return stmts

    def statement(self):
        kind, value = self.peek()
        if kind == "kw":
            if value == "let":
                return self.let_stmt()
            if value == "fn":
                return self.fn_decl()
            if value == "if":
                return self.if_stmt()
            if value == "while":
                return self.while_stmt()
            if value == "return":
                return self.return_stmt()
            if value == "break":
                if self.loop_depth == 0:
                    raise LangSyntaxError("'break' outside loop")
                self.advance()
                self.expect_op(";")
                return ("break",)
            if value == "continue":
                if self.loop_depth == 0:
                    raise LangSyntaxError("'continue' outside loop")
                self.advance()
                self.expect_op(";")
                return ("continue",)
            if value in ("true", "false", "nil"):
                return self.expr_stmt()
            raise LangSyntaxError("unexpected keyword %r" % value)
        if kind == "op" and value == "{":
            return self.block()
        if kind == "ident" and self.peek(1) == ("op", "="):
            name = self.expect_ident()
            self.advance()
            expr = self.expression()
            self.expect_op(";")
            return ("assign", name, expr)
        return self.expr_stmt()

    def let_stmt(self):
        self.expect_kw("let")
        name = self.expect_ident()
        self.expect_op("=")
        expr = self.expression()
        self.expect_op(";")
        return ("let", name, expr)

    def fn_decl(self):
        self.expect_kw("fn")
        name = self.expect_ident()
        self.expect_op("(")
        params = []
        if not self.match_op(")"):
            while True:
                param = self.expect_ident()
                if param in params:
                    raise LangSyntaxError("duplicate parameter %r" % param)
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
        return ("fn", name, params, body[1])

    def if_stmt(self):
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
        return ("if", cond, then, otherwise)

    def while_stmt(self):
        self.expect_kw("while")
        self.expect_op("(")
        cond = self.expression()
        self.expect_op(")")
        self.loop_depth += 1
        body = self.block()
        self.loop_depth -= 1
        return ("while", cond, body)

    def return_stmt(self):
        if self.fn_depth == 0:
            raise LangSyntaxError("'return' outside function")
        self.expect_kw("return")
        if self.match_op(";"):
            return ("return", None)
        expr = self.expression()
        self.expect_op(";")
        return ("return", expr)

    def block(self):
        kind, value = self.peek()
        if kind != "op" or value != "{":
            raise LangSyntaxError("expected '{', got %r" % (value,))
        self.advance()
        stmts = []
        while not self.match_op("}"):
            if self.peek()[0] == "eof":
                raise LangSyntaxError("unterminated block")
            stmts.append(self.statement())
        return ("block", stmts)

    def expr_stmt(self):
        expr = self.expression()
        self.expect_op(";")
        return ("expr", expr)

    def expression(self):
        return self.or_expr()

    def or_expr(self):
        left = self.and_expr()
        while self.match_op("||"):
            left = ("or", left, self.and_expr())
        return left

    def and_expr(self):
        left = self.eq_expr()
        while self.match_op("&&"):
            left = ("and", left, self.eq_expr())
        return left

    def eq_expr(self):
        left = self.rel_expr()
        while True:
            kind, value = self.peek()
            if kind == "op" and value in ("==", "!="):
                self.advance()
                left = ("bin", value, left, self.rel_expr())
            else:
                return left

    def rel_expr(self):
        left = self.add_expr()
        while True:
            kind, value = self.peek()
            if kind == "op" and value in ("<", "<=", ">", ">="):
                self.advance()
                left = ("bin", value, left, self.add_expr())
            else:
                return left

    def add_expr(self):
        left = self.mul_expr()
        while True:
            kind, value = self.peek()
            if kind == "op" and value in ("+", "-"):
                self.advance()
                left = ("bin", value, left, self.mul_expr())
            else:
                return left

    def mul_expr(self):
        left = self.unary()
        while True:
            kind, value = self.peek()
            if kind == "op" and value in ("*", "/", "%"):
                self.advance()
                left = ("bin", value, left, self.unary())
            else:
                return left

    def unary(self):
        kind, value = self.peek()
        if kind == "op" and value in ("-", "!"):
            self.advance()
            return ("un", value, self.unary())
        return self.call()

    def call(self):
        expr = self.primary()
        while self.match_op("("):
            args = []
            if not self.match_op(")"):
                while True:
                    args.append(self.expression())
                    if self.match_op(")"):
                        break
                    self.expect_op(",")
            expr = ("call", expr, args)
        return expr

    def primary(self):
        kind, value = self.advance()
        if kind == "int" or kind == "string":
            return ("lit", value)
        if kind == "kw":
            if value == "true":
                return ("lit", True)
            if value == "false":
                return ("lit", False)
            if value == "nil":
                return ("lit", None)
            raise LangSyntaxError("unexpected keyword %r" % value)
        if kind == "ident":
            return ("var", value)
        if kind == "op" and value == "(":
            expr = self.expression()
            self.expect_op(")")
            return expr
        raise LangSyntaxError("unexpected token %r" % (value,))


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


class _Return(Exception):
    def __init__(self, value):
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


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
    return "function"


def _display(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return v
    if v is None:
        return "nil"
    raise LangTypeError("cannot convert a function to a string")


def _equals(a, b):
    ta = _type_name(a)
    if ta != _type_name(b):
        return False
    if ta == "function":
        return a is b
    return a == b


def _require_bool(v, context):
    if not isinstance(v, bool):
        raise LangTypeError("%s must be a bool, got %s" % (context, _type_name(v)))
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
        raise LangTypeError("'+' requires two ints or two strings, got %s and %s"
                            % (_type_name(l), _type_name(r)))
    if not _is_int(l) or not _is_int(r):
        raise LangTypeError("%r requires ints, got %s and %s"
                            % (op, _type_name(l), _type_name(r)))
    if op == "-":
        return l - r
    if op == "*":
        return l * r
    if r == 0:
        raise LangZeroDivError("division or modulo by zero")
    q = abs(l) // abs(r)
    if (l < 0) != (r < 0):
        q = -q
    if op == "/":
        return q
    return l - q * r


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
        return env.get(node[1])
    if tag == "bin":
        return _bin_op(node[1], _eval(node[2], env), _eval(node[3], env))
    if tag == "and":
        left = _require_bool(_eval(node[1], env), "'&&' operand")
        if not left:
            return False
        return _require_bool(_eval(node[2], env), "'&&' operand")
    if tag == "or":
        left = _require_bool(_eval(node[1], env), "'||' operand")
        if left:
            return True
        return _require_bool(_eval(node[2], env), "'||' operand")
    if tag == "un":
        value = _eval(node[2], env)
        if node[1] == "-":
            if not _is_int(value):
                raise LangTypeError("unary '-' requires an int, got %s"
                                    % _type_name(value))
            return -value
        return not _require_bool(value, "'!' operand")
    callee = _eval(node[1], env)
    args = [_eval(arg, env) for arg in node[2]]
    return _call(callee, args)


def _exec(node, env):
    tag = node[0]
    if tag == "expr":
        _eval(node[1], env)
    elif tag == "let":
        env.declare(node[1], _eval(node[2], env))
    elif tag == "assign":
        env.assign(node[1], _eval(node[2], env))
    elif tag == "block":
        child = Env(env)
        for stmt in node[1]:
            _exec(stmt, child)
    elif tag == "if":
        if _require_bool(_eval(node[1], env), "'if' condition"):
            _exec(node[2], env)
        elif node[3] is not None:
            _exec(node[3], env)
    elif tag == "while":
        while _require_bool(_eval(node[1], env), "'while' condition"):
            try:
                _exec(node[2], env)
            except _Break:
                break
            except _Continue:
                continue
    elif tag == "fn":
        env.declare(node[1], Function(node[1], node[2], node[3], env))
    elif tag == "return":
        raise _Return(None if node[1] is None else _eval(node[1], env))
    elif tag == "break":
        raise _Break()
    else:
        raise _Continue()


def run(source):
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    program = Parser(tokenize(source)).parse_program()

    out = []

    def _builtin_print(args):
        out.append(" ".join(_display(a) for a in args))
        return None

    def _builtin_str(args):
        return _display(args[0])

    def _builtin_len(args):
        if not isinstance(args[0], str):
            raise LangTypeError("len() requires a string, got %s"
                                % _type_name(args[0]))
        return len(args[0])

    builtins_env = Env()
    builtins_env.declare("print", Builtin("print", _builtin_print, None))
    builtins_env.declare("str", Builtin("str", _builtin_str, 1))
    builtins_env.declare("len", Builtin("len", _builtin_len, 1))

    globals_env = Env(builtins_env)
    for stmt in program:
        _exec(stmt, globals_env)
    return out
