
from __future__ import print_function

import helpers_test  # side effect: make cparser importable
from cparser import *
from helpers_test import *


def test_parse_code_basic():
    state = State()
    state.autoSetupSystemMacros()

    try:
        preprocessed = state.preprocess_source_code("int v;")
        tokens = cpre2_parse(state, preprocessed)
        cpre3_parse(state, tokens)

    except Exception as e:
        state.error("internal exception: %r" % e)
        print("parsing errors:")
        pprint(state._errors)
        raise

    if state._errors:
        print("parsing errors:")
        pprint(state._errors)
        assert False, "there are parsing errors"

    pprint(state.vars)
    assert "v" in state.vars
    v = state.vars["v"]
    assert isinstance(v.type, CBuiltinType)
    assert v.type.builtinType == ("int", )


def test_parse_var_decl():
    state = parse("int v;")
    assert "v" in state.vars
    v = state.vars["v"]
    assert isinstance(v.type, CBuiltinType)
    assert v.type.builtinType == ("int", )


def test_parse_var_decl_body():
    state = parse("int v = 42;")
    v = state.vars["v"]
    assert isinstance(v.body, CStatement)
    value = v.body._leftexpr
    assert isinstance(value, CNumber)
    assert value.content == 42


def test_parse_typedef_redefinition():
    # Identical typedef redefinition is allowed in C11
    parse("""
    typedef int T;
    typedef int T;
    """)


def test_parse_typedef_redefinition_2():
    # Typedef redefinition using the typedef itself
    parse("""
    typedef int T;
    typedef T T;
    """)


def test_parse_macro_redefinition():
    # Identical macro redefinition is allowed in C
    state = State()
    parse_code("""
    #define M 1
    #define M 1
    """, state)
    if state._errors:
        print("Errors:", state._errors)
        assert False, "should not have errors"
    assert "M" in state.macros
    assert state.macros["M"].rightside.strip() == "1"


def test_parse_macro_redefinition_2():
    # Redefinition with identical rightside (string-wise or token-wise) should be allowed.
    state = State()
    parse_code("""
    #define M(a) a + 1
    #define M(a) a + 1
    """, state)
    if state._errors:
        print("Errors:", state._errors)
        assert False, "should not have errors"


def test_parse_var_decl_ptr():
    state = parse("int* v;")
    assert "v" in state.vars
    v = state.vars["v"]
    assert isinstance(v.type, CPointerType)
    assert isinstance(v.type.pointerOf, CBuiltinType)
    assert v.type.pointerOf.builtinType == ("int", )


def test_parse_var_decl_ptr_body():
    state = parse("int* v = 42;")
    v = state.vars["v"]
    assert isinstance(v.body, CStatement)
    value = v.body._leftexpr
    assert isinstance(value, CNumber)
    assert value.content == 42


def test_parse_c_cast():
    state = parse("int v = (int) 42;")
    v = state.vars["v"]
    assert isinstance(v.body, CStatement)
    # TODO ...


def test_parse_c_cast_ptr():
    state = parse("unsigned int v = (unsigned int) 42;")
    v = state.vars["v"]
    assert isinstance(v.body, CStatement)
    # TODO ...


def test_parse_macro():
    parse("""
    #define macro(x) (x)
    int v = 0;
    if(macro(v)) {}
    """)


def test_parse_aritmethic_1():
    parse("if(0.5) {}")


def test_parse_aritmethic_1a():
    parse("if(0 == 0.5) {}")


def test_parse_aritmethic_1b():
    parse("if((0) * 0.5 == (0)) {}")


def test_parse_postfix_incr_in_binary_expr():
    """Postfix ++ on the right-hand operand of a binary op must parse correctly."""
    from cparser.cparser import CStatement, CVarDecl, COp
    state = parse("int f() { int a = 5; a = a++ + ++a; return a; }")
    assert not state._errors, state._errors
    func = state.funcs["f"]
    # The assignment statement is contentlist[1]: a = a++ + ++a
    assign = func.body.contentlist[1]
    assert isinstance(assign, CStatement)
    assert assign._op == COp("="), "outer op should be ="

    rhs = assign._rightexpr  # should be (a++) + (++a)
    assert isinstance(rhs, CStatement)
    assert rhs._op == COp("+"), "rhs outer op should be + (binary add), got %r" % rhs._op

    lhs_of_add = rhs._leftexpr  # should be a++ (postfix)
    assert isinstance(lhs_of_add, CStatement)
    assert lhs_of_add._op == COp("++"), "left of + should be postfix a++, got %r" % lhs_of_add._op
    assert lhs_of_add._rightexpr is None, "postfix ++ must have no rightexpr"
    assert isinstance(lhs_of_add._leftexpr, CVarDecl)

    rhs_of_add = rhs._rightexpr  # should be ++a (prefix)
    assert isinstance(rhs_of_add, CStatement)
    assert rhs_of_add._leftexpr is None, "prefix ++ must have no leftexpr"
    assert rhs_of_add._op == COp("++"), "right of + should be prefix ++a, got %r" % rhs_of_add._op


