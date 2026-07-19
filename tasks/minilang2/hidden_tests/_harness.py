"""Shared harness for the minilang2 hidden suite.

Not a test file (no test_ prefix) — imported by every test file.

Do NOT add a conftest.py to this directory: bench.py overwrites
hidden_tests/conftest.py with its own 5s-per-test SIGALRM watchdog at eval
time. This module supplies the finer-grained protection the suite actually
relies on:

- The import of the agent's `interp` module is guarded by its own 10s
  timer (a module-level infinite loop would otherwise hang pytest
  *collection*, where no per-test watchdog exists, and eat the whole eval
  budget). An unimportable module makes every test fail fast and
  individually via `require_interp()` instead of zeroing collection.
- Every `interp.run` call goes through `run()` below, which enforces a
  per-CALL budget (default 1s) that is tighter than the conftest's 5s
  alarm. 200 hanging tests then cost ~210s, safely under the 300s eval
  cap (measured against a hanging implementation on the bench machine).
  The timeout is raised as a BaseException subclass so that an
  implementation's over-broad `except Exception:` cannot swallow it.

Known blind spot (CPython 3.10, empirically verified on the bench
machine): SIGALRM is never checked inside a tight Python loop whose body
is only try/except with no function calls (`while True: try: x = 1
except Exception: pass`), so NO in-process watchdog — this one or the
conftest's — can interrupt that exact shape; only the bench's 300s eval
timeout ends it, losing junit.xml entirely. Any loop that makes at least
one function call per iteration (i.e. every realistic interpreter) is
interruptible. Accepted residual risk.
"""

import signal

import pytest


class _Timeout(BaseException):
    """BaseException so `except Exception` in the implementation can't eat it."""


_interp = None
_import_error = None


def _import_handler(signum, frame):
    raise _Timeout("import exceeded 10s")


_prev = signal.signal(signal.SIGALRM, _import_handler)
signal.setitimer(signal.ITIMER_REAL, 10.0)
try:
    import interp as _interp_module
    _interp = _interp_module
except _Timeout:
    _import_error = RuntimeError("import of interp.py timed out after 10s")
except BaseException as exc:  # SyntaxError from truncation, ImportError, ...
    _import_error = exc
finally:
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, _prev)


ERROR_NAMES = (
    "LangSyntaxError", "LangNameError", "LangTypeError", "LangArityError",
    "LangZeroDivError", "LangIndexError", "LangKeyError", "LangValueError",
    "LangThrownError",
)


def require_interp():
    if _interp is None:
        pytest.fail("interp.py failed to import: %r" % (_import_error,),
                    pytrace=False)
    return _interp


def run(src, seconds=1.0):
    """Call interp.run(src) under a per-call watchdog."""
    mod = require_interp()
    fn = getattr(mod, "run", None)
    if not callable(fn):
        pytest.fail("interp.run is missing or not callable", pytrace=False)

    def _handler(signum, frame):
        raise _Timeout()

    prev = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn(src)
    except _Timeout:
        pytest.fail("interp.run exceeded %.1fs" % seconds, pytrace=False)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prev)


def expect_error(src, err_name, line=None, col=None, seconds=1.0):
    """Assert run(src) raises exactly the named error class (optionally at
    an exact 1-based line/col). Also rejects an exception that is
    simultaneously an instance of an unrelated sibling error class, which
    catches entangled/aliased hierarchies."""
    mod = require_interp()
    err_cls = getattr(mod, err_name, None)
    if not isinstance(err_cls, type):
        pytest.fail("interp.py does not define class %s" % err_name,
                    pytrace=False)
    try:
        result = run(src, seconds=seconds)
    except err_cls as exc:
        for other in ERROR_NAMES:
            if other == err_name:
                continue
            other_cls = getattr(mod, other, None)
            if (isinstance(other_cls, type)
                    and not issubclass(err_cls, other_cls)
                    and not issubclass(other_cls, err_cls)
                    and isinstance(exc, other_cls)):
                pytest.fail("expected %s but the raised exception is also an "
                            "instance of unrelated class %s"
                            % (err_name, other), pytrace=False)
        if line is not None:
            got = (getattr(exc, "line", None), getattr(exc, "col", None))
            assert got == (line, col), (
                "expected %s at %d:%d, got position %r"
                % (err_name, line, col, got))
        return exc
    except Exception as exc:
        pytest.fail("expected %s, got %s: %s"
                    % (err_name, type(exc).__name__, exc), pytrace=False)
    pytest.fail("expected %s, but run() returned %r" % (err_name, result),
                pytrace=False)
