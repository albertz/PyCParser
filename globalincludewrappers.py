# PyCParser - global include wrappers
# by Albert Zeyer, 2011
# code under BSD 2-Clause License

from .cparser import *
from .interpreter import CWrapValue, _ctype_ptr_get_value, Helpers, CAbortException
import ctypes
import _ctypes
import os
import sys
import typing

if typing.TYPE_CHECKING:
    from . import interpreter

PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] >= 3

libc = ctypes.CDLL(None)


def _fixCType(stateStruct, t):
    if t is ctypes.c_void_p: t = CBuiltinType(("void", "*"))
    if t is ctypes.c_char_p: t = CPointerType(CBuiltinType(("char",)))
    if t is ctypes.c_char: t = CBuiltinType(("char",))
    return t


def wrapCFunc(state, funcname, restype, argtypes, varargs=False):
    f = getattr(libc, funcname)
    restype = _fixCType(state, restype)
    if restype is CVoidType:
        f.restype = None
    else:
        assert restype is not None
        f.restype = getCTypeWrapped(restype, state)
    assert argtypes is not None
    argtypes = [_fixCType(state, arg) for arg in argtypes]
    f.argtypes = [getCTypeWrapped(arg, state) for arg in argtypes]
    state.funcs[funcname] = CWrapValue(
        f, name=funcname, funcname=funcname,
        returnType=restype, argTypes=argtypes)


def wrapCFunc_varargs(state, funcname, wrap_funcname):
    """
    :param str funcname: e.g. "vprintf"
    :param wrap_funcname: e.g. "printf"
    Will register a new function, where the last arg is expected to be va_list.
    va_list is just a tuple of args.
    Will call the wrap-func with all args and unwraps the va_list args.
    """
    wrap_func = state.funcs[wrap_funcname]
    assert isinstance(wrap_func, CWrapValue)
    wrap_arg_len = len(wrap_func.value.argtypes)
    def f(*args):
        assert len(args) == wrap_arg_len + 1
        assert isinstance(args[-1], Helpers.VarArgs)
        return wrap_func.value(*(args[:-1] + args[-1].args))
    f.__name__ = funcname
    state.funcs[funcname] = CWrapValue(
        f, name=funcname, funcname=funcname,
        returnType=wrap_func.returnType, argTypes=wrap_func.argTypes)


def _fixCArg(a):
    if PY2 and isinstance(a, unicode):
        a = a.encode("utf-8")
    if isinstance(a, str):
        if PY2:
            a = ctypes.c_char_p(a)
        else:
            a = ctypes.c_char_p(a.encode("utf8"))
    if isinstance(a, ctypes.c_char_p) or (isinstance(a, _ctypes._Pointer) and a._type_ is ctypes.c_char):
        return ctypes.cast(a, ctypes.POINTER(ctypes.c_byte))
    if isinstance(a, ctypes.c_char):
        return ctypes.c_byte(ord(a.value))
    return a


def callCFunc(funcname, *args):
    f = getattr(libc, funcname)
    args = [_fixCArg(arg) for arg in args]
    return f(*args)


