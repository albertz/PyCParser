
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


if __name__ == "__main__":
    main(globals())