def test_parse_macro_2a():
    state = cparser.State()
    preprocessed = state.preprocess_source_code("""
    #define Py_IS_INFINITY(X) ((X) * 0.5 == (X))
    if(Py_IS_INFINITY(0)) {}
    """)
    # preproccessed code will *not* substitute macros. that's handled by cpre2_parse.
    preprocessed = "".join(preprocessed)
    preprocessed = [l.strip() for l in preprocessed.splitlines()]
    preprocessed = "".join([l + "\n" for l in preprocessed if l])
    print("preprocessed:")
    pprint(preprocessed)
    tokens = cpre2_parse(state, preprocessed)
    if state._errors:
        print("parse errors after cpre2_parse:")
        pprint(state._errors)
    tokens = list(tokens)
    print("token list:")
    pprint(tokens)
    cpre3_parse(state, tokens)
    if state._errors:
        print("parse errors:")
        pprint(state._errors)
        assert False, "parse errors"


def test_parse_macro_2():
    parse("""
    #define Py_FORCE_DOUBLE(X) (X)
    #define Py_IS_NAN(X) ((X) != (X))
    #define Py_IS_INFINITY(X) ((X) &&                                   \
                              (Py_FORCE_DOUBLE(X)*0.5 == Py_FORCE_DOUBLE(X)))
    #define Py_IS_FINITE(X) (!Py_IS_INFINITY(X) && !Py_IS_NAN(X))
    int v = 0;
    if(Py_IS_FINITE(v)) {}
    """)


def test_parse_cast_ptr_attrib_access():
    parse("""
    typedef void *(*allocfunc)(void *, int);
    typedef struct {
        allocfunc tp_alloc;
    } MetaType;
    typedef struct {} PyTypeObject;
    void foo() {
        MetaType* metatype;
        PyTypeObject* type = (PyTypeObject *)metatype->tp_alloc(0, 0);
    }
    """)


def test_parse_cmp_null():
    parse("""
    #define NULL 0
    void* foo() {
        void* x;
        if(x == NULL) {}
    }
    """)


def test_parse_var_decl_existing_typedef():
    parse("""
    typedef struct {} PyObject;
    typedef struct {} state;
    void foo() {
        PyObject *state;
    }
    """)


def test_parse_var_decl_existing_typedef_asign():
    parse("""
    typedef struct {} PyObject;
    typedef struct {} state;
    void foo() {
        PyObject *state;
        state = 42;
        if(state * state == 0) {}
    }
    """)


def test_parse_nested_body():
    parse("void foo() {{ int x; }}")


def test_parse_two_nested_bodies():
    parse("void foo() { {int x;} {int x;} }")


def test_parse_nested_body_after_while():
    parse("void foo() { while(0) {int x;} {int x;} }")


def test_parse_nested_body_after_do_while():
    parse("void foo() { do {int x;} while(0); {int x;} }")


def test_parse_nested_body_after_do_while_while():
    parse("void foo() { do {} while(0); while(0) {} {} }")


def test_parse_while_after_do_while():
    parse("void foo() { do {} while(0); while(0) {} }")


def test_parse_goto_label():
    parse("""
    void foo() {
        label:
        int x = 1;
    }
    """)


def test_parse_goto_label_single_stmnt():
    parse("""
    void foo() {
        int x = 0;
        if(0) {}
        else
            label:
                x = 1;
    }
    """)


def test_parse_array():
    s = parse("int x[10];")
    x = s.vars["x"]
    print("x:", x)
    assert isinstance(x, CVarDecl)
    assert isinstance(x.type, CArrayType)
    assert isinstance(x.type.arrayLen, CArrayStatement)
    assert x.type.arrayOf == CBuiltinType(("int",))
    l = getConstValue(s, x.type.arrayLen)
    assert l == 10


def test_parse_enum_const_prev_identifier():
    s = parse("""
    typedef enum {
    _PyTime_ROUND_FLOOR=0,
    _PyTime_ROUND_CEILING=1,
    _PyTime_ROUND_HALF_EVEN=2,
    _PyTime_ROUND_UP=3,
    _PyTime_ROUND_TIMEOUT = _PyTime_ROUND_UP
    } _PyTime_round_t;
    """)
    t = s.typedefs["_PyTime_round_t"]
    assert isinstance(t, CTypedef)
    t = t.type
    assert isinstance(t, CEnum)
    print(t, t.body)
    assert isinstance(t.body, CEnumBody)
    for c in t.body.contentlist:
        assert isinstance(c, CEnumConst)
        assert s.enumconsts[c.name] is c
    assert_equal(s.enumconsts["_PyTime_ROUND_HALF_EVEN"].value, 2)
    assert_equal(s.enumconsts["_PyTime_ROUND_UP"].value, 3)
    assert_equal(s.enumconsts["_PyTime_ROUND_TIMEOUT"].value, 3)


