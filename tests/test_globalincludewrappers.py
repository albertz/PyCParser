
from __future__ import print_function

import ctypes
import errno as _errno_mod
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
# stddef.h: offsetof
# ---------------------------------------------------------------------------

def test_offsetof_parses():
    """offsetof(struct, member) must parse without errors."""
    _parse("""
    #include <stddef.h>
    struct Foo { int a; int b; };
    size_t f() { return offsetof(struct Foo, b); }
    """)


def test_offsetof_returns_size_t():
    """offsetof must return a non-negative integer."""
    r = _run("""
    #include <stddef.h>
    struct Foo { int a; int b; };
    size_t f() { return offsetof(struct Foo, b); }
    """)
    assert r.value >= 0, "offsetof returned negative: %r" % r


def test_offsetof_second_field_greater_than_first():
    """offsetof of a later field must be >= offsetof of an earlier field."""
    r = _run("""
    #include <stddef.h>
    struct Foo { int a; int b; };
    int f() {
        int off_a = (int)offsetof(struct Foo, a);
        int off_b = (int)offsetof(struct Foo, b);
        return off_b > off_a;
    }
    """)
    assert r.value == 1, "offsetof(b) not > offsetof(a): %r" % r


# ---------------------------------------------------------------------------
# errno.h: errno constants
# ---------------------------------------------------------------------------

def test_erange_defined():
    """ERANGE must be available after #include <errno.h>."""
    r = _run("""
    #include <errno.h>
    int f() { return ERANGE; }
    """)
    assert r.value == _errno_mod.ERANGE, "ERANGE mismatch: %r" % r


def test_etimedout_defined():
    """ETIMEDOUT must be available after #include <errno.h>."""
    r = _run("""
    #include <errno.h>
    int f() { return ETIMEDOUT; }
    """)
    assert r.value == _errno_mod.ETIMEDOUT, "ETIMEDOUT mismatch: %r" % r


def test_eintr_defined():
    """EINTR must be available after #include <errno.h>."""
    r = _run("""
    #include <errno.h>
    int f() { return EINTR; }
    """)
    assert r.value == _errno_mod.EINTR, "EINTR mismatch: %r" % r


# ---------------------------------------------------------------------------
# limits.h: INT_MIN
# ---------------------------------------------------------------------------

def test_int_min_defined():
    """INT_MIN must be available after #include <limits.h>."""
    r = _run("""
    #include <limits.h>
    int f() { return INT_MIN; }
    """)
    import ctypes as _ct
    expected = _ct.c_int(-1 << (8 * _ct.sizeof(_ct.c_int) - 1)).value
    assert r.value == expected, "INT_MIN mismatch: %r" % r


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


def test_atomic_uintptr_t_is_pointer_sized():
    """atomic_uintptr_t must preserve full pointer values."""
    r = _run("""
    #include <stdint.h>
    #include <stdlib.h>
    #include <stdatomic.h>
    int f() {
        char *p = (char *)malloc(1);
        atomic_uintptr_t addr = 0;
        int ok;
        atomic_store(&addr, (uintptr_t)p);
        ok = (char *)atomic_load(&addr) == p;
        free(p);
        return ok;
    }
    """)
    assert r.value == 1, "atomic_uintptr_t truncated a pointer"


# ---------------------------------------------------------------------------
# stdbool.h: bool / true / false macros
# ---------------------------------------------------------------------------

def test_stdbool_true_is_one():
    """true from stdbool.h must evaluate to 1."""
    r = _run("""
    #include <stdbool.h>
    int f() {
        return true;
    }
    """)
    assert r.value == 1, "true != 1: %r" % r


def test_stdbool_false_is_zero():
    """false from stdbool.h must evaluate to 0."""
    r = _run("""
    #include <stdbool.h>
    int f() {
        return false;
    }
    """)
    assert r.value == 0, "false != 0: %r" % r


def test_stdbool_bool_as_type():
    """bool can be used as an int-compatible variable type."""
    r = _run("""
    #include <stdbool.h>
    int f() {
        bool x = true;
        bool y = false;
        return x + y;
    }
    """)
    assert r.value == 1, "bool arithmetic returned %r" % r


# ---------------------------------------------------------------------------
# time.h: struct timespec
# ---------------------------------------------------------------------------

def test_timespec_parse():
    """struct timespec should be parseable from time.h."""
    _parse("""
    #include <time.h>
    void f() {
        struct timespec ts;
        ts.tv_sec = 0;
        ts.tv_nsec = 0;
    }
    """)


# ---------------------------------------------------------------------------
# sys/time.h: struct timeval / gettimeofday
# ---------------------------------------------------------------------------

