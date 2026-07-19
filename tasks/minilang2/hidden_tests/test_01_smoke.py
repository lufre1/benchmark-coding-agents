"""T1 smoke: API surface. 12 cases."""

import pytest

from _harness import ERROR_NAMES, require_interp, run


def test_import_ok():
    mod = require_interp()
    assert callable(getattr(mod, "run", None))


def test_run_returns_list():
    assert run("") == []


@pytest.mark.parametrize("name", ERROR_NAMES)
def test_error_class(name):
    mod = require_interp()
    cls = getattr(mod, name, None)
    assert isinstance(cls, type), "missing class %s" % name
    base = getattr(mod, "LangError", None)
    assert isinstance(base, type) and issubclass(base, Exception)
    assert issubclass(cls, base) and cls is not base


def test_error_classes_distinct():
    mod = require_interp()
    classes = [getattr(mod, n, None) for n in ERROR_NAMES]
    assert len(set(map(id, classes))) == len(ERROR_NAMES), (
        "error classes must be distinct classes")