def test_struct_pad_unnamed():
    s = parse("""
    struct {
        unsigned int interned:2;
        unsigned int kind:3;
        unsigned int compact:1;
        unsigned int ascii:1;
        unsigned int ready:1;
        unsigned int :24;
    } state;
    """)
    v = s.vars["state"]
    print(v)
    assert isinstance(v, CVarDecl)
    assert isinstance(v.type, CStruct)
    a = v.type.body.contentlist[-1]
    print(a)
    assert isinstance(a, CVarDecl)
    assert a.name is None
    assert a.bitsize == 24


def test_parse_const_func_ptr():
    s = parse("int (*const hash)(const void *, int);")
    v = s.vars["hash"]
    print(v)
    assert isinstance(v, CVarDecl)
    assert isinstance(v.type, CFuncPointerDecl)
    assert "const" in v.type.attribs


# ---------------------------------------------------------------------------
# Wide string / char literals in parsed code
# ---------------------------------------------------------------------------

def test_wchar_string_literal_in_function():
    """L\"...\" used as an initialiser should parse without errors."""
    parse("""
    void f() {
        wchar_t *s = L"hello";
    }
    """)


def test_wchar_char_literal_in_function():
    """L'x' used in a comparison should parse without errors."""
    parse("""
    int f(wchar_t c) {
        return c == L'A';
    }
    """)


# ---------------------------------------------------------------------------
# Scientific-notation number literals in parsed code
# ---------------------------------------------------------------------------

def test_number_scientific_notation_in_var_decl():
    """Variable initialised with scientific notation must parse cleanly."""
    parse("float v = 1e10;")


# ---------------------------------------------------------------------------
# __func__ predefined identifier
# ---------------------------------------------------------------------------

def test_func_identifier_in_function():
    """__func__ used as a string value must parse without errors."""
    parse("""
    void f() {
        const char *name = __func__;
    }
    """)


# ---------------------------------------------------------------------------
# C99 for-loop init-variable visibility
# ---------------------------------------------------------------------------

def test_for_loop_c99_init():
    """for(int i = 0; i < n; i++) must parse without errors."""
    parse("""
    void f() {
        for(int i = 0; i < 10; i++) {}
    }
    """)


def test_for_loop_c99_init_used_in_body():
    """Loop variable declared in for-init must be usable in the body."""
    parse("""
    void f() {
        int a[10];
        for(int i = 0; i < 10; i++) {
            a[i] = i;
        }
    }
    """)


def test_for_loop_c99_init_multiple():
    """Multiple consecutive C99 for loops must each parse cleanly."""
    parse("""
    void f() {
        for(int i = 0; i < 5; i++) {}
        for(int j = 0; j < 5; j++) {}
    }
    """)


# ---------------------------------------------------------------------------
# Designated initializers (.field = value)
# ---------------------------------------------------------------------------

def test_designated_init_struct():
    """Struct literal with .field = value syntax must parse without errors."""
    parse("""
    struct Point { int x; int y; };
    struct Point p = { .x = 1, .y = 2 };
    """)


def test_designated_init_partial():
    """Partial designated initializer (only some fields) must parse."""
    parse("""
    struct S { int a; int b; int c; };
    struct S v = { .a = 10, .c = 30 };
    """)


def test_designated_init_in_function():
    """Designated initializer inside a function body must parse."""
    parse("""
    struct Pair { int first; int second; };
    void f() {
        struct Pair p = { .first = 42, .second = 99 };
    }
    """)


# ---------------------------------------------------------------------------
# Struct initializer with function-pointer fields (function-to-pointer decay)
# ---------------------------------------------------------------------------

def test_parse_struct_func_ptr_field():
    """A struct with a function-pointer field must parse without errors."""
    parse("""
    typedef struct {
        void (*fn)(void);
    } Ops;
    """)


def test_parse_struct_func_ptr_init():
    """Struct initializer using a named function as a function-pointer value
    (function-to-pointer decay) must parse and the variable must appear in
    state.vars."""
    state = parse("""
    void my_func(void) {}
    typedef struct {
        void (*fn)(void);
    } Ops;
    Ops ops = { my_func };
    """)
    assert "ops" in state.vars, "ops not in state.vars"


def test_parse_struct_multi_func_ptr_init():
    """Struct with multiple function-pointer fields initialized from named
    functions must parse cleanly — mirrors the CPython PyMemAllocatorEx pattern."""
    state = parse("""
    static void *my_malloc(void *ctx, size_t size) { return 0; }
    static void *my_calloc(void *ctx, size_t n, size_t s) { return 0; }
    static void *my_realloc(void *ctx, void *ptr, size_t n) { return 0; }
    static void  my_free(void *ctx, void *ptr) {}

    typedef struct {
        void *ctx;
        void *(*malloc)(void *ctx, size_t size);
        void *(*calloc)(void *ctx, size_t n, size_t s);
        void *(*realloc)(void *ctx, void *ptr, size_t n);
        void  (*free)(void *ctx, void *ptr);
    } AllocEx;

    static AllocEx alloc = {0, my_malloc, my_calloc, my_realloc, my_free};
    """)
    assert "alloc" in state.vars, "alloc not in state.vars"