def test_timeval_parse():
    """struct timeval should be parseable from sys/time.h."""
    _parse("""
    #include <sys/time.h>
    void f() {
        struct timeval tv;
        tv.tv_sec = 0;
        tv.tv_usec = 0;
    }
    """)


def test_gettimeofday_returns_zero():
    """gettimeofday must parse and return 0 (success)."""
    r = _run("""
    #include <sys/time.h>
    int f() {
        struct timeval tv;
        return gettimeofday(&tv, 0);
    }
    """)
    assert r.value == 0, "gettimeofday returned %r" % r


# ---------------------------------------------------------------------------
# pthread.h: mutex/cond stubs
# ---------------------------------------------------------------------------

def test_pthread_mutex_stub():
    """pthread_mutex_init/lock/unlock/destroy must return 0."""
    r = _run("""
    #include <pthread.h>
    int f() {
        pthread_mutex_t m;
        int r = 0;
        r += pthread_mutex_init(&m, 0);
        r += pthread_mutex_lock(&m);
        r += pthread_mutex_unlock(&m);
        r += pthread_mutex_destroy(&m);
        return r;
    }
    """)
    assert r.value == 0, "pthread mutex stubs returned %r" % r


def test_pthread_cond_stub():
    """pthread_cond_init/signal/destroy must return 0."""
    r = _run("""
    #include <pthread.h>
    int f() {
        pthread_cond_t c;
        int r = 0;
        r += pthread_cond_init(&c, 0);
        r += pthread_cond_signal(&c);
        r += pthread_cond_destroy(&c);
        return r;
    }
    """)
    assert r.value == 0, "pthread cond stubs returned %r" % r


# ---------------------------------------------------------------------------
# locale.h: setlocale
# ---------------------------------------------------------------------------

def test_setlocale():
    """setlocale should be available and work."""
    r = _run("""
    #include <locale.h>
    int f() {
        char* loc = setlocale(LC_ALL, "");
        return loc != 0;
    }
    """)
    assert r.value == 1, "setlocale returned NULL"


# ---------------------------------------------------------------------------
# sys/stat.h: stat, fstat, macros
# ---------------------------------------------------------------------------

def test_sys_stat():
    """sys/stat.h should provide struct stat and macros."""
    _parse("""
    #include <sys/stat.h>
    void f() {
        struct stat st;
        st.st_mode = 0;
        int isreg = S_ISREG(st.st_mode);
        int isdir = S_ISDIR(st.st_mode);
        stat("test", &st);
        fstat(0, &st);
    }
    """)


# ---------------------------------------------------------------------------
# sys/types.h
# ---------------------------------------------------------------------------

def test_sys_types():
    """sys/types.h should provide common typedefs."""
    _parse("""
    #include <sys/types.h>
    void f() {
        dev_t dev;
        ino_t ino;
        mode_t mode;
        nlink_t nlink;
        uid_t uid;
        gid_t gid;
        off_t off;
        pid_t pid;
    }
    """)


# ---------------------------------------------------------------------------
# stdint.h: exact-width integer type sizes
# ---------------------------------------------------------------------------

def test_int8_t_is_one_byte():
    """int8_t must be exactly 1 byte wide, not 4 (old heuristic bug)."""
    r = _run("""
    #include <stdint.h>
    int f() { return (int)sizeof(int8_t); }
    """)
    assert r.value == 1, "sizeof(int8_t) expected 1, got %r" % r


def test_int16_t_is_two_bytes():
    """int16_t must be exactly 2 bytes wide."""
    r = _run("""
    #include <stdint.h>
    int f() { return (int)sizeof(int16_t); }
    """)
    assert r.value == 2, "sizeof(int16_t) expected 2, got %r" % r


def test_uint8_t_is_one_byte():
    """uint8_t must be exactly 1 byte wide."""
    r = _run("""
    #include <stdint.h>
    int f() { return (int)sizeof(uint8_t); }
    """)
    assert r.value == 1, "sizeof(uint8_t) expected 1, got %r" % r


def test_uint16_t_is_two_bytes():
    """uint16_t must be exactly 2 bytes wide."""
    r = _run("""
    #include <stdint.h>
    int f() { return (int)sizeof(uint16_t); }
    """)
    assert r.value == 2, "sizeof(uint16_t) expected 2, got %r" % r


def test_int8_t_pointer_arithmetic():
    """Pointer arithmetic on int8_t* must advance by 1 byte, not 4."""
    r = _run("""
    #include <stdint.h>
    int f() {
        int8_t arr[4];
        arr[0] = 10;
        arr[1] = 20;
        arr[2] = 30;
        arr[3] = 40;
        int8_t *p = arr;
        return (int)(*(p + 2));
    }
    """)
    assert r.value == 30, "int8_t pointer arithmetic: expected 30, got %r" % r


if __name__ == "__main__":
    helpers_test.main(globals())