class Wrapper:
    def __init__(self, state):
        """
        :type state: cparser.State
        """
        self.state = state
        # The Wrapper is supposed to work for parsing also without an interpreter.
        # However, when you are going to call some of the functions from here,
        # this is needed.
        self.interpreter = None  # type: typing.Optional[interpreter.Interpreter]

    def handle_errno_h(self, state):
        import errno as _errno_mod
        for name in dir(_errno_mod):
            if name.startswith("E"):
                state.macros[name] = Macro(rightside=str(getattr(_errno_mod, name)))
        # errno is also exposed as a writable global int variable.
        if "errno" not in state.vars:
            state.vars["errno"] = CWrapValue(0, name="errno")

    def handle_float_h(self, state):
        """Define the <float.h> macros for IEEE-754 double-precision doubles
        and single-precision floats, using the host's sys.float_info as the
        source of truth.  CPython source (e.g. Objects/longobject.c) needs
        DBL_MANT_DIG / DBL_MAX etc. at compile time."""
        fi = sys.float_info
        # IEEE-754 binary -- FLT_RADIX is 2 on every platform we care about.
        state.macros["FLT_RADIX"] = Macro(rightside=str(fi.radix))
        state.macros["FLT_ROUNDS"] = Macro(rightside=str(fi.rounds))
        # double (c_double, 64-bit IEEE on every platform Python supports)
        state.macros["DBL_MANT_DIG"] = Macro(rightside=str(fi.mant_dig))
        state.macros["DBL_DIG"] = Macro(rightside=str(fi.dig))
        state.macros["DBL_MIN_EXP"] = Macro(rightside=str(fi.min_exp))
        state.macros["DBL_MIN_10_EXP"] = Macro(rightside=str(fi.min_10_exp))
        state.macros["DBL_MAX_EXP"] = Macro(rightside=str(fi.max_exp))
        state.macros["DBL_MAX_10_EXP"] = Macro(rightside=str(fi.max_10_exp))
        state.macros["DBL_MAX"] = Macro(rightside=repr(fi.max))
        state.macros["DBL_MIN"] = Macro(rightside=repr(fi.min))
        state.macros["DBL_EPSILON"] = Macro(rightside=repr(fi.epsilon))
        # float (c_float, 32-bit IEEE-754 single precision).  sys.float_info
        # only exposes the double values, so we hard-code the well-known
        # single-precision constants.
        state.macros["FLT_MANT_DIG"] = Macro(rightside="24")
        state.macros["FLT_DIG"] = Macro(rightside="6")
        state.macros["FLT_MIN_EXP"] = Macro(rightside="-125")
        state.macros["FLT_MIN_10_EXP"] = Macro(rightside="-37")
        state.macros["FLT_MAX_EXP"] = Macro(rightside="128")
        state.macros["FLT_MAX_10_EXP"] = Macro(rightside="38")
        state.macros["FLT_MAX"] = Macro(rightside="3.402823466e+38F")
        state.macros["FLT_MIN"] = Macro(rightside="1.175494351e-38F")
        state.macros["FLT_EPSILON"] = Macro(rightside="1.192092896e-07F")
        # long double -- treat as double on all platforms (this is the case
        # on MSVC and many ARM toolchains; on glibc/x86-64 it's 80-bit, but
        # CPython only uses LDBL_* in a handful of corner cases).
        for _suffix in ("MANT_DIG", "DIG", "MIN_EXP", "MIN_10_EXP",
                        "MAX_EXP", "MAX_10_EXP", "MAX", "MIN", "EPSILON"):
            state.macros["LDBL_" + _suffix] = Macro(
                rightside=state.macros["DBL_" + _suffix].rightside)

    def handle_limits_h(self, state):
        # char (signed by default on x86/ARM macOS+Linux; 8-bit on every
        # platform Python supports).
        state.macros["UCHAR_MAX"] = Macro(rightside="255")
        state.macros["CHAR_MAX"] = Macro(rightside="127")
        state.macros["CHAR_MIN"] = Macro(rightside="-128")
        state.macros["SCHAR_MAX"] = Macro(rightside="127")
        state.macros["SCHAR_MIN"] = Macro(rightside="-128")
        # short
        # Signed-MIN macros must stay in signed range.  Writing them
        # as the literal ``-N`` doesn't work when N exceeds the
        # type's signed-max: the magnitude is typed as the *unsigned*
        # variant (per the C-literal-typing rules), and unary-minus
        # on an unsigned wraps modulo 2**w -- the value comes out as
        # ``+N`` of the unsigned type.  This made every ``x < INT_MIN``
        # check (e.g. inside ``_PyLong_AsInt``) fire on perfectly
        # valid small ``x``, raising a bogus ``OverflowError`` in
        # ``_install_external_importers``.  Match what real
        # ``<limits.h>`` does and write ``(-MAX - 1)``, which stays
        # in signed range throughout.
        _intmax = 2 ** (ctypes.sizeof(ctypes.c_int) * 8 - 1) - 1
        _longmax = 2 ** (ctypes.sizeof(ctypes.c_long) * 8 - 1) - 1
        _llmax = 2 ** (ctypes.sizeof(ctypes.c_longlong) * 8 - 1) - 1
        state.macros["SHRT_MAX"] = Macro(rightside=str(2 ** (ctypes.sizeof(ctypes.c_short) * 8 - 1) - 1))
        state.macros["SHRT_MIN"] = Macro(rightside=str(-(2 ** (ctypes.sizeof(ctypes.c_short) * 8 - 1))))
        state.macros["USHRT_MAX"] = Macro(rightside=str(2 ** (ctypes.sizeof(ctypes.c_ushort) * 8) - 1))
        # int
        state.macros["INT_MAX"] = Macro(rightside=str(_intmax))
        state.macros["INT_MIN"] = Macro(rightside="(-%d - 1)" % _intmax)
        state.macros["UINT_MAX"] = Macro(rightside=str(2 ** (ctypes.sizeof(ctypes.c_uint) * 8) - 1))
        # long
        state.macros["LONG_MAX"] = Macro(rightside=str(_longmax))
        state.macros["LONG_MIN"] = Macro(rightside="(-%dL - 1)" % _longmax)
        state.macros["ULONG_MAX"] = Macro(rightside=str(2 ** (ctypes.sizeof(ctypes.c_ulong) * 8) - 1))
        # long long
        state.macros["LLONG_MAX"] = Macro(rightside=str(_llmax))
        state.macros["LLONG_MIN"] = Macro(rightside="(-%dLL - 1)" % _llmax)
        state.macros["ULLONG_MAX"] = Macro(rightside=str(2 ** (ctypes.sizeof(ctypes.c_ulonglong) * 8) - 1))

    def handle_stdio_h(self, state):
        state.macros["NULL"] = Macro(rightside="0")
        # Conventional stdio buffer size; matches glibc/libc on macOS+Linux.
        state.macros["BUFSIZ"] = Macro(rightside="8192")
        # EOF is the typical sentinel returned by getc/fgetc on end-of-file.
        state.macros["EOF"] = Macro(rightside="-1")
        FileP = CPointerType(CStdIntType("FILE")).getCType(state)
        wrapCFunc(state, "fopen", restype=FileP, argtypes=(ctypes.c_char_p, ctypes.c_char_p))
        wrapCFunc(state, "fclose", restype=ctypes.c_int, argtypes=(FileP,))
        wrapCFunc(state, "fdopen", restype=FileP, argtypes=(ctypes.c_int, ctypes.c_char_p))
        if sys.platform == "darwin":
            sym_names = ("__stdinp", "__stdoutp", "__stderrp")
        else:
            sym_names = ("stdin", "stdout", "stderr")
        state.vars["stdin"] = CWrapValue(FileP.in_dll(libc, sym_names[0]), name="stdin")
        state.vars["stdout"] = CWrapValue(FileP.in_dll(libc, sym_names[1]), name="stdout")
        state.vars["stderr"] = CWrapValue(FileP.in_dll(libc, sym_names[2]), name="stderr")
        wrapCFunc(state, "printf", restype=ctypes.c_int, argtypes=(ctypes.c_char_p,), varargs=True)
        wrapCFunc(state, "fprintf", restype=ctypes.c_int, argtypes=(FileP, ctypes.c_char_p), varargs=True)
        wrapCFunc(state, "sprintf", restype=ctypes.c_int, argtypes=(ctypes.c_char_p, ctypes.c_char_p), varargs=True)
        wrapCFunc(state, "snprintf", restype=ctypes.c_int, argtypes=(ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p), varargs=True)
        wrapCFunc_varargs(state, "vprintf", wrap_funcname="printf")
        wrapCFunc_varargs(state, "vfprintf", wrap_funcname="fprintf")
        wrapCFunc_varargs(state, "vsprintf", wrap_funcname="sprintf")
        wrapCFunc(state, "fputs", restype=ctypes.c_int, argtypes=(ctypes.c_char_p, FileP))
        wrapCFunc(state, "fputc", restype=ctypes.c_int, argtypes=(ctypes.c_int, FileP))
        wrapCFunc(state, "fgets", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p, ctypes.c_int, FileP))
        wrapCFunc(state, "fread", restype=ctypes.c_size_t, argtypes=(ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, FileP))
        wrapCFunc(state, "fwrite", restype=ctypes.c_size_t, argtypes=(ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, FileP))
        wrapCFunc(state, "fflush", restype=ctypes.c_int, argtypes=(FileP,))
        wrapCFunc(state, "ftell", restype=ctypes.c_long, argtypes=(FileP,))
        wrapCFunc(state, "rewind", restype=CVoidType, argtypes=(FileP,))
        wrapCFunc(state, "ferror", restype=ctypes.c_int, argtypes=(FileP,))
        wrapCFunc(state, "clearerr", restype=CVoidType, argtypes=(FileP,))
        state.vars["errno"] = CWrapValue(0, name="errno") # TODO
        state.macros["EOF"] = Macro(rightside="-1") # TODO?
        wrapCFunc(state, "setbuf", restype=CVoidType, argtypes=(FileP, ctypes.c_char_p))
        wrapCFunc(state, "isatty", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
        wrapCFunc(state, "fileno", restype=ctypes.c_int, argtypes=(FileP,))
        wrapCFunc(state, "getc", restype=ctypes.c_int, argtypes=(FileP,))
        wrapCFunc(state, "ungetc", restype=ctypes.c_int, argtypes=(ctypes.c_int, FileP))
        wrapCFunc(state, "fseek", restype=ctypes.c_int, argtypes=(FileP, ctypes.c_long, ctypes.c_int))
        wrapCFunc(state, "feof", restype=ctypes.c_int, argtypes=(FileP,))
        wrapCFunc(state, "remove", restype=ctypes.c_int, argtypes=(ctypes.c_char_p,))
        wrapCFunc(state, "rename", restype=ctypes.c_int, argtypes=(ctypes.c_char_p, ctypes.c_char_p))
        state.macros["SEEK_SET"] = Macro(rightside="0")
        state.macros["SEEK_CUR"] = Macro(rightside="1")
        state.macros["SEEK_END"] = Macro(rightside="2")

    def handle_unistd_h(self, state):
        """POSIX <unistd.h>: pulls in sys/time types since Python.h includes this."""
        self.handle_sys_time_h(state)
        for _fname, _res, _args in [
            ("write",  ctypes.c_long,    (ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t)),
            ("read",   ctypes.c_long,    (ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t)),
            ("close",  ctypes.c_int,     (ctypes.c_int,)),
            ("dup",    ctypes.c_int,     (ctypes.c_int,)),
            ("dup2",   ctypes.c_int,     (ctypes.c_int, ctypes.c_int)),
            ("getcwd", ctypes.c_char_p,  (ctypes.c_char_p, ctypes.c_size_t)),
            ("getpid", ctypes.c_int,     ()),
            ("lseek",  ctypes.c_long,    (ctypes.c_int, ctypes.c_long, ctypes.c_int)),
        ]:
            if _fname not in state.funcs:
                wrapCFunc(state, _fname, restype=_res, argtypes=_args)
        if "_exit" not in state.funcs:
            state.funcs["_exit"] = CWrapValue(
                lambda code: self.interpreter._exit(code.value),
                returnType=CVoidType,
                name="_exit"
            )

    def handle_stdlib_h(self, state):
        state.macros["EXIT_SUCCESS"] = Macro(rightside="0")
        state.macros["EXIT_FAILURE"] = Macro(rightside="1")
        state.funcs["abort"] = CWrapValue(
            lambda: self.interpreter._abort(),
            returnType=CVoidType,
            name="abort"
        )
        state.funcs["exit"] = CWrapValue(
            lambda s: self.interpreter._exit(s.value),  # int
            returnType=CVoidType,
            name="exit"
        )
        state.funcs["malloc"] = CWrapValue(
            lambda s: self.interpreter._malloc(s.value),  # size_t
            returnType=ctypes.c_void_p,
            name="malloc"
        )
        state.funcs["realloc"] = CWrapValue(
            lambda p, s: self.interpreter._realloc(_ctype_ptr_get_value(p), s.value),  # void*, size_t
            returnType=ctypes.c_void_p,
            name="realloc"
        )
        state.funcs["free"] = CWrapValue(
            lambda p: self.interpreter._free(_ctype_ptr_get_value(p)),  # void*
            returnType=CVoidType,
            name="free"
        )
        state.funcs["calloc"] = CWrapValue(
            lambda nmemb, size: self.interpreter._malloc(nmemb.value * size.value),  # size_t, size_t
            returnType=ctypes.c_void_p,
            name="calloc"
        )
        wrapCFunc(state, "strtoul", restype=ctypes.c_ulong, argtypes=(ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p), ctypes.c_int))
        wrapCFunc(state, "strtol", restype=ctypes.c_long, argtypes=(ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p), ctypes.c_int))
        wrapCFunc(state, "strtod", restype=ctypes.c_double, argtypes=(ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p)))
        wrapCFunc(state, "qsort", restype=CVoidType, argtypes=(ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p))
        wrapCFunc(state, "bsearch", restype=ctypes.c_void_p, argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p))
        wrapCFunc(state, "abs", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
        state.funcs["atoi"] = CWrapValue(
            lambda x: ctypes.c_int(int(ctypes.cast(x, ctypes.c_char_p).value)),
            returnType=ctypes.c_int,
            name="atoi"
        )
        state.funcs["getenv"] = CWrapValue(
            lambda x: self.interpreter._make_string(os.getenv(ctypes.cast(x, ctypes.c_char_p).value.decode("utf8"))),
            returnType=CPointerType(ctypes.c_byte),
            name="getenv"
        )
    def handle_stdarg_h(self, state):
        state.typedefs["va_list"] = CTypedef(name="va_list", type=CVariadicArgsType())
        def va_start(v, dummy_last):
            assert isinstance(v, Helpers.VarArgs)
            v.idx = 0
        def va_end(v):
            assert isinstance(v, Helpers.VarArgs)
            #assert v.idx == len(v.args), "VarArgs: va_end: not handled all args"  # is this an error?
        def __va_arg(v, inplace_typed):
            assert isinstance(v, Helpers.VarArgs)
            x = v.get_next()
            helpers = v.intp.helpers
            helpers.assignGeneric(inplace_typed, x)
            return inplace_typed
        def __va_arg_getReturnType(stateStruct, stmnt_args):
            assert len(stmnt_args) == 2  # see __va_arg
            return getValueType(stateStruct, stmnt_args[1])
        state.funcs["va_start"] = CWrapValue(va_start, name="va_start", returnType=CVoidType)
        state.funcs["va_end"] = CWrapValue(va_end, name="va_end", returnType=CVoidType)
        state.macros["va_arg"] = Macro(args=("list", "type"), rightside="((__va_arg(list, type())))")
        state.funcs["__va_arg"] = CWrapValue(__va_arg, name="__va_arg",
                                             returnType=None, getReturnType=__va_arg_getReturnType)
        # va_copy(dst, src): copy a va_list.  In our interpreter va_list is a VarArgs object,
        # so we just make dst point to a shallow copy of src.
        def va_copy(dst, src):
            assert isinstance(dst, Helpers.VarArgs)
            assert isinstance(src, Helpers.VarArgs)
            dst.args = list(src.args)
            dst.idx = src.idx
        state.funcs["va_copy"] = CWrapValue(va_copy, name="va_copy", returnType=CVoidType)
        state.funcs["__builtin_va_copy"] = CWrapValue(va_copy, name="__builtin_va_copy",
                                                      returnType=CVoidType)
    def handle_stdbool_h(self, state):
        state.macros["bool"] = Macro(rightside="int")
        state.macros["true"] = Macro(rightside="1")
        state.macros["false"] = Macro(rightside="0")
    def handle_stddef_h(self, state): pass  # offsetof is handled as a cparser builtin keyword
    def handle_math_h(self, state):
        """Wrap the standard C99 <math.h> functions and constants.

        We bind directly to libc (via ctypes), so behaviour matches the host
        platform's libm.  Only the double-precision variants are wrapped --
        CPython source mostly uses those.
        """
        import math
        # Infinity macros.
        # We need each of these to expand to a single token
        # that parses as a C float literal and evaluates to +inf.
        # Of the three obvious candidates:
        #   - `(1.0/0.0)`  -- canonical C, but blows up in our interpreter
        #                     (Python raises ZeroDivisionError on float div).
        #   - `(DBL_MAX*DBL_MAX)` -- glibc-style overflow; would require us
        #                     to also pull `<float.h>` into every TU that
        #                     uses `<math.h>` so DBL_MAX is in scope.
        #   - `1e999`      -- a decimal float literal whose magnitude
        #                     exceeds DBL_MAX.  Python (and IEEE-754
        #                     hardware in C) round it to +inf on
        #                     conversion, which is exactly what we want.
        # We pick the third: it's a single token, self-contained, parses
        # fine in cparser, and `float("1e999") == inf` in Python.
        # We deliberately do NOT define NAN here -- the canonical
        # `(0.0/0.0)` parses fine but raises ZeroDivisionError when our
        # interpreter evaluates it, and CPython source uses the
        # `Py_IS_NAN` macro for NaN tests rather than the `NAN` value, so
        # leaving it undefined is fine in practice.
        state.macros["HUGE_VAL"] = Macro(rightside="1e999")
        state.macros["HUGE_VALF"] = Macro(rightside="1e999F")
        state.macros["HUGE_VALL"] = Macro(rightside="1e999L")
        state.macros["INFINITY"] = Macro(rightside="1e999F")
        # FP classification result codes (C99 <math.h>).  Values match glibc.
        state.macros["FP_NAN"] = Macro(rightside="0")
        state.macros["FP_INFINITE"] = Macro(rightside="1")
        state.macros["FP_ZERO"] = Macro(rightside="2")
        state.macros["FP_SUBNORMAL"] = Macro(rightside="3")
        state.macros["FP_NORMAL"] = Macro(rightside="4")
        # M_* constants (POSIX; widely used but not in strict C99).
        state.macros["M_PI"] = Macro(rightside=repr(math.pi))
        state.macros["M_E"] = Macro(rightside=repr(math.e))
        state.macros["M_LN2"] = Macro(rightside=repr(math.log(2)))
        state.macros["M_LN10"] = Macro(rightside=repr(math.log(10)))
        state.macros["M_LOG2E"] = Macro(rightside=repr(1.0 / math.log(2)))
        state.macros["M_LOG10E"] = Macro(rightside=repr(1.0 / math.log(10)))
        state.macros["M_SQRT2"] = Macro(rightside=repr(math.sqrt(2)))
        # Single-arg double-returning functions.
        # We skip names that the host libc doesn't actually expose
        # (e.g. "cbrt" is missing on some MSVC builds, "nearbyint" on very old runtimes).
        _double = ctypes.c_double
        for _fn in (
                # Power and logarithm
                "sqrt", "cbrt", "exp", "exp2", "expm1",
                "log", "log2", "log10", "log1p",
                # Rounding and truncation
                "floor", "ceil", "round", "trunc", "rint", "nearbyint",
                # Absolute value
                "fabs",
                # Trigonometric
                "sin", "cos", "tan", "asin", "acos", "atan",
                # Hyperbolic
                "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
                # Error / gamma
                "erf", "erfc", "tgamma", "lgamma",
                # FP-bit-pattern queries
                "logb",
        ):
            if hasattr(libc, _fn):
                wrapCFunc(state, _fn, restype=_double, argtypes=(_double,))
        # Two-arg double-returning functions.
        for _fn in ("pow", "atan2", "fmod", "hypot",
                    "copysign", "nextafter", "remainder", "fdim",
                    "fmax", "fmin"):
            if hasattr(libc, _fn):
                wrapCFunc(state, _fn, restype=_double, argtypes=(_double, _double))
        # Functions with mixed signatures.
        if "ldexp" not in state.funcs and hasattr(libc, "ldexp"):
            wrapCFunc(state, "ldexp", restype=_double, argtypes=(_double, ctypes.c_int))
        if "frexp" not in state.funcs and hasattr(libc, "frexp"):
            wrapCFunc(state, "frexp", restype=_double,
                      argtypes=(_double, ctypes.POINTER(ctypes.c_int)))
        if "modf" not in state.funcs and hasattr(libc, "modf"):
            wrapCFunc(state, "modf", restype=_double,
                      argtypes=(_double, ctypes.POINTER(_double)))
        # Classification: return int (an FP_* code or boolean).
        for _fn in ("isnan", "isinf", "isfinite", "isnormal", "signbit",
                    "fpclassify"):
            if hasattr(libc, _fn):
                wrapCFunc(state, _fn, restype=ctypes.c_int, argtypes=(_double,))

    def handle_string_h(self, state):
        wrapCFunc(state, "strlen", restype=ctypes.c_size_t, argtypes=(ctypes.c_char_p,))
        wrapCFunc(state, "strcpy", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
        wrapCFunc(state, "strncpy", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p,ctypes.c_size_t))
        wrapCFunc(state, "strcat", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
        wrapCFunc(state, "strcmp", restype=ctypes.c_int, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
        wrapCFunc(state, "strncmp", restype=ctypes.c_int, argtypes=(ctypes.c_char_p,ctypes.c_char_p,ctypes.c_size_t))
        wrapCFunc(state, "strtok", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
        wrapCFunc(state, "strchr", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_int))
        wrapCFunc(state, "strrchr", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_int))
        wrapCFunc(state, "strstr", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
        wrapCFunc(state, "strdup", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,))
        wrapCFunc(state, "strerror", restype=ctypes.c_char_p, argtypes=(ctypes.c_int,))
        wrapCFunc(state, "memset", restype=ctypes.c_void_p, argtypes=(ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t))
        wrapCFunc(state, "memcpy", restype=ctypes.c_void_p, argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t))
        wrapCFunc(state, "memmove", restype=ctypes.c_void_p, argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t))
        wrapCFunc(state, "memchr", restype=ctypes.c_void_p, argtypes=(ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t))
        wrapCFunc(state, "memcmp", restype=ctypes.c_int, argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t))
    def handle_time_h(self, state):
        state.typedefs["time_t"] = CTypedef(name="time_t", type=CBuiltinType(("int",)))
        if "timespec" not in state.structs:
            s = state.structs["timespec"] = CStruct(name="timespec")
            s.body = CBody(parent=s)
            CVarDecl(parent=s, name="tv_sec", type=CBuiltinType(("long",))).finalize(state)
            CVarDecl(parent=s, name="tv_nsec", type=CBuiltinType(("long",))).finalize(state)
    def handle_ctype_h(self, state):
        wrapCFunc(state, "isalpha", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
        wrapCFunc(state, "isalnum", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
        wrapCFunc(state, "isspace", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
        wrapCFunc(state, "isdigit", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
        wrapCFunc(state, "isxdigit", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
        wrapCFunc(state, "islower", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
        wrapCFunc(state, "tolower", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
        wrapCFunc(state, "isupper", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
        wrapCFunc(state, "toupper", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
    def handle_wctype_h(self, state): pass
    def handle_wchar_h(self, state):
        wchar_p = CPointerType(CStdIntType("wchar_t"))
        wrapCFunc(state, "mbstowcs", restype=ctypes.c_size_t, argtypes=(wchar_p, ctypes.c_char_p, ctypes.c_size_t))
        wrapCFunc(state, "wcstombs", restype=ctypes.c_size_t, argtypes=(ctypes.c_char_p, wchar_p, ctypes.c_size_t))
        wrapCFunc(state, "wcslen", restype=ctypes.c_size_t, argtypes=(wchar_p,))
        wrapCFunc(state, "wcscmp", restype=ctypes.c_int, argtypes=(wchar_p, wchar_p))
        wrapCFunc(state, "wcsncmp", restype=ctypes.c_int, argtypes=(wchar_p, wchar_p, ctypes.c_size_t))
        wchar_t = CStdIntType("wchar_t")
        wrapCFunc(state, "wcschr", restype=wchar_p, argtypes=(wchar_p, wchar_t))
        wrapCFunc(state, "wcsrchr", restype=wchar_p, argtypes=(wchar_p, wchar_t))
        wrapCFunc(state, "wcstok", restype=wchar_p, argtypes=(wchar_p, wchar_p, CPointerType(wchar_p)))
        wrapCFunc(state, "wcsdup", restype=wchar_p, argtypes=(wchar_p,))
        wrapCFunc(state, "wcscpy", restype=wchar_p, argtypes=(wchar_p, wchar_p))
        wrapCFunc(state, "wcsncpy", restype=wchar_p, argtypes=(wchar_p, wchar_p, ctypes.c_size_t))
        wrapCFunc(state, "wcscat", restype=wchar_p, argtypes=(wchar_p, wchar_p))
        wrapCFunc(state, "wcsstr", restype=wchar_p, argtypes=(wchar_p, wchar_p))
        wrapCFunc(state, "wcstol", restype=ctypes.c_long, argtypes=(wchar_p, CPointerType(wchar_p), ctypes.c_int))
        wrapCFunc(state, "wcstoul", restype=ctypes.c_ulong, argtypes=(wchar_p, CPointerType(wchar_p), ctypes.c_int))
        wrapCFunc(state, "wcstod", restype=ctypes.c_double, argtypes=(wchar_p, CPointerType(wchar_p)))
        wrapCFunc(state, "wcsftime", restype=ctypes.c_size_t, argtypes=(wchar_p, ctypes.c_size_t, wchar_p, ctypes.c_void_p))
    def handle_stdint_h(self, state):
        """Provide standard integer types from <stdint.h>."""
        # Map each ctypes type to the CBuiltinType tuple that best matches its
        # actual byte-width.  The old heuristic only distinguished "int" (≤4 B)
        # from "long" (8 B), so int8_t / int16_t / uint8_t / uint16_t were all
        # silently promoted to 4-byte types, corrupting pointer arithmetic that
        # multiplies by sizeof(element_type).
        def _builtin_for(name, ctype):
            size = ctypes.sizeof(ctype)
            if name.startswith("u"):
                if size == 1:
                    return ("unsigned", "char")
                elif size == 2:
                    return ("unsigned", "short")
                elif size == 4:
                    return ("unsigned", "int")
                elif size == ctypes.sizeof(ctypes.c_ulong):
                    return ("unsigned", "long")
                else:
                    return ("unsigned", "long", "long")
            else:
                if size == 1:
                    return ("char",)   # c_byte = signed 1-byte int
                elif size == 2:
                    return ("short",)
                elif size == 4:
                    return ("int",)
                elif size == ctypes.sizeof(ctypes.c_long):
                    return ("long",)
                else:
                    return ("long", "long")
        for _name, _ctype in [
            ("int8_t", ctypes.c_int8),
            ("int16_t", ctypes.c_int16),
            ("int32_t", ctypes.c_int32),
            ("int64_t", ctypes.c_int64),
            ("uint8_t", ctypes.c_uint8),
            ("uint16_t", ctypes.c_uint16),
            ("uint32_t", ctypes.c_uint32),
            ("uint64_t", ctypes.c_uint64),
            ("intptr_t", ctypes.c_ssize_t),
            ("uintptr_t", ctypes.c_size_t),
            ("intmax_t", ctypes.c_int64),
            ("uintmax_t", ctypes.c_uint64),
        ]:
            if _name not in state.typedefs:
                state.typedefs[_name] = CTypedef(name=_name, type=CBuiltinType(_builtin_for(_name, _ctype)))

    def handle_inttypes_h(self, state):
        self.handle_stdint_h(state)

    def handle_assert_h(self, state):
        def assert_wrap(x):
            if isinstance(x, (int, long)):
                val = x
            else:
                if isinstance(x, (ctypes._Pointer, ctypes.Array, ctypes._CFuncPtr)):
                    x = ctypes.cast(x, ctypes.c_void_p)
                val = x.value
            if not val:
                print("assert failed: %r (type %r)" % (x, type(x)))
                raise CAbortException("assert failed: %r (type %r)" % (x, type(x)))
        state.funcs["assert"] = CWrapValue(assert_wrap, returnType=CVoidType, name="assert")
    def handle_fcntl_h(self, state):
        state.macros["O_RDONLY"] = Macro(rightside="0x0000")
        state.macros["O_WRONLY"] = Macro(rightside="0x0001")
        state.macros["O_RDWR"] = Macro(rightside="0x0002")
        state.macros["O_CREAT"] = Macro(rightside="0x0200")
        state.macros["O_TRUNC"] = Macro(rightside="0x0400")
        state.macros["O_APPEND"] = Macro(rightside="0x0008")
        state.macros["O_NONBLOCK"] = Macro(rightside="0x0004")
        state.macros["O_CLOEXEC"] = Macro(rightside="0x01000000")
        # F_* command codes for fcntl()
        state.macros["F_GETFD"] = Macro(rightside="1")
        state.macros["F_SETFD"] = Macro(rightside="2")
        state.macros["F_GETFL"] = Macro(rightside="3")
        state.macros["F_SETFL"] = Macro(rightside="4")
        state.macros["FD_CLOEXEC"] = Macro(rightside="1")
        wrapCFunc(state, "open", restype=ctypes.c_int, argtypes=(ctypes.c_char_p, ctypes.c_int))
        # <fcntl.h> implicitly includes <unistd.h> on most POSIX systems, so
        # we also make the core file-descriptor functions available here.
        self.handle_unistd_h(state)
        # fcntl is variadic: int fcntl(int fd, int cmd[, int arg]).
        # We provide a Python wrapper that accepts 2 or 3 int args so that
        # both F_GETFD/F_GETFL (no arg) and F_SETFD/F_SETFL (with arg) work.
        _libc_fcntl = libc.fcntl
        _libc_fcntl.restype = ctypes.c_int
        def _fcntl_wrapper(fd, cmd, *extra):
            fd_v = fd.value if hasattr(fd, 'value') else int(fd)
            cmd_v = cmd.value if hasattr(cmd, 'value') else int(cmd)
            if extra:
                arg = extra[0]
                arg_v = arg.value if hasattr(arg, 'value') else int(arg)
                return ctypes.c_int(_libc_fcntl(fd_v, cmd_v, arg_v))
            return ctypes.c_int(_libc_fcntl(fd_v, cmd_v))
        state.funcs["fcntl"] = CWrapValue(
            _fcntl_wrapper, name="fcntl", funcname="fcntl",
            returnType=ctypes.c_int, argTypes=[ctypes.c_int, ctypes.c_int])
        # TODO: these are on OSX. cross-platform? probably not...
        state.macros["EINTR"] = Macro(rightside="4")  # via <sys/errno.h>
        state.macros["ERANGE"] = Macro(rightside="34")  # via <sys/errno.h>
    def handle_signal_h(self, state):
        # typedef void (*sig_t) (int)
        state.typedefs["sig_t"] = CTypedef(
            name="sig_t", type=CFuncPointerDecl(type=CVoidType(), args=[CBuiltinType(("int",))]))
        # There is no safe way to support the native C function.
        # The signal handler can be called at any point and it could be that
        # the GIL is hold. Then the signal handler code deadlocks because it also wants the GIL.
        #wrapCFunc(state, "signal", restype=state.typedefs["sig_t"],
        #		  argtypes=(ctypes.c_int, state.typedefs["sig_t"]))
        def signal(sig, f):
            sig = sig.value
            import signal
            if isinstance(f, CWrapValue):
                f = f.value
            def sig_handler(sig, stack_frame):
                return f(sig)
            if isinstance(f, ctypes._CFuncPtr):
                if _ctype_ptr_get_value(f) == 0:  # place-holder for SIG_DFL
                    sig_handler = signal.SIG_DFL
                elif _ctype_ptr_get_value(f) == 1:  # place-holder for SIG_IGN
                    sig_handler = signal.SIG_IGN
            old_action = signal.signal(sig, sig_handler)
            # TODO: need to use helpers.makeFuncPtr for old_action.
            # And maybe handle SIG_DFL/SIG_IGN cases?
            return 0  # place-holder for SIG_DFL
        state.funcs["signal"] = CWrapValue(signal, name="signal", returnType=state.typedefs["sig_t"])
        state.macros["SIGINT"] = Macro(rightside="2")
        state.macros["SIGABRT"] = Macro(rightside="6")
        state.macros["SIGFPE"] = Macro(rightside="8")
        state.macros["SIGKILL"] = Macro(rightside="9")
        state.macros["SIGSEGV"] = Macro(rightside="11")
        state.macros["SIGTERM"] = Macro(rightside="15")
        state.macros["SIGBUS"] = Macro(rightside="10")
        state.macros["SIGILL"] = Macro(rightside="4")
        state.macros["SIG_DFL"] = Macro(rightside="((sig_t)0)")
        state.macros["SIG_IGN"] = Macro(rightside="((sig_t)1)")
        state.macros["SIG_ERR"] = Macro(rightside="((sig_t)-1)")
        wrapCFunc(state, "raise", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
    def handle_locale_h(self, state):
        import locale as _locale
        struct_lconv = state.structs["lconv"] = CStruct(name="lconv") # TODO
        struct_lconv.body = CBody(parent=struct_lconv)
        CVarDecl(parent=struct_lconv, name="grouping", type=ctypes.c_char_p).finalize(state)
        CVarDecl(parent=struct_lconv, name="thousands_sep", type=ctypes.c_char_p).finalize(state)
        wrapCFunc(state, "localeconv", restype=struct_lconv, argtypes=())
        state.macros["LC_ALL"] = Macro(rightside=str(_locale.LC_ALL))
        state.macros["LC_CTYPE"] = Macro(rightside=str(_locale.LC_CTYPE))
        state.macros["LC_COLLATE"] = Macro(rightside=str(_locale.LC_COLLATE))
        state.macros["LC_MONETARY"] = Macro(rightside=str(_locale.LC_MONETARY))
        state.macros["LC_NUMERIC"] = Macro(rightside=str(_locale.LC_NUMERIC))
        state.macros["LC_TIME"] = Macro(rightside=str(_locale.LC_TIME))
        state.macros["LC_MESSAGES"] = Macro(rightside=str(getattr(_locale, "LC_MESSAGES", 6)))

        def _setlocale(category, locale):
            # category is c_int, locale is c_char_p
            cat = category.value
            if isinstance(locale, (ctypes.c_int, ctypes.c_long, ctypes.c_longlong)):
                loc_ptr = locale.value
            else:
                loc_ptr = ctypes.cast(locale, ctypes.c_void_p).value
            if not loc_ptr:
                loc = None
            else:
                loc = ctypes.cast(loc_ptr, ctypes.c_char_p).value
            if loc is not None and not isinstance(loc, str): loc = loc.decode("utf8")
            res = _locale.setlocale(cat, loc)
            return self.interpreter._make_string(res)
        state.funcs["setlocale"] = CWrapValue(_setlocale, name="setlocale", returnType=CPointerType(CBuiltinType(("char",))))

    def handle_langinfo_h(self, state):
        """``<langinfo.h>``: nl_langinfo(CODESET) etc.

        Used by ``initfsencoding`` in pylifecycle.c (and a few others)
        to discover the filesystem encoding.  We expose the constants
        from host Python's ``locale`` module and dispatch
        ``nl_langinfo`` to host ``locale.nl_langinfo``.
        """
        import locale as _locale
        # Common langinfo items.  CODESET is the only one CPython's
        # init really needs; the rest are exposed for completeness.
        for _name in ("CODESET", "D_T_FMT", "D_FMT", "T_FMT",
                      "T_FMT_AMPM", "AM_STR", "PM_STR", "DAY_1",
                      "ABDAY_1", "MON_1", "ABMON_1", "ERA",
                      "ERA_D_FMT", "ERA_D_T_FMT", "ERA_T_FMT",
                      "ALT_DIGITS", "RADIXCHAR", "THOUSEP",
                      "YESEXPR", "NOEXPR", "CRNCYSTR"):
            val = getattr(_locale, _name, None)
            if val is not None:
                state.macros[_name] = Macro(rightside=str(val))
        # ``nl_item`` typedef -- it's basically an int.
        state.typedefs["nl_item"] = CTypedef(name="nl_item", type=CBuiltinType(("int",)))

        def _nl_langinfo(item):
            item_v = item.value if hasattr(item, "value") else int(item)
            s = _locale.nl_langinfo(item_v)
            if isinstance(s, str):
                s = s.encode("utf-8")
            return self.interpreter._make_string(s.decode("utf-8") if isinstance(s, bytes) else s)
        state.funcs["nl_langinfo"] = CWrapValue(
            _nl_langinfo, name="nl_langinfo",
            returnType=CPointerType(CBuiltinType(("char",))))

    def handle_sys_stat_h(self, state):
        self.handle_sys_types_h(state)
        struct_stat = state.structs.get("stat")
        if not struct_stat:
            struct_stat = state.structs["stat"] = CStruct(name="stat") # TODO
            struct_stat.body = CBody(parent=struct_stat)
            CVarDecl(parent=struct_stat, name="st_dev", type=state.typedefs["dev_t"]).finalize(state)
            CVarDecl(parent=struct_stat, name="st_ino", type=state.typedefs["ino_t"]).finalize(state)
            CVarDecl(parent=struct_stat, name="st_mode", type=state.typedefs["mode_t"]).finalize(state)
            CVarDecl(parent=struct_stat, name="st_nlink", type=state.typedefs["nlink_t"]).finalize(state)
            CVarDecl(parent=struct_stat, name="st_uid", type=state.typedefs["uid_t"]).finalize(state)
            CVarDecl(parent=struct_stat, name="st_gid", type=state.typedefs["gid_t"]).finalize(state)
            CVarDecl(parent=struct_stat, name="st_rdev", type=state.typedefs["dev_t"]).finalize(state)
            CVarDecl(parent=struct_stat, name="st_size", type=state.typedefs["off_t"]).finalize(state)
            # ... add more if needed
        def _fill_stat_struct(st_ptr, st_res):
            if not st_ptr:
                return ctypes.c_int(-1)
            st = st_ptr.contents
            st.st_dev = st_res.st_dev
            st.st_ino = st_res.st_ino
            st.st_mode = st_res.st_mode
            st.st_nlink = st_res.st_nlink
            st.st_uid = st_res.st_uid
            st.st_gid = st_res.st_gid
            st.st_rdev = st_res.st_rdev
            st.st_size = st_res.st_size
            return ctypes.c_int(0)

        def _fstat(fd, st_ptr):
            fd_v = fd.value if hasattr(fd, "value") else int(fd)
            try:
                st_res = os.fstat(fd_v)
            except OSError:
                return ctypes.c_int(-1)
            return _fill_stat_struct(st_ptr, st_res)

        def _stat(path, st_ptr):
            path_b = ctypes.cast(path, ctypes.c_char_p).value
            if not path_b:
                return ctypes.c_int(-1)
            try:
                st_res = os.stat(path_b.decode("utf8"))
            except OSError:
                return ctypes.c_int(-1)
            return _fill_stat_struct(st_ptr, st_res)

        state.funcs["fstat"] = CWrapValue(_fstat, name="fstat", returnType=ctypes.c_int)
        state.funcs["stat"] = CWrapValue(_stat, name="stat", returnType=ctypes.c_int)
        state.macros["S_IFMT"] = Macro(rightside="0170000")
        state.macros["S_IFDIR"] = Macro(rightside="0040000")
        state.macros["S_IFREG"] = Macro(rightside="0100000")
        state.macros["S_ISDIR"] = Macro(args=("m",), rightside="(((m) & S_IFMT) == S_IFDIR)")
        state.macros["S_ISREG"] = Macro(args=("m",), rightside="(((m) & S_IFMT) == S_IFREG)")

    def handle_sys_types_h(self, state):
        """Provide basic POSIX scalar typedefs from <sys/types.h>."""
        for _name, _ctype_name in [
            ("dev_t", ("unsigned", "long")),
            ("ino_t", ("unsigned", "long")),
            ("mode_t", ("unsigned", "int")),
            ("nlink_t", ("unsigned", "long")),
            ("uid_t", ("unsigned", "int")),
            ("gid_t", ("unsigned", "int")),
            ("off_t", ("long",)),
            ("pid_t", ("int",)),
        ]:
            if _name not in state.typedefs:
                state.typedefs[_name] = CTypedef(name=_name, type=CBuiltinType(_ctype_name))
    def handle_sys_time_h(self, state):
        """Provide struct timeval, struct timezone and gettimeofday."""
        if "timeval" not in state.structs:
            s = state.structs["timeval"] = CStruct(name="timeval")
            s.body = CBody(parent=s)
            CVarDecl(parent=s, name="tv_sec", type=CBuiltinType(("long",))).finalize(state)
            CVarDecl(parent=s, name="tv_usec", type=CBuiltinType(("long",))).finalize(state)
        if "timezone" not in state.structs:
            s = state.structs["timezone"] = CStruct(name="timezone")
            s.body = CBody(parent=s)
        import time as _time
        def _gettimeofday(tv_ptr, tz_ptr):
            t = _time.time()
            if tv_ptr and ctypes.cast(tv_ptr, ctypes.c_void_p).value:
                tv = ctypes.cast(tv_ptr, ctypes.POINTER(ctypes.c_long * 2))
                tv.contents[0] = int(t)
                tv.contents[1] = int((t % 1) * 1_000_000)
            return ctypes.c_int(0)
        state.funcs["gettimeofday"] = CWrapValue(_gettimeofday, name="gettimeofday",
                                                  returnType=CBuiltinType(("int",)))
    def handle_pthread_h(self, state):
        state.typedefs["pthread_key_t"] = CTypedef(name="pthread_key_t", type=CBuiltinType(("int",)))
        state.typedefs["pthread_cond_t"] = CTypedef(name="pthread_cond_t", type=CBuiltinType(("int",)))
        state.typedefs["pthread_mutex_t"] = CTypedef(name="pthread_mutex_t", type=CBuiltinType(("int",)))
        state.typedefs["pthread_mutexattr_t"] = CTypedef(name="pthread_mutexattr_t", type=CBuiltinType(("int",)))
        state.typedefs["pthread_condattr_t"] = CTypedef(name="pthread_condattr_t", type=CBuiltinType(("int",)))
        state.typedefs["pthread_attr_t"] = CTypedef(name="pthread_attr_t", type=CBuiltinType(("int",)))
        state.typedefs["pthread_t"] = CTypedef(name="pthread_t", type=CBuiltinType(("int",)))
        # Stub pthread functions: all return 0 (success).  The interpreter does
        # not actually run multiple threads so lock/unlock are no-ops.
        def _pthread_stub(*args):
            return ctypes.c_int(0)
        for _fname in (
            "pthread_mutex_init", "pthread_mutex_destroy",
            "pthread_mutex_lock", "pthread_mutex_unlock", "pthread_mutex_trylock",
            "pthread_cond_init", "pthread_cond_destroy",
            "pthread_cond_wait", "pthread_cond_signal",
            "pthread_cond_broadcast", "pthread_cond_timedwait",
            "pthread_key_create", "pthread_key_delete",
            "pthread_setspecific", "pthread_getspecific",
            "pthread_self", "pthread_equal",
            "pthread_create", "pthread_detach", "pthread_exit",
        ):
            state.funcs[_fname] = CWrapValue(_pthread_stub, name=_fname,
                                              returnType=CBuiltinType(("int",)))
    def handle_stdatomic_h(self, state):
        from .cparser import _CBaseWithOptBody
        parentObj = _CBaseWithOptBody()
        parentObj.body = state
        memory_order = CEnum(name="memory_order", parent=parentObj)
        memory_order.body = CEnumBody(parent=memory_order)
        CEnumConst(parent=memory_order, name="memory_order_relaxed").finalize(state)
        CEnumConst(parent=memory_order, name="memory_order_consume").finalize(state)
        CEnumConst(parent=memory_order, name="memory_order_acquire").finalize(state)
        CEnumConst(parent=memory_order, name="memory_order_release").finalize(state)
        CEnumConst(parent=memory_order, name="memory_order_acq_rel").finalize(state)
        CEnumConst(parent=memory_order, name="memory_order_seq_cst").finalize(state)
        memory_order.finalize(state)
        self.handle_stdint_h(state)
        state.typedefs["atomic_uintptr_t"] = CTypedef(name="atomic_uintptr_t", type=state.typedefs["uintptr_t"])
        state.typedefs["atomic_int"] = CTypedef(name="atomic_int", type=CBuiltinType(("int",)))
        state.macros["atomic_load_explicit"] = Macro(args=("obj", "order"), rightside="(*(obj))")
        state.macros["atomic_store_explicit"] = Macro(args=("obj", "val", "order"), rightside="((*(obj)) = (val))")
        state.macros["atomic_load"] = Macro(args=("obj",), rightside="(*(obj))")
        state.macros["atomic_store"] = Macro(args=("obj", "val"), rightside="((*(obj)) = (val))")

    def find_handler_func(self, filename):
        funcname = "handle_" + filename.replace("/", "_").replace(".", "_")
        return getattr(self, funcname, None)

    def readGlobalInclude(self, state, oldFunc, filename):
        f = self.find_handler_func(filename)
        if f is not None:
            def reader():
                if filename in state._global_include_list: return  # already included
                f(state)
                state._global_include_list.append(filename)
                return
                yield None # to make it a generator
            return reader(), None
        return oldFunc(filename) # fallback

    def install(self):
        state = self.state
        oldFunc = state.readGlobalInclude
        state.readGlobalInclude = lambda fn: self.readGlobalInclude(state, oldFunc, fn)

    def add_all_to_state(self, state):
        for funcname in dir(self):
            if not funcname.startswith("handle_"): continue
            f = getattr(self, funcname)
            f(state)