def test_parse_wcslen_via_wchar_h():
    """wcslen must be available after including <wchar.h> via the global
    include wrappers."""
    state = parse("""
    #include <wchar.h>
    size_t f(wchar_t *s) {
        return wcslen(s);
    }
    """, withGlobalIncludeWrappers=True)
    assert "f" in state.funcs, "f not parsed"


def test_parse_precedence_address_of_sub():
    """&x[1] - &x[0] should be parsed as (&(x[1])) - (&(x[0])) and not &(x[1] - &x[0])."""
    state = parse("""
    void f() {
        int x[2];
        int r = &x[1] - &x[0];
    }
    """)
    f = state.funcs["f"]
    # int r = ...
    stmt = f.body.contentlist[1].body
    # should be a binary '-' op
    assert isinstance(stmt, CStatement)
    assert stmt._op.content == "-"
    assert isinstance(stmt._leftexpr, CStatement)
    assert stmt._leftexpr._op.content == "&"
    assert isinstance(stmt._rightexpr, CStatement)
    assert stmt._rightexpr._op.content == "&"


def test_function_like_macro_not_expanded_without_parens():
    """A function-like macro must NOT be expanded when used as a plain identifier (without '(')."""
    # In C, #define foo(x) ... is only expanded when followed by '('.
    # Using 'foo' as a variable name must not trigger expansion.
    state = parse("""
    #define myfunc(a) ((a) + 1)
    int f(int myfunc) { return myfunc; }
    """)
    assert not state._errors, "Unexpected errors: %r" % state._errors


def test_function_like_macro_expanded_with_parens():
    """A function-like macro MUST be expanded when followed by '('."""
    state = parse("""
    #define double_val(x) ((x) * 2)
    int f() { return double_val(3); }
    """)
    assert not state._errors, "Unexpected errors: %r" % state._errors


def test_prototype_after_definition():
    """A forward declaration (no body) after the full definition must not be an error.

    This mirrors the CPython clinic pattern where clinic/foo.c.h contains a
    prototype for a function that was already fully defined earlier in foo.c.
    """
    state = parse("""
    static int my_func(int x) { return x + 1; }
    static int my_func(int x);
    """)
    assert not state._errors, "unexpected errors: %r" % state._errors
    assert "my_func" in state.funcs
    assert state.funcs["my_func"].body is not None, "body should be the existing definition"


def test_parse_library_collision():
    """Declaring a library function without a body should not crash or overwrite the wrapper."""
    state = parse("""
    #include <string.h>
    int strlen(const char *);
    int f() { return strlen("foo"); }
    """, withGlobalIncludeWrappers=True)
    assert "strlen" in state.funcs
    assert isinstance(state.funcs["strlen"], CWrapValue)


# ---------------------------------------------------------------------------
# File-scope ``static`` declarations across translation units.
#
# Per ISO C, ``static`` at file scope has *internal linkage* -- the name
# is visible only within its own .c file.  Two .c files can independently
# declare ``static int counter;`` and they are SEPARATE variables.
#
# Our cparser currently merges all parsed translation units into a single
# ``state.vars`` namespace and does not distinguish file-scope statics by
# their declaring file.  When two .c files declare ``static T *x;`` with
# the same name, the later parse silently overwrites the first.  If the
# two declarations have DIFFERENT types (size in bytes), code in one file
# that thinks it's accessing its own ``x`` ends up reading/writing the
# other file's variable, causing memory corruption.
#
# This was the root cause of the SIGSEGV in ``cpython.py -c "print('hi')"``
# at shutdown gc -- ``Objects/classobject.c`` declares ``static
# PyMethodObject *free_list`` (40-byte body) while
# ``Objects/methodobject.c`` declares ``static PyCFunctionObject
# *free_list`` (48-byte body).  See SEGFAULT_INVESTIGATION.md for the
# full diagnostic narrative.
#
# Mitigation in ``cpython.py``: preprocessor macros rename the colliding
# statics with a per-file suffix before parsing each .c file.
# ---------------------------------------------------------------------------

def _write_two_files_and_parse(src_a, src_b):
    """Helper: parse two .c sources (a.c, b.c in temp dir) into one
    ``cparser.State`` and return it.  Errors are NOT asserted away --
    the caller inspects ``state._errors``.
    """
    import os
    import tempfile
    import cparser
    state = cparser.State()
    state.autoSetupSystemMacros()
    with tempfile.TemporaryDirectory() as tmpdir:
        for basename, src in (("a.c", src_a), ("b.c", src_b)):
            full = os.path.join(tmpdir, basename)
            with open(full, "w") as f:
                f.write(src)
            cparser.parse(full, state)
    return state


