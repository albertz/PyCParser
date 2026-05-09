
from __future__ import print_function

import ctypes
import helpers_test
from cparser import *
from cparser.interpreter import Interpreter
from helpers_test import parse, assert_equal

# All tests here require the global include wrappers (standard library headers).
_parse = lambda src: parse(src, withGlobalIncludeWrappers=True)


def _run(src):
    """Parse C source, register with interpreter, run f(), return result."""
    state = _parse(src)
    interp = Interpreter()
    interp.register(state)
    return interp.runFunc("f")


# ---------------------------------------------------------------------------
# stdlib.h: calloc
# ---------------------------------------------------------------------------

def test_calloc_returns_nonnull():
    """calloc must return a non-NULL pointer."""
    r = _run("""
    #include <stdlib.h>
    int f() {
        int *p = (int *)calloc(4, 4);
        int ok = (p != 0);
        free(p);
        return ok;
    }
    """)
    assert r.value == 1, "calloc returned NULL"


# ---------------------------------------------------------------------------
# stdlib.h: strtol
# ---------------------------------------------------------------------------

def test_strtol_decimal():
    """strtol("42", NULL, 10) must return 42."""
    r = _run("""
    #include <stdlib.h>
    long f() {
        return strtol("42", 0, 10);
    }
    """)
    assert r.value == 42, "strtol returned %r" % r


def test_strtol_negative():
    """strtol("-7", NULL, 10) must return -7."""
    r = _run("""
    #include <stdlib.h>
    long f() {
        return strtol("-7", 0, 10);
    }
    """)
    assert r.value == -7, "strtol returned %r" % r


# ---------------------------------------------------------------------------
# stdlib.h: strtod
# ---------------------------------------------------------------------------

def test_strtod_integer_string():
    """strtod("3.0", NULL) cast to int must equal 3."""
    r = _run("""
    #include <stdlib.h>
    int f() {
        double d = strtod("3.0", 0);
        return (int)d;
    }
    """)
    assert r.value == 3, "strtod returned %r" % r


# ---------------------------------------------------------------------------
# stdlib.h: qsort / bsearch (parse-level: just verify they are available)
# ---------------------------------------------------------------------------

def test_qsort_available():
    """qsort must be available in the stdlib.h wrapper (parse without error)."""
    _parse("""
    #include <stdlib.h>
    void f() {
        int arr[3];
        qsort(arr, 3, sizeof(int), 0);
    }
    """)


def test_bsearch_available():
    """bsearch must be available in the stdlib.h wrapper (parse without error)."""
    _parse("""
    #include <stdlib.h>
    void f() {
        int arr[3];
        int key = 1;
        bsearch(&key, arr, 3, sizeof(int), 0);
    }
    """)


# ---------------------------------------------------------------------------
# wchar.h: wcscmp / wcsncmp
# ---------------------------------------------------------------------------

def test_wcscmp_equal():
    """wcscmp of identical strings must return 0."""
    r = _run("""
    #include <wchar.h>
    int f() {
        return wcscmp(L"hello", L"hello");
    }
    """)
    assert r.value == 0, "wcscmp equal returned %r" % r


def test_wcscmp_different():
    """wcscmp of different strings must return non-zero."""
    r = _run("""
    #include <wchar.h>
    int f() {
        int c = wcscmp(L"abc", L"abd");
        return c != 0;
    }
    """)
    assert r.value == 1, "wcscmp different returned %r" % r


def test_wcsncmp_partial_match():
    """wcsncmp of strings equal in first 2 chars must return 0."""
    r = _run("""
    #include <wchar.h>
    int f() {
        return wcsncmp(L"abc", L"abX", 2);
    }
    """)
    assert r.value == 0, "wcsncmp partial match returned %r" % r


# ---------------------------------------------------------------------------
# wchar.h: wcscpy
# ---------------------------------------------------------------------------

def test_wcscpy_copies_string():
    """wcscpy must copy all characters including the first."""
    r = _run("""
    #include <stdlib.h>
    #include <wchar.h>
    int f() {
        wchar_t buf[10];
        wcscpy(buf, L"Hi");
        return buf[0] == L'H';
    }
    """)
    assert r.value == 1, "wcscpy first char wrong: %r" % r


# ---------------------------------------------------------------------------
# wchar.h: wcstol / wcstoul / wcstod
# ---------------------------------------------------------------------------

def test_wcstol_available():
    """wcstol must be available in the wchar.h wrapper (parse without error)."""
    _parse("""
    #include <wchar.h>
    void f() {
        wcstol(L"99", 0, 10);
    }
    """)


def test_wcstoul_available():
    """wcstoul must be available in the wchar.h wrapper (parse without error)."""
    _parse("""
    #include <wchar.h>
    void f() {
        wcstoul(L"255", 0, 10);
    }
    """)


def test_wcstod_available():
    """wcstod must be available in the wchar.h wrapper (parse without error)."""
    _parse("""
    #include <wchar.h>
    void f() {
        wcstod(L"2.0", 0);
    }
    """)


# ---------------------------------------------------------------------------
# locale.h: LC_* macros and setlocale
# ---------------------------------------------------------------------------

def test_locale_macros_defined():
    """LC_ALL and LC_CTYPE must be available as integer constants."""
    r = _run("""
    #include <locale.h>
    int f() {
        int a = LC_ALL;
        int b = LC_CTYPE;
        return a >= 0 && b >= 0;
    }
    """)
    assert r.value == 1, "LC_ALL/LC_CTYPE not non-negative: %r" % r


def test_setlocale_c_locale():
    """setlocale(LC_ALL, "C") must return a non-NULL pointer."""
    r = _run("""
    #include <locale.h>
    int f() {
        char *loc = setlocale(LC_ALL, "C");
        return loc != 0;
    }
    """)
    assert r.value == 1, "setlocale returned NULL"


# ---------------------------------------------------------------------------
# stdatomic.h: atomic_load / atomic_store macros
# ---------------------------------------------------------------------------

def test_atomic_store_and_load():
    """atomic_store then atomic_load must round-trip the value."""
    r = _run("""
    #include <stdatomic.h>
    int f() {
        int x = 0;
        atomic_store(&x, 42);
        return atomic_load(&x);
    }
    """)
    assert r.value == 42, "atomic round-trip returned %r" % r


def test_atomic_store_explicit_and_load_explicit():
    """atomic_store_explicit / atomic_load_explicit must also round-trip."""
    r = _run("""
    #include <stdatomic.h>
    int f() {
        int x = 0;
        atomic_store_explicit(&x, 7, 0);
        return atomic_load_explicit(&x, 0);
    }
    """)
    assert r.value == 7, "atomic_explicit round-trip returned %r" % r


if __name__ == "__main__":
    helpers_test.main(globals())
