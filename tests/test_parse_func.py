
from __future__ import print_function

import helpers_test  # side effect: make cparser importable
from cparser import *
from helpers_test import *


def test_parse_void_func():
    state = parse("void f() {}")
    assert "f" in state.funcs
    f = state.funcs["f"]
    print(f)
    assert isinstance(f, CFunc)


def test_parse_int_func():
    state = parse("int f() {}")
    assert "f" in state.funcs
    f = state.funcs["f"]
    print(f)
    assert isinstance(f, CFunc)
    assert isinstance(f.type, CBuiltinType)


def test_parse_static_void_func():
    state = parse("static void f() {}")
    assert "f" in state.funcs


def test_parse_variadic_args():
    state = parse("void f(...) {}")
    assert "f" in state.funcs
    f = state.funcs["f"]
    print(f)
    assert isinstance(f, CFunc)
    assert len(f.args) == 1
    arg0 = f.args[0]
    assert isinstance(arg0, CFuncArgDecl)
    assert isinstance(arg0.type, CVariadicArgsType)


def test_parse_void_func_self_call():
    state = parse("void f() { f(); }")
    assert "f" in state.funcs
    f = state.funcs["f"]
    print(f)
    assert isinstance(f, CFunc)


def test_parse_param_named_byte():
    """`byte` is not a C standard type, so a parameter (or local) named
    `byte` must parse correctly -- not be mis-identified as a type token.

    cparser historically registered `byte` in `State.StdIntTypes` as a
    non-standard alias for `c_byte`, which meant a function signature like
    `void f(char *byte)` would be tokenised as the type sequence
    `[char, *, byte]` and rejected with
    `make_type_from_typetokens: type tokens not handled: ['char', '*', 'byte']`.
    CPython's Objects/bytes_methods.c uses exactly this idiom (`char *byte`
    parameters and `char byte;` locals).  The alias has been dropped from
    StdIntTypes; if anyone genuinely needs `byte` as a type they can still
    do `typedef unsigned char byte;` explicitly.
    """
    # 1. `byte` as a pointer parameter name -- this is the failing case
    #    from bytes_methods.c.
    state = parse("void f(char *byte) { *byte = 0; }")
    assert not state._errors, "unexpected errors: %r" % state._errors
    assert "f" in state.funcs
    f = state.funcs["f"]
    assert len(f.args) == 1
    arg = f.args[0]
    assert arg.name == "byte", "param name should be 'byte', got %r" % arg.name
    assert isinstance(arg.type, CPointerType)
    assert arg.type.pointerOf == CBuiltinType(("char",))

    # 2. `byte` as a plain local variable name.
    state = parse("int g(void) { char byte = 0; return byte; }")
    assert not state._errors, "unexpected errors: %r" % state._errors
    assert "g" in state.funcs

    # 3. An explicit `typedef unsigned char byte;` must still work for code
    #    that wants the alias.
    state = parse("typedef unsigned char byte;\nbyte h(byte x) { return x; }")
    assert not state._errors, "unexpected errors: %r" % state._errors
    assert "byte" in state.typedefs
    assert "h" in state.funcs


if __name__ == "__main__":
    main(globals())