def test_file_scope_static_collision_is_detected_as_parse_error():
    """Two .c files declaring ``static T *shared;`` of DIFFERENT types
    must produce a cparser parse error.  Per ISO C these are SEPARATE
    variables (internal linkage), but cparser merges all translation
    units into one ``state.vars``; the second decl silently
    overwriting the first would cause type-confusion memory
    corruption at runtime.  cparser detects this at finalize time
    and refuses to merge.
    """
    src_a = """
    typedef struct { int x_a; long y_a; } TypeA;
    static TypeA *shared = 0;
    int store_a(TypeA *p) { shared = p; return 1; }
    """
    src_b = """
    typedef struct { int x_b; long y_b; double z_b; } TypeB;
    static TypeB *shared = 0;
    int store_b(TypeB *p) { shared = p; return 1; }
    """
    state = _write_two_files_and_parse(src_a, src_b)
    matching = [e for e in state._errors
                if "shared" in e and "MEMORY CORRUPTION" in e]
    assert len(matching) == 1, (
        "expected exactly one collision error for 'shared'; got "
        "errors=%r" % state._errors)
    assert "INCOMPATIBLE TYPES" in matching[0]


def test_file_scope_static_collision_workaround_via_macros():
    """The supported workaround: use ``state.macros`` to rename one
    file's static before parsing it.  No name collision -> no parse
    error.  Mirrors the pattern used throughout ``cpython.py`` for
    ``free_list``, ``numfree``, etc.
    """
    import os
    import tempfile
    import cparser as _cparser
    src_a = """
    typedef struct { int x_a; long y_a; } TypeA;
    static TypeA *shared = 0;
    int store_a(TypeA *p) { shared = p; return 1; }
    """
    src_b = """
    typedef struct { int x_b; long y_b; double z_b; } TypeB;
    static TypeB *shared = 0;
    int store_b(TypeB *p) { shared = p; return 1; }
    """
    state = _cparser.State()
    state.autoSetupSystemMacros()
    with tempfile.TemporaryDirectory() as tmpdir:
        fa = os.path.join(tmpdir, "a.c")
        fb = os.path.join(tmpdir, "b.c")
        with open(fa, "w") as f:
            f.write(src_a)
        with open(fb, "w") as f:
            f.write(src_b)
        state.macros["shared"] = _cparser.Macro(rightside="shared_a")
        _cparser.parse(fa, state)
        state.macros["shared"] = _cparser.Macro(rightside="shared_b")
        _cparser.parse(fb, state)
        state.macros.pop("shared")
    assert not state._errors, "parsing errors: %r" % state._errors
    # Both variables now exist as separate entries.
    assert "shared_a" in state.vars
    assert "shared_b" in state.vars


def test_file_scope_static_same_type_collision_is_accepted():
    """Arrays of the SAME element type but different lengths
    (eg. ``static char doc[100]`` in one file, ``static char doc[80]``
    in another) are a common pattern for per-file doc strings.
    cparser tolerates these without an error -- the data is read
    not written through, so size mismatch is not dangerous.
    """
    src_a = """
    static char doc[] = "doc string for file A";
    """
    src_b = """
    static char doc[] = "doc string for file B (much longer)";
    """
    state = _write_two_files_and_parse(src_a, src_b)
    matching = [e for e in state._errors
                if "doc" in e and "MEMORY CORRUPTION" in e]
    assert not matching, (
        "did not expect collision error for same-element-type "
        "arrays of different lengths; got: %r" % matching)
    # The merge still happens (only one `doc` in state.vars), but no
    # error -- file-scope arrays of identical element type are
    # treated as compatible.
    assert "doc" in state.vars


# ---------------------------------------------------------------------------
# Ternary operator in variable assignment (listobject.c pattern)
# ---------------------------------------------------------------------------

def test_ternary_in_var_assignment():
    """v = cond ? a : b must parse without 'goto-label' errors."""
    parse("""
    void f() {
        int n = 0;
        int v = n == 0 ? 0 : n;
    }
    """)


def test_ternary_with_negated_paren_middle():
    """cond ? -(expr) : expr must parse without 'goto-label' errors (Py_ABS pattern)."""
    parse("""
    void f() {
        int x, y;
        if (x && ((y) < 0 ? -(y) : (y)) > 1) {}
    }
    """)


def test_ternary_macro_abs():
    """Py_ABS(Py_SIZE(key)) in an if-condition must parse without errors."""
    parse("""
    #define Py_ABS(x) ((x) < 0 ? -(x) : (x))
    #define Py_SIZE(ob) (((ob)->ob_size))
    typedef struct { int ob_size; } PyVarObject;
    void f() {
        PyVarObject *key;
        int x;
        if (x && Py_ABS(Py_SIZE(key)) > 1) {}
    }
    """)


def test_ternary_cast_in_var_assignment():
    """v = cond ? 0 : (cast)expr must parse without errors (listobject.c pattern)."""
    parse("""
    typedef int sdigit;
    typedef struct { int ob_digit[1]; int ob_size; } PyLongObject;
    #define Py_SIZE(ob) (((PyLongObject*)(ob))->ob_size)
    void f() {
        PyLongObject *vl;
        int v0 = Py_SIZE(vl) == 0 ? 0 : (sdigit)vl->ob_digit[0];
    }
    """)


def test_compound_literal_in_braceless_if_body():
    """Compound literal (Type){.field=val} in a brace-less if/while body must parse
    correctly.  Previously the '{' was mistakenly consumed as the start of a new
    block instead of being passed to the pending cast expression.
    Pattern: _Py_INIT_ERR(msg) in CPython's pylifecycle.c.
    """
    state = parse("""
    struct _PyInitError { const char *prefix; const char *msg; int user_err; };
    typedef struct _PyInitError _PyInitError;
    #define _Py_INIT_GET_FUNC() __func__
    #define _Py_INIT_ERR(MSG) \
        (_PyInitError){.prefix = _Py_INIT_GET_FUNC(), .msg = (MSG), .user_err = 0}

    int some_check();
    _PyInitError f() {
        if (some_check())
            return _Py_INIT_ERR("something failed");
        _PyInitError ok = (_PyInitError){.prefix = 0, .msg = 0, .user_err = 0};
        return ok;
    }
    """)
    from cparser.cparser import CCurlyArrayArgs, CReturnStatement
    func = state.funcs['f']

    # The first statement in f's body is an if with a single return.
    if_stmt = func.body.contentlist[0]
    ret = if_stmt.body  # direct CReturnStatement (brace-less body)
    assert isinstance(ret, CReturnStatement), \
        "Expected CReturnStatement, got %r" % type(ret).__name__

    # The returned expression should be a compound literal (CFuncCall with CCurlyArrayArgs).
    def find_curly(obj, depth=0):
        if depth > 10:
            return None
        if isinstance(obj, CCurlyArrayArgs):
            return obj
        for attr in ('_leftexpr', '_rightexpr', 'args'):
            v = getattr(obj, attr, None)
            if isinstance(v, list):
                for item in v:
                    r = find_curly(item, depth + 1)
                    if r is not None:
                        return r
            elif v is not None and hasattr(v, '__dict__'):
                r = find_curly(v, depth + 1)
                if r is not None:
                    return r
        return None

    curly = find_curly(ret.body)
    assert curly is not None, "CCurlyArrayArgs not found in return expression"
    assert len(curly.args) == 3, "Expected 3 designated initializers, got %d" % len(curly.args)
    designator_names = [getattr(a, 'designators', [None])[0] for a in curly.args]
    assert designator_names == ['prefix', 'msg', 'user_err'], \
        "Wrong designators: %r" % designator_names


def test_macro_char_literal_arg_single_quote():
    """A macro invoked with '\\'' must parse without error.

    Before fixing CChar.asCCode(), '\\'\\'' was serialised back to ''' after
    macro-argument collection, causing the re-tokeniser to read the next ''' in
    the source as the closing delimiter of an empty char literal.
    """
    parse(r"""
    #define WRITE_CHAR(ch) do { int x = (ch); } while(0)
    void f(int c) {
        switch (c) {
            case '\\': WRITE_CHAR('\\'); break;
            case '\'': WRITE_CHAR('\''); break;
        }
    }
    """)


def test_preprocessor_if_hex_with_suffix():
    """#if expressions with hex literals carrying u/U/L suffixes (e.g. 0xFFu) must
    not produce 'not a valid macro name' errors.

    CPython's stringlib/codecs.h uses #if STRINGLIB_MAX_CHAR >= 0x80 where
    STRINGLIB_MAX_CHAR expands to 0xFFu, 0xFFFFu, or 0x10FFFFu depending on
    which ucsXlib.h was included.
    """
    state = parse("""
    #define MAX_CHAR 0xFFu
    #if MAX_CHAR >= 0x80
    int selected = 1;
    #else
    int selected = 0;
    #endif
    """)
    assert not state._errors, "unexpected errors: %r" % state._errors
    assert "selected" in state.vars


def test_preprocessor_if_decimal_with_suffix():
    """#if expressions with decimal literals carrying UL suffixes must parse cleanly."""
    state = parse("""
    #define LIMIT 100UL
    #if LIMIT > 50
    int big = 1;
    #else
    int big = 0;
    #endif
    """)
    assert not state._errors, "unexpected errors: %r" % state._errors


def test_for_init_pointer_decl():
    """C99 for-init with a pointer declaration must not produce 'identifier unknown' errors.

    `for (const char *p = str; *p; p++)` declares `p` in the for-init and uses
    it in the condition and increment.  Before the fix, the `*` in `const char *`
    inside `cpre3_parse_statements_in_brackets` converted the partial type into a
    CStatement expression, making `p` unrecognised in the condition/increment parts.
    """
    state = parse("""
    void f(const char *str) {
        for (const char *p = str; *p; p++) {
            int x = *p;
        }
    }
    """)
    assert not state._errors, "unexpected errors: %r" % state._errors


def test_preprocessor_if_wide_char_literal():
    """#if with a wide-char literal (L'x') must not produce 'not expected' errors.

    CPython's osdefs.h defines SEP as L'/' or L'\\\\', and pathconfig.c uses
    `#if SEP == L'/'`.  Before the fix, the preprocessor evaluator saw 'L' as
    an identifier token and then '\\'' as an unexpected character.
    """
    state = parse("""
    #define SEP L'/'
    #if SEP == L'/'
    int on_unix = 1;
    #else
    int on_unix = 0;
    #endif
    """)
    assert not state._errors, "unexpected errors: %r" % state._errors
    assert "on_unix" in state.vars


def test_preprocessor_if_char_literal_comparison():
    """#if with regular char literals in comparisons must evaluate correctly."""
    state = parse("""
    #define MYCHAR '/'
    #if MYCHAR == '/'
    int is_slash = 1;
    #else
    int is_slash = 0;
    #endif
    """)
    assert not state._errors, "unexpected errors: %r" % state._errors
    assert "is_slash" in state.vars


def test_parse_prefix_and_binary_precedence():
    """Testing that `*(int*)p = 42` is parsed correctly as `(*(int*)p) = 42` and not `*((int*)p = 42)`."""
    state = parse("""
    void f() {
        void *p = 0;
        *(int*)p = 42;
    }
    """)
    f = state.funcs["f"]
    assert len(f.body.contentlist) == 2
    stmnt = f.body.contentlist[1]
    # stmnt is an expression statement.
    assert stmnt._op.content == "="
    assert stmnt._rightexpr.content == 42
    assert stmnt._leftexpr._op.content == "*"


def test_parse_cast_postfix_inc_precedence():
    """`(T) *p->ptr++` must parse as `(T)(*((p->ptr)++))`, NOT
    `((T)(*p->ptr))++`.

    Per the C grammar `cast-expression : ( type-name ) cast-expression`,
    postfix operators (++, --, ., ->, [], ()) bind to the operand of the
    cast, not to its result.  Mis-parsing put the `++` on the cast's
    return value (an rvalue), making it a no-op -- which broke marshal's
    byte-stream reader `(unsigned char) *p->ptr++` and meant frozen
    module bytecode never advanced past byte 0.
    """
    state = parse("""
    int f(int *p) {
        return (int) *p++;
    }
    """)
    assert not state._errors, "unexpected errors: %r" % state._errors
    f = state.funcs["f"]
    ret = f.body.contentlist[0]
    expr = ret.body
    # Top-level should NOT have `_op = ++` -- the ++ must be inside the cast.
    assert expr._op is None or expr._op.content != "++", \
        "top-level op should NOT be '++'; ++ must bind to the cast operand, " \
        "got %r (full: %r)" % (expr._op, expr)
    # The outermost should be a cast (CFuncCall with type base).
    # Walk: ret.body._leftexpr is the cast.
    cast = expr._leftexpr
    from cparser import CFuncCall
    assert isinstance(cast, CFuncCall), \
        "expected outermost to be a CFuncCall (cast), got %r" % type(cast).__name__
    # Cast arg should contain both `*` and `++` (deref of postinc).
    arg_str = repr(cast.args[0]) if cast.args else "<no args>"
    assert "*" in arg_str and "++" in arg_str, \
        "cast arg should contain '*' and '++', got %r" % arg_str


def test_parse_deref_postinc_bitwise_precedence():
    """`*p++ & 0x80` must parse as `(*p++) & 0x80`, NOT `*((p++) & 0x80)`.

    This is the pattern from CPython's stringlib find_max_char
    (`if (*p++ & 0x80) return 255;`).  Before the fix, after delegating
    a tighter-binding postfix `++` to the inner expression, the outer
    wrapper went unconditionally to state 8 -- so the next operator
    (here `&`) never got the precedence check against the outer prefix
    `*`, and was instead absorbed by the inner statement, producing the
    wrong AST `*((p++) & 0x80)`.

    The critical invariant: the *top-level* operator of the returned
    expression must be the bitwise `&`, not the unary `*`.  We also
    check that the right-hand side of `&` is the literal 128 and that
    the left-hand side contains both a `*` and a `++` -- so the AST is
    `(deref+postinc) & 128`, regardless of how many intermediate
    wrapper CStatement nodes the parser inserts.
    """
    state = parse("""
    int f(unsigned char *p) {
        return *p++ & 128;
    }
    """)
    assert not state._errors, "unexpected errors: %r" % state._errors
    f = state.funcs["f"]
    # The function body is a single `return EXPR;`; CReturnStatement.body
    # is the returned CStatement.
    ret = f.body.contentlist[0]
    expr = ret.body
    # Top-level: bitwise AND.  This is THE assertion that flips on the
    # precedence fix; before the fix this would be `*` and the test
    # would fail with `_op.content == '*'`.
    assert expr._op is not None and expr._op.content == "&", \
        "top-level op should be '&', got %r (full expr: %r)" % (expr._op, expr)
    assert expr._rightexpr.content == 128, \
        "right side should be the literal 128, got %r" % expr._rightexpr
    # The left side must contain BOTH a `*` (deref) and a `++`
    # (post-increment) anywhere in its subtree -- the parser nests
    # wrapper CStatement nodes around unary operators, so we walk
    # the tree rather than asserting a specific shape.
    def _ops_in(node):
        seen = set()
        stack = [node]
        while stack:
            n = stack.pop()
            if n is None:
                continue
            op = getattr(n, "_op", None)
            if op is not None:
                seen.add(op.content)
            for attr in ("_leftexpr", "_rightexpr", "_middleexpr"):
                child = getattr(n, attr, None)
                if child is not None:
                    stack.append(child)
        return seen
    ops = _ops_in(expr._leftexpr)
    assert "*" in ops, "expected '*' in left subtree, got ops=%r" % ops
    assert "++" in ops, "expected '++' in left subtree, got ops=%r" % ops


def test_parse_typedef_sizeof_in_macro_array_bound():
    """`sizeof(typedef_name)` inside a macro expansion that lands in an
    array-bound position must resolve the typedef.

    Reduced from Modules/_io/textio.c::

        typedef off_t Py_off_t;
        #define COOKIE_BUF_LEN (sizeof(Py_off_t) + 3 * sizeof(int) + sizeof(char))
        static int textiowrapper_parse_cookie(...) {
            unsigned char buffer[COOKIE_BUF_LEN];
            ...
        }

    The same `Py_off_t` used as a plain field type (``Py_off_t start_pos;``)
    is found fine; only the macro-expanded sizeof in the array bound
    raised ``identifier 'Py_off_t' unknown in state 5``.
    """
    state = parse("""
    typedef long Py_off_t;
    #define COOKIE_BUF_LEN (sizeof(Py_off_t) + 3 * sizeof(int))
    int f(void) {
        unsigned char buffer[COOKIE_BUF_LEN];
        return buffer[0];
    }
    """)
    assert not state._errors, "unexpected errors: %r" % state._errors


# ---------------------------------------------------------------------------
# Cross-dict (vars vs funcs) collision warning (task #18).
# See _addToParent in cparser.py.
# ---------------------------------------------------------------------------

def _parse_no_assert(src):
    """Like helpers_test.parse but does NOT assert _errors empty --
    for tests that inspect the errors list directly."""
    import cparser
    state = cparser.State()
    state.autoSetupSystemMacros()
    cparser.parse_code(src, state)
    return state


def test_crossdict_collision_var_vs_func_warns():
    """A name used as both a CFunc and a CVarDecl in the same scope must
    be flagged at parse time -- lookup order would otherwise silently
    pick one or the other."""
    state = _parse_no_assert("""
    int X(void);     /* prototype -- goes into state.funcs */
    static int X;    /* variable  -- goes into state.vars */
    """)
    errors = " ".join(state._errors)
    assert "cross-dict name collision" in errors, (
        "expected cross-dict warning, got: %r" % state._errors)
    assert "'X'" in errors


def test_crossdict_collision_dedup():
    """The warning must fire AT MOST once per name per state."""
    state = _parse_no_assert("""
    int X(void);
    static int X;
    int X(void);     /* second prototype shouldn't re-trigger */
    """)
    n = sum(1 for e in state._errors if "cross-dict name collision" in e)
    assert n == 1, "expected exactly 1 warning, got %d: %r" % (n, state._errors)


def test_two_function_scope_statics_in_different_functions_no_warning():
    """Same-named function-scope statics in DIFFERENT functions are
    legal C -- the parse should produce NO errors at all."""
    parse("""
    int foo(void) { static int X = 1; return X; }
    int bar(void) { static int X = 2; return X; }
    """)


def test_for_loop_init_with_multiple_declarators():
    """``for (T a = 0, b = 1; ...; ...)`` must register BOTH ``a`` and
    ``b`` in the loop's scope.  Real-world hit: CPython's peephole.c:144
    ``for (Py_ssize_t i = 0, pos = c_start; i < n; i++, pos++)`` --
    cparser used to register only ``i`` and report 7 follow-on errors
    for ``pos`` being unknown."""
    parse("""
    int f(int n) {
        int sum = 0;
        for (int i = 0, pos = 100; i < n; i++, pos++) {
            sum += pos;
        }
        return sum;
    }
    """)


def test_file_and_function_scope_same_name_static_no_error():
    """File-scope ``static int X`` and function-scope ``static int X``
    in another function are SEPARATE C objects (different scopes,
    different lifetimes).  The parser must accept both without any
    error -- the interpreter's name mangling
    (``<funcname>__<varname>``) keeps them distinct at runtime."""
    parse("""
    static int X = 1;
    int foo(void) {
        static int X = 2;
        return X;
    }
    """)


if __name__ == "__main__":
    main(globals())
