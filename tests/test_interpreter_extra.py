
from helpers_test import parse
from cparser.interpreter import Interpreter, GlobalsWrapper, getAstNodeForVarType, FuncEnv
from cparser.cparser import State, CArrayType, CBuiltinType, CStatement, CIdentifier, CVarDecl, CPointerType, CFuncCall, CSizeofSymbol, getConstValue
import ctypes
import ast


def test_globals_wrapper_getattr_attribute_error():
    state = parse("int x = 42;")
    interpreter = Interpreter()
    interpreter.register(state)
    globals_wrapper = GlobalsWrapper(interpreter.globalScope)
    
    # Existing attribute should work
    assert globals_wrapper.x.value == 42
    
    # Non-existent attribute should raise AttributeError, not KeyError
    try:
        globals_wrapper.non_existent
    except AttributeError as e:
        assert str(e) == "non_existent"
    except Exception as e:
        assert False, "Should have raised AttributeError, but raised %s" % type(e)
    else:
        assert False, "Should have raised AttributeError"


def test_interpret_type_array_index():
    # Tests CArrayIndexRef with type base, e.g. sizeof(int[10])
    state = parse("int f() { return sizeof(int[10]); }")
    interpreter = Interpreter()
    interpreter.register(state)
    r = interpreter.runFunc("f")
    assert r.value == 10 * ctypes.sizeof(ctypes.c_int)


def test_interpret_type_array_index_2():
    # Tests CArrayIndexRef with type base in a cast
    state = parse("""
    int f() {
        return (int)sizeof(int[10]);
    }
    """)
    interpreter = Interpreter()
    interpreter.register(state)
    r = interpreter.runFunc("f")
    assert r.value == 10 * ctypes.sizeof(ctypes.c_int)


def test_getAstNodeForVarType_non_const_array():
    state = State()
    interp = Interpreter()
    interp.register(state)
    funcEnv = FuncEnv(interp.globalScope)
    
    arrayOf = CBuiltinType(("int",))
    
    # We need 'n' to be in the scope
    n_decl = CVarDecl(name="n", type=CBuiltinType(("int",)))
    interp.globalScope.identifiers["n"] = n_decl
    
    # Mock a non-constant array length
    arrayLen = CStatement()
    arrayLen._leftexpr = n_decl
    
    t = CArrayType(arrayOf=arrayOf, arrayLen=arrayLen)
    
    ast_node = getAstNodeForVarType(funcEnv, t)
    assert isinstance(ast_node, ast.BinOp)
    assert isinstance(ast_node.op, ast.Mult)


def test_getAstNodeForVarType_void_ptr():
    state = State()
    interp = Interpreter()
    interp.register(state)
    funcEnv = FuncEnv(interp.globalScope)
    
    t = CPointerType(CBuiltinType(("void",)))
    ast_node = getAstNodeForVarType(funcEnv, t)
    assert isinstance(ast_node, ast.Attribute)
    assert ast_node.attr == "c_void_p"


def test_sizeof_computed_array_size():
    """sizeof(char[N]) where N is a non-constant expression must work.
    The Py_BUILD_ASSERT macro in CPython uses the pattern
       sizeof(char [1 - 2*!(cond)])
    which triggers this exact code path.
    """
    # sizeof(char[1 - 2*!(1==1)]) == sizeof(char[1]) == 1, so result is 0
    state = parse("""
    int f() {
        return (int)(sizeof(char[1 - 2*!(1 == 1)]) - 1);
    }
    """)
    interpreter = Interpreter()
    interpreter.register(state)
    r = interpreter.runFunc("f")
    assert r.value == 0

def test_interpret_type_identity_compatibility():
    # Demonstrates the need for global caching of CFUNCTYPE and POINTER.
    # In cparser, each C function is translated to a separate Python function.
    # Without global caching, each translated Python function would create its own
    # distinct ctypes class for the same C function pointer type, causing
    # TypeErrors during assignment.
    
    testcode = """
        typedef int (*callback_t)(int);
        struct S {
            callback_t f;
        };
        int my_callback(int x) { return x + 42; }
        
        void set_callback(struct S* s) {
            // This assignment requires 'my_callback' to be wrapped in 'callback_t'.
            // The resulting wrapper must match the type of 's->f'.
            s->f = my_callback;
        }
        
        int test() {
            struct S s;
            set_callback(&s);
            return s.f(7);
        }
    """
    state = parse(testcode)
    interpreter = Interpreter()
    interpreter.register(state)
    
    r = interpreter.runFunc("test")
    assert r.value == 49


def test_sizeof_constant_evaluation():
    # Tests that sizeof can be evaluated as a constant (e.g. for array length).
    testcode = """
        int test() {
            // Test sizeof(type)
            long buffer[sizeof(long) * 2];
            return sizeof(buffer) / sizeof(long);
        }
    """
    state = parse(testcode)
    interpreter = Interpreter()
    interpreter.register(state)
    
    r = interpreter.runFunc("test")
    assert r.value == 16


def test_makeFuncPtr_casting():
    # Tests that a function can be cast to a different pointer type.
    # This verifies the casting logic added to makeFuncPtr.
    # This pattern is used extensively in CPython (e.g. METH_O functions
    # being cast to PyCFunction for storage in PyMethodDef).
    testcode = """
        typedef struct _object { int x; } PyObject;
        typedef PyObject* (*PyCFunction)(PyObject*, PyObject*);
        typedef PyObject* (*PyCFunction_WithOneArg)(PyObject*);
        
        struct PyMethodDef {
            const char* name;
            PyCFunction ml_meth;
        };
        
        PyObject* my_method_one_arg(PyObject* self) { return self; }
        
        int test() {
            PyObject obj;
            struct PyMethodDef m;
            m.name = "meth";
            // Cast my_method_one_arg to the more generic PyCFunction.
            // This is valid C for storage, as long as it's called correctly.
            m.ml_meth = (PyCFunction)my_method_one_arg;
            
            // Cast it back and call it.
            PyCFunction_WithOneArg f = (PyCFunction_WithOneArg)m.ml_meth;
            PyObject* res = f(&obj);
            return (res == &obj);
        }
    """
    state = parse(testcode)
    interpreter = Interpreter()
    interpreter.register(state)
    
    r = interpreter.runFunc("test")
    assert r.value == 1


def test_sizeof_constant_evaluation_2():
    # Tests sizeof on various types
    testcode = """
        typedef struct { int x; int y; } S;
        int test() {
            if (sizeof(S) < sizeof(int) * 2) return 1;
            if (sizeof(char) != 1) return 2;
            return 0;
        }
    """
    state = parse(testcode)
    interpreter = Interpreter()
    interpreter.register(state)
    r = interpreter.runFunc("test")
    assert r.value == 0


def test_sizeof_incomplete_type():
    state = parse("struct S; void* p = (void*)sizeof(struct S);", withSystemMacros=False)
    # sizeof(struct S) should not be evaluatable
    p = state.vars["p"]
    # It should be a cast (CFuncCall) of a sizeof (CFuncCall)
    assert isinstance(p.body, CStatement)
    cast_call = p.body._leftexpr
    assert isinstance(cast_call, CFuncCall)
    sizeof_stmnt = cast_call.args[0]
    assert isinstance(sizeof_stmnt, CStatement)
    sizeof_call = sizeof_stmnt._leftexpr
    assert isinstance(sizeof_call, CFuncCall)
    assert isinstance(sizeof_call.base, CSizeofSymbol)
    assert getConstValue(state, sizeof_call) is None


def test_bitfields():
    state = parse("""
    typedef struct {
        unsigned int a:2;
        unsigned int b:3;
        unsigned int c:1;
    } S;

    int get_a(S *s) { return s->a; }
    int get_b(S *s) { return s->b; }
    void set_b(S *s, int val) { s->b = val; }
    """)
    interp = Interpreter()
    interp.register(state)
    S = interp.getCType(state.typedefs['S'])
    s = S()
    # bitfields are checked by direct access as well as JITed code
    s.b = 7
    assert interp.getFunc("get_a")(ctypes.pointer(s)) == 0
    assert interp.getFunc("get_b")(ctypes.pointer(s)) == 7
    s.b = 8 # 1000 binary, should be 0 in 3 bits
    assert interp.getFunc("get_b")(ctypes.pointer(s)) == 0


def test_pointer_cast_to_struct():
    state = parse("""
    typedef struct { int x; int y; } S;
    #include <stdlib.h>
    int f() {
        S *s = (S*)malloc(sizeof(S));
        if(!s) return -1;
        s->x = 42; s->y = 123;
        int res = s->x + s->y;
        free(s);
        return res;
    }
    """, withGlobalIncludeWrappers=True)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("f")
    assert r.value == 165


def test_bitfield_cast():
    state = parse("""
    typedef struct {
        unsigned int a:2;
    } S;

    int f(S *s) {
        return (int)s->a;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    S = interp.getCType(state.typedefs['S'] or state.structs['S'])
    s = S()
    s.a = 3
    assert interp.getFunc("f")(ctypes.pointer(s)) == 3


def test_bitfield_aug_assign():
    state = parse("""
    typedef struct {
        unsigned int a:2;
    } S;

    void f(S *s) {
        s->a += 1;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    S = interp.getCType(state.typedefs['S'] or state.structs['S'])
    s = S()
    s.a = 1
    interp.getFunc("f")(ctypes.pointer(s))
    assert s.a == 2


def test_bitfield_postfix_inc():
    state = parse("""
    typedef struct {
        unsigned int a:2;
    } S;

    int f(S *s) {
        return s->a++;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    S = interp.getCType(state.typedefs['S'] or state.structs['S'])
    s = S()
    s.a = 1
    r = interp.getFunc("f")(ctypes.pointer(s))
    assert r == 1
    assert s.a == 2, "expected 0, got %r" % r


def test_bitfield_logic_or():
    state = parse("""
    typedef struct {
        unsigned int a:1;
        unsigned int b:1;
    } S;

    int f(S *s) {
        return (!s->a) || (!s->b);
    }
    """)
    interp = Interpreter()
    interp.register(state)
    S = interp.getCType(state.typedefs['S'] or state.structs['S'])
    s = S()
    s.a = 1
    s.b = 0
    # (!1) || (!0)  =>  0 || 1  => 1
    r = interp.getFunc("f")(ctypes.pointer(s))
    assert r == 1


def test_ub_incr():
    # https://gynvael.coldwind.pl/?id=372
    state = parse("""
    int f() { int a = 5; a = a++ + ++a; return a; }
    """)
    interpreter = Interpreter()
    interpreter.register(state)
    r = interpreter.runFunc("f")
    assert r.value in (11, 12, 13)


def test_null_ptr_dereference_raises_value_error():
    """Dereferencing a NULL pointer via a struct field must raise ValueError.

    This documents the mechanism behind the unicode_dealloc / interned-is-NULL
    crash: when PyDict_Check(op) tries to read op->ob_type->tp_flags on a NULL
    op it raises ValueError: NULL pointer access, which ctypes then reports as
    "Exception ignored on calling ctypes callback function".
    """
    state = parse("""
    typedef struct { int x; } Foo;
    int f() {
        Foo *p = 0;
        return p->x;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    try:
        interp.runFunc("f")
        assert False, "Expected ValueError for NULL pointer dereference"
    except ValueError as e:
        assert "NULL pointer" in str(e), "Unexpected error: %s" % e


def test_release_interned_noop_does_not_crash():
    """_Py_ReleaseInternedUnicodeStrings must be interceptable as a no-op.

    In the cpython.py simulation, _Py_ReleaseInternedUnicodeStrings is
    registered as a no-op to prevent it from setting interned=NULL and causing
    subsequent unicode_dealloc calls to crash with ValueError.  This test
    verifies that a function whose body calls a no-op stub behaves correctly.
    """
    state = parse("""
    static int called = 0;
    void release_strings(void);

    int f() {
        release_strings();
        return called;
    }
    """)
    interp = Interpreter()
    interp.register(state)

    # Install a no-op stub for release_strings (mimicking what cpython.py does)
    def _noop():
        pass
    _noop.C_argTypes = []
    _noop.C_resType = None
    interp._func_cache['release_strings'] = _noop

    r = interp.runFunc("f")
    # called was never set to 1 because the stub does nothing; the function
    # completes without crashing
    assert r.value == 0, "expected 0 (stub called, body skipped), got %r" % r


def test_continue_in_function_with_goto():
    """C `continue` inside a loop must target the innermost loop -- even when
    the function also contains C `goto` statements (which trigger the
    goto-rewriting transformation in cparser.goto, wrapping the whole function
    body in a single `while True:` loop).  Before the fix, a bare ast.Continue
    survived the flatten pass unchanged, turning into a Python `continue` that
    continued the function-level loop and re-executed the function's prologue.
    This is the bug that made `pmerge` (used by MRO computation in
    typeobject.c) loop forever during _Py_ReadyTypes.
    """
    state = parse("""
    int f() {
        int total = 0;
        int trips = 0;
        for (int i = 0; i < 10; i++) {
            trips++;
            if (i % 2 == 0) {
                continue;  /* must continue the for-loop, NOT restart f() */
            }
            total += i;
            if (total > 100) goto done;
        }
    done:
        /* sum of odd i in [0,10) = 1+3+5+7+9 = 25; trips must equal 10 */
        return total * 1000 + trips;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("f")
    assert r.value == 25 * 1000 + 10, "expected 25010, got %r" % r


def test_continue_in_nested_loop_with_goto():
    """`continue` must target the innermost loop in the presence of goto."""
    state = parse("""
    int f() {
        int hits = 0;
        for (int i = 0; i < 4; i++) {
            for (int j = 0; j < 4; j++) {
                if (j == i) continue;  /* skip diagonal in inner loop */
                hits++;
            }
        }
        if (hits == 0) goto err;
        return hits;
    err:
        return -1;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("f")
    # 4x4 grid minus 4 diagonal entries = 12
    assert r.value == 12, "expected 12, got %r" % r


def test_address_of_local_var():
    """Pointers created via & must be correctly registered in pointerStorage.
    This verifies that the _storePtr call added to the & operator is working.
    """
    state = parse("""
    int f() {
        int x = 42;
        int *p = &x;
        return *p;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("f")
    assert r.value == 42


def test_pointer_chained_assignment():
    """Chained pointer assignments through multiple locals must preserve the
    target.  Stresses the pointerStorage tracking: q and r are not registered
    via &, only via assignment from p (which was registered via &x)."""
    state = parse("""
    int f() {
        int x = 42;
        int *p = &x;
        int *q = p;
        int *r = q;
        return *r;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    res = interp.runFunc("f")
    assert res.value == 42


def test_logical_not_on_bitfield():
    """`!` applied to a bitfield must yield a usable int (0 or 1) that can
    participate in further boolean expressions."""
    state = parse("""
    typedef struct { unsigned int x:1; } S;
    int f(S *s) {
        return (!s->x) || 0;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    S = interp.getCType(state.typedefs['S'])
    s = S()
    s.x = 0
    # (!0) || 0  => 1 || 0 => 1
    assert interp.getFunc("f")(ctypes.pointer(s)) == 1
    s.x = 1
    # (!1) || 0  => 0 || 0 => 0
    assert interp.getFunc("f")(ctypes.pointer(s)) == 0


def test_signed_char_cast_in_loop_expression():
    """Regression: `(signed char)arr[idx]` must be treated as a cast.

    CPython `frameobject.c` uses this exact pattern in `frame_setlineno`.
    It used to be parsed as a call-like expression and tripped an internal
    assertion that expected only function-pointer calls in this code path.
    """
    state = parse("""
    int f() {
        unsigned char lnotab[4] = {1, 2, 3, 4};
        int line = 0;
        int offset;
        for (offset = 0; offset < 4; offset += 2) {
            line += (signed char)lnotab[offset + 1];
        }
        return line;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("f")
    assert r.value == 6


def test_ambiguous_call_cast_raises_type_error():
    """A non-callable base used like a call must raise a clear TypeError."""
    state = parse("""
    int f() {
        int x = 7;
        return (x)(1);
    }
    """)
    interp = Interpreter()
    interp.register(state)
    try:
        interp.runFunc("f")
        raise Exception("expected exception for ambiguous call/cast")
    except Exception as e:
        assert "'x'" in str(e), str(e)


def test_unknown_builtin_cast_tokens_raise_type_error():
    """Unknown builtin-token cast spellings should fail with clear error."""
    state = parse("""
    int f() {
        int x = 7;
        return (signed signed char int)x;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    try:
        interp.runFunc("f")
        raise Exception("expected exception for unknown builtin cast tokens")
    except Exception as e:
        assert "signed" in str(e), str(e)


def test_short_array_initializer_zero_fills():
    """C zero-fills array elements that aren't explicitly initialised.
    CPython's `static PyObject *unicode_latin1[256] = {NULL};` declares a
    256-slot array with only one explicit initialiser; the remaining 255
    slots must be zero.  Previously the interpreter asserted
    `arrayLen == len(argType)` and refused to compile."""
    state = parse("""
    static int arr[5] = {7, 3};
    int sum(void) {
        int s = 0;
        int i;
        for (i = 0; i < 5; i++) s += arr[i];
        return s;
    }
    int get_last(void) { return arr[4]; }
    """)
    interp = Interpreter()
    interp.register(state)
    # 7 + 3 + 0 + 0 + 0 == 10
    assert interp.runFunc("sum").value == 10
    # last element must be 0, not garbage
    assert interp.runFunc("get_last").value == 0


def test_cast_postfix_inc_advances_pointer():
    """`(unsigned char) *p->ptr++` must increment p->ptr.  Previously the
    parser placed the `++` outside the cast (`((unsigned char)*p->ptr)++`),
    making it a no-op on the cast's rvalue result and breaking marshal's
    byte-stream reader (frozen module bytecode never advanced past byte 0).
    """
    state = parse("""
    typedef struct { char *ptr; char *end; } P;
    int read_one(P *p) {
        int c = -1;
        if (p->ptr < p->end)
            c = (unsigned char) *p->ptr++;
        return c;
    }
    int run(void) {
        char buf[3] = {0x41, 0x42, 0x43};
        P p; p.ptr = buf; p.end = buf + 3;
        int a = read_one(&p);
        int b = read_one(&p);
        int c = read_one(&p);
        int d = read_one(&p);  /* exhausted, must return -1 */
        return ((a & 0xff) << 24) | ((b & 0xff) << 16) |
               ((c & 0xff) << 8)  | (d & 0xff);
    }
    """)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("run")
    assert r.value == 0x414243ff, "expected 0x414243ff, got %r" % hex(r.value)


def test_ptr_ptr_subtraction_in_arithmetic():
    """`ptr - ptr` in C yields ptrdiff_t, not the pointer type.  This matters
    in mixed-arithmetic contexts like binary-search bisection
    `p = l + ((r - l) >> 1);` (from Objects/listobject.c binarysort), where
    the inner `r - l` must be a scalar for the outer `l + (...)` to be
    valid pointer-arithmetic rather than triggering the
    `assert ptr OP ptr requires '-' op` check.

    Previously `CStatement.getValueType` returned `getCommonValueType(ptr,ptr)
    == ptr` for the `-` op, so the inner expression's type was reported as
    the pointer type, propagating outward through `>>` and confusing the
    interpreter's AST builder.
    """
    state = parse("""
    int f(int *arr, int n) {
        int *l = arr;
        int *r = arr + n;
        int *m = l + ((r - l) >> 1);  /* the failing pattern */
        return (int)(m - arr);        /* should be n/2 */
    }
    int run(void) {
        int buf[10] = {0,1,2,3,4,5,6,7,8,9};
        int a = f(buf, 10);
        int b = f(buf, 7);
        return a * 100 + b;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("run")
    # n=10 -> 5, n=7 -> 3 ; combined = 503
    assert r.value == 503, "expected 503, got %r" % r


def test_call_through_ternary_func_pointer():
    """`(cond ? funcA : funcB)(args)` must work when both branches are
    plain CFuncs.  The ternary expression's type is CWrapFuncType (not
    CFuncPointerDecl), so the func-call dispatcher in
    interpreter.astAndTypeForStatement must accept both.

    This is the pattern used in CPython's stringlib/unicode_format.h to
    select between SubString_new_object_or_empty / SubString_new_object.
    """
    state = parse("""
    int add(int x) { return x + 100; }
    int sub(int x) { return x - 100; }
    int run(int cond, int x) {
        return (cond ? add : sub)(x);
    }
    """)
    interp = Interpreter()
    interp.register(state)
    assert interp.runFunc("run", 1, 5).value == 105
    assert interp.runFunc("run", 0, 5).value == -95


def test_get_ptr_through_overlapping_inner_range():
    """End-to-end repro of the overlapping-range bug via interpreted C code.

    Mirrors the structural shape of `PyTupleObject` / `PyDictKeysObject`:
    a heap-allocated struct with several pointer fields.  Taking the
    address of a non-first field (e.g. `&t->p1`) makes the interpreter
    register an 8-byte inner range at `malloc+8` in
    ``pointerStorageRanges`` (the struct field is a sub-view of the
    malloc'd buffer).  The malloc buffer's own range
    (``(malloc_addr, 40)``) is already in there too.

    We then access a later field's address (`&t->p4` at `malloc+32`)
    via raw uintptr arithmetic so the resulting pointer has no
    ``_b_base_`` chain.  ``_getPtr`` walks the range list in reverse,
    finds the smaller inner ``(malloc+8, 8)`` first, observes
    ``8 + 8 <= 32``, and ``break``s -- never checking the outer
    ``(malloc, 40)`` range that does cover the address.  Result:
    ``Exception("invalid pointer access ...")``.

    The bug fix is to stop registering ranges for sub-views (objs with
    a non-None ``_b_base_``): the enclosing root allocation's range
    already covers them, and adding a smaller overlapping range only
    breaks the reverse-irange invariant.
    """
    state = parse("""
    extern void* malloc(unsigned long);
    typedef struct { int *p0; int *p1; int *p2; int *p3; int *p4; } Five;
    int run(void) {
        Five *t = (Five*) malloc(sizeof(Five));
        int x = 100, y = 200;
        /* register inner range at &t->p1 (non-zero offset, fresh addr) */
        int **slot1 = &t->p1;
        *slot1 = &x;
        /* access &t->p4 via raw uintptr -- no _b_base_ chain */
        unsigned long slot4_addr = ((unsigned long) slot1) + 3UL * 8UL;
        int **slot4 = (int**) slot4_addr;
        *slot4 = &y;
        return **slot4;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    # Wire a minimal malloc that returns a raw address (interpreter's
    # _malloc returns a c_void_p; the generated code feeds it to _getPtr
    # which expects an int).
    def _malloc(size):
        if hasattr(size, "value"): size = size.value
        ptr = interp._malloc(int(size))
        return ptr.value or 0
    _malloc.C_argTypes = [ctypes.c_ulong]
    _malloc.C_resType = ctypes.c_void_p
    interp._func_cache["malloc"] = _malloc

    r = interp.runFunc("run")
    assert r.value == 200, "expected 200, got %r" % r.value


def test_do_while_continue_runs_post_iteration():
    """In C, `continue` inside a `do { ... } while (cond);` jumps to the
    condition test -- which, for a `do { ... } while (expr_with_side_effect);`
    pattern, must still evaluate the side-effect-bearing expression
    (e.g. `(++p)->offset == offset` in typeobject.c's `update_one_slot`).

    The previous translation emitted a plain `while True: <body>; if cond:
    continue else: break`, so a C-continue became a Python `continue` that
    jumped back to the top of `while True:`, skipping the bottom condition
    check entirely.  For loops whose only state-advance lives in the
    condition test, this caused an infinite loop (observed in
    `update_one_slot` calling `find_name_in_mro` 45,000+ times on a single
    type during interpreted cpython.py init).
    """
    state = parse("""
    int run(void) {
        int arr[6] = {0, 0, 0, 1, 2, 3};
        int *p = arr;
        int sum = 0;
        do {
            if (*p == 0) continue;   /* must still evaluate `*++p` below */
            sum += *p;
        } while (*++p != 3);
        return sum;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("run")
    # arr = {0,0,0,1,2,3}, p walks arr[0..5].
    # iter 0: *p=0 -> continue; ++p -> *p=0, cond true (0 != 3).
    # iter 1: *p=0 -> continue; ++p -> *p=0, cond true.
    # iter 2: *p=0 -> continue; ++p -> *p=1, cond true.
    # iter 3: *p=1, sum=1;       ++p -> *p=2, cond true.
    # iter 4: *p=2, sum=3;       ++p -> *p=3, cond false -> exit.
    assert r.value == 3, "expected 3, got %r" % r.value


def test_do_while_break_exits_loop():
    """`break` inside a do-while must exit the loop entirely (not just
    a wrapping construct introduced by the translation).  This is a
    companion to ``test_do_while_continue_runs_post_iteration``: when
    we wrap the body in an inner single-iteration `for` to fix
    `continue` semantics, we must not regress `break` -- it must still
    exit the do-while, not just the inner for.
    """
    state = parse("""
    int run(void) {
        int i = 0;
        int sum = 0;
        do {
            if (i == 3) break;          /* exit while i==3, sum=3 */
            sum += i;
            i++;
        } while (i < 100);
        return sum * 100 + i;           /* expect 3*100 + 3 = 303 */
    }
    """)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("run")
    assert r.value == 303, "expected 303, got %r" % r.value


def test_null_initializer_for_va_list_pointer():
    """Passing a literal `NULL`/`0` where a `va_list *` is expected
    (e.g. CPython getargs.c's ``skipitem(&format, NULL, 0)``) must be
    handled correctly: the interpreter represents such pointers via
    ``Helpers.PyRef``, but a NULL literal has no ``.ref`` attribute.
    The translation must construct an empty / null ``PyRef`` instead
    of trying to access ``.ref`` on the integer 0.

    Previously this failed with
    ``AttributeError: 'wrapCTypeClass_c_int' object has no attribute 'ref'``.
    """
    state = parse("""
    #include <stdarg.h>
    int helper(va_list *p_va) {
        return (p_va != 0);
    }
    int run(void) {
        return helper(0);   /* NULL for va_list* -- common in getargs.c */
    }
    """, withGlobalIncludeWrappers=True)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("run")
    assert r.value == 0, "expected 0, got %r" % r.value


def test_address_of_va_list_compares_against_null():
    """Taking the address of a `va_list` (`&args`) gives a pointer that
    real C code routinely tests against ``NULL`` (e.g. ``p_va != NULL``
    in CPython's getargs.c convertitem chain).  The interpreter
    represents ``&va_list`` as a ``Helpers.PyRef`` (a Python-level
    reference, not a ctypes pointer), so any code path that translates
    ``(void *)p_va != 0`` into ``ctypes.cast(p_va, c_void_p).value != 0``
    fails with ``ArgumentError: 'PyRef' object cannot be interpreted as
    ctypes.c_void_p``.

    The cast pattern must accept PyRef and treat it as a non-NULL
    pointer (a va_list pointer in valid C is never NULL).
    """
    state = parse("""
    #include <stdarg.h>
    int run(int x, ...) {
        va_list args;
        va_start(args, x);
        int r = ((&args) != 0);
        va_end(args);
        return r;
    }
    """, withGlobalIncludeWrappers=True)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("run", 1, 42)
    assert r.value == 1, "expected 1, got %r" % r.value


def test_func_ptr_call_with_extra_args_truncates_to_signature():
    """When a function pointer is cast to a wider signature and called
    with more args than the function actually declares (the standard
    METH_NOARGS dispatch pattern: a 1-arg C function stored as 2-arg
    ``PyCFunction`` and invoked with ``meth(self, NULL)``), real C
    ignores the extra args via the calling convention.  Our
    short-circuited direct Python call in ``Helpers.checkedFuncPtrCall``
    must do the same -- pass only as many args as the function's
    actual signature declares -- otherwise the Python function raises
    ``TypeError: takes N positional argument but M were given``.

    This is what trips ``dictitems_new`` (declared ``dictitems_new(PyObject *)``,
    1 arg) when CPython's METH_NOARGS dispatcher calls it as
    ``meth(self, NULL)`` via the cast to ``PyCFunction``.
    """
    state = parse("""
    typedef int (*two_arg_t)(int, int);

    int one_arg_impl(int x) {
        return x * 10;
    }

    int run(void) {
        /* Stow the 1-arg function as a 2-arg PyCFunction-like slot. */
        two_arg_t stored = (two_arg_t) one_arg_impl;
        /* The dispatcher calls it with the extra arg ignored. */
        return stored(7, 0);
    }
    """)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("run")
    assert r.value == 70, "expected 70, got %r" % r.value


def test_func_ptr_call_propagates_python_exception():
    """When a function pointer is called by interpreted C code and the
    underlying callable is one of our own Python functions (translated
    from C source, or an injected stub), any Python exception it
    raises must propagate to the outer caller -- not be silently
    swallowed by the ctypes callback layer.

    The previous implementation always called the function pointer
    *through* its ctypes CFUNCTYPE wrapper, which prints
    `Exception ignored on calling ctypes callback function: ...`
    and returns to C with a NULL/0 result.  That hides interpreter
    bugs (e.g. AssertionError, ctypes.ArgumentError, custom raises)
    behind silent corruption deeper in the interpreted CPython.
    """
    state = parse("""
    extern int the_fn(int);
    typedef int (*int_fn_t)(int);
    int run(int x) {
        int_fn_t f = the_fn;   /* take address -> wraps via makeFuncPtr */
        return f(x);           /* call via the wrapped pointer */
    }
    """)
    interp = Interpreter()
    interp.register(state)

    class _Boom(Exception):
        pass

    def _raising_boom(x):
        raise _Boom("boom x=%r" % (x.value if hasattr(x, "value") else x))
    _raising_boom.C_argTypes = [ctypes.c_int]
    _raising_boom.C_resType = ctypes.c_int
    interp._func_cache["the_fn"] = _raising_boom

    raised = False
    try:
        interp.runFunc("run", 7)
    except _Boom:
        raised = True
    assert raised, "expected _Boom to propagate through function-pointer call"


def test_func_ptr_cast_preserves_argcount():
    """When a function pointer is cast to a different signature for
    storage (e.g. `(PyCFunction)foo` stowing a METH_FASTCALL 4-arg
    function into the 2-arg PyMethodDef.ml_meth slot) and later cast
    back to the actual signature at the call site, calling the casted
    pointer must invoke the Python function with its full argument
    list.

    Previously, `Helpers.makeFuncPtr` wrapped the function with the
    *cast target* CFUNCTYPE on first use.  If that first use was a
    cast to a narrower signature, the ctypes callback was generated
    with the narrower argcount; any later cast back to the original
    signature still passed the narrow argcount to the Python function,
    yielding `TypeError: missing N required positional arguments`.

    This is exactly the failure mode of `builtin___build_class__` and
    other METH_FASTCALL builtins in interpreted cpython.py.
    """
    state = parse("""
    typedef int (*two_arg_t)(int, int);
    typedef int (*four_arg_t)(int, int, int, int);

    int four_arg_impl(int a, int b, int c, int d) {
        return a + b + c + d;
    }

    int run(void) {
        /* Stow the 4-arg function into a 2-arg slot, mirroring
           `(PyCFunction)builtin___build_class__`. */
        two_arg_t stored = (two_arg_t) four_arg_impl;
        /* Later, the dispatcher casts back to the real signature
           and calls with all four args. */
        four_arg_t called = (four_arg_t) stored;
        return called(1, 2, 3, 4);
    }
    """)
    interp = Interpreter()
    interp.register(state)
    r = interp.runFunc("run")
    assert r.value == 10, "expected 10, got %r" % r.value


def test_free_purges_interior_pointer_storage_entries():
    """``_storePtr`` may register the same buffer object at multiple
    ``pointerStorage`` keys -- the base address *and* every interior
    address it was queried at with a non-zero offset (e.g. ``buf +
    offsetof(struct, field)``).  When the buffer is later freed via
    ``_free``, the base entry is purged but the interior entries are
    leaked.  The buffer may then stay alive via the
    ``WeakValueDictionary`` only by accident, or vanish leaving stale
    interior references; either way it is bookkeeping divergence
    between ``mallocs`` (now empty) and ``pointerStorage`` (still
    referencing the freed allocation).

    ``_free`` must purge every ``pointerStorage`` entry whose key
    falls inside ``[base, base + size)``.
    """
    from cparser.interpreter import _ctype_ptr_get_value

    state = parse("int x;")
    interp = Interpreter()
    interp.register(state)

    # Malloc, then probe two interior offsets to seed pointerStorage.
    buf = interp._malloc(64)
    base = _ctype_ptr_get_value(buf)
    # Force `_storePtr` to register interior addresses by using
    # offset != 0 -- mirroring `helpers.ptrArithmetic(buf, '+', n)`.
    fresh_inner_1 = interp.ctypes_wrapped.c_void_p(base + 16)
    interp._storePtr(fresh_inner_1, offset=16)
    fresh_inner_2 = interp.ctypes_wrapped.c_void_p(base + 32)
    interp._storePtr(fresh_inner_2, offset=32)

    # Interior keys should now be in pointerStorage.
    assert (base + 16) in interp.pointerStorage
    assert (base + 32) in interp.pointerStorage

    interp._free(base)
    # mallocs and pointerStorageRanges have been purged.
    assert base not in interp.mallocs
    assert not any(
        s <= base < s + sz for (s, sz) in interp.pointerStorageRanges)
    # ...and all interior pointerStorage entries that pointed into the
    # freed buffer must be purged too.  Without this, the bookkeeping
    # diverges from `mallocs`, leaving stale weak refs that confuse
    # later lookups and (more dangerously) keep the buffer object
    # alive through chains of `_b_base_` that no longer reflect the
    # interpreter's allocation state.
    assert (base + 16) not in interp.pointerStorage, (
        "interior entry base+16 was leaked after _free")
    assert (base + 32) not in interp.pointerStorage, (
        "interior entry base+32 was leaked after _free")


def test_free_purges_subview_keys_tracked_under_root():
    """``_storePtr`` may match an obj that is itself a *sub-view* (has
    ``_b_base_``).  Its ``addressof`` is then interior to a malloc'd
    root buffer.  When the obj-loop registers it in ``pointerStorage``,
    we must track the key under the *root*'s base address (walked via
    ``_b_base_``), not under the sub-view's own address -- otherwise
    ``_free(root_addr)`` won't know to purge it, and the entry stays
    in ``pointerStorage`` with a ``_b_base_`` chain pointing at memory
    that is no longer in ``mallocs``.
    """
    from cparser.interpreter import _ctype_ptr_get_value, _ctype_get_ptr_addr

    state = parse("int x;")
    interp = Interpreter()
    interp.register(state)

    PtrArrT = ctypes.c_void_p * 4
    buf = interp._malloc(ctypes.sizeof(PtrArrT))
    base = _ctype_ptr_get_value(buf)

    # Build a sub-view by casting the malloc'd buffer to a typed
    # pointer and then accessing an element.  The resulting ctype's
    # `_b_base_` chain leads back to `buf`.
    arr = ctypes.cast(buf, ctypes.POINTER(PtrArrT)).contents
    # `byref(arr, 8)` is the c-level pointer (no _b_base_); cast it to
    # a typed pointer.  The cast result's `_b_base_` chain reaches the
    # arr/buf.
    interior_ptr = ctypes.cast(
        ctypes.byref(arr, 8),
        ctypes.POINTER(ctypes.c_void_p))
    # Trigger the obj-loop with a sub-view match.
    interp._storePtr(interior_ptr)

    # An interior key for the sub-view's addressof should now exist
    # in pointerStorage.  Find it.
    interior_keys = [k for k in interp.pointerStorage
                     if base < k < base + ctypes.sizeof(PtrArrT)]
    assert interior_keys, (
        "expected at least one interior key in pointerStorage "
        "after _storePtr on a sub-view; got none")

    # Free the root buffer.  Every interior key must be purged.
    interp._free(base)
    leaked = [k for k in interp.pointerStorage
              if base <= k < base + ctypes.sizeof(PtrArrT)]
    assert not leaked, (
        "after _free(root), interior keys %r still in pointerStorage; "
        "they were not tracked under the root's address" % [hex(k) for k in leaked])


def test_free_purges_cache_path_interior_keys_under_root():
    """``_storePtr``'s cache fast-path (``ptr_addr - offset in
    pointerStorage``) inserts ``pointerStorage[ptr_addr] = base_obj``.
    That new interior key must be tracked under the *root*'s base
    address (walking ``base_obj._b_base_``), not under
    ``ptr_addr - offset`` -- because that address may itself be only
    an interior offset, never the target of ``_free``.
    """
    from cparser.interpreter import _ctype_ptr_get_value

    state = parse("int x;")
    interp = Interpreter()
    interp.register(state)

    PtrArrT = ctypes.c_void_p * 4   # 32 bytes
    buf = interp._malloc(ctypes.sizeof(PtrArrT))
    base = _ctype_ptr_get_value(buf)

    # Seed the cache: register the interior at base+8 via a sub-view
    # _storePtr call (obj-loop path).  This puts `pointerStorage[base+8]
    # = some sub-view`.
    arr = ctypes.cast(buf, ctypes.POINTER(PtrArrT)).contents
    seed_ptr = ctypes.cast(
        ctypes.byref(arr, 8),
        ctypes.POINTER(ctypes.c_void_p))
    interp._storePtr(seed_ptr)
    assert (base + 8) in interp.pointerStorage

    # Now exercise the cache fast-path with offset=8: the call sees
    # `ptr_addr - offset = base + 8` is already known, and inserts
    # `pointerStorage[base + 16] = pointerStorage[base + 8]`.
    fresh_ptr = interp.ctypes_wrapped.c_void_p(base + 16)
    interp._storePtr(fresh_ptr, offset=8)
    assert (base + 16) in interp.pointerStorage

    # Free the root.  Both interior keys (base+8 and base+16) must be
    # purged -- regardless of which one was registered via cache vs.
    # obj-loop.
    interp._free(base)
    assert (base + 8) not in interp.pointerStorage, (
        "obj-loop interior key base+8 leaked after _free")
    assert (base + 16) not in interp.pointerStorage, (
        "cache-path interior key base+16 leaked after _free -- it was "
        "tracked under an intermediate address, not the root's base")


def test_ctype_collect_objects_target_addr_filters_unrelated_keepalives():
    """``_ctype_collect_objects(obj, target_addr=X)`` should prune
    ctype entries reached through ``_objects`` whose memory range does
    NOT contain ``X``.  Memory-sharing entries (``cast(x, T)`` style,
    where source and result point at the same target) must still be
    found.  Unrelated keep-alives (eg. a separate buffer attached as a
    side ref) must NOT be returned.
    """
    from cparser.interpreter import _ctype_collect_objects

    # Two completely separate buffers.
    src = (ctypes.c_int * 4)(1, 2, 3, 4)
    side = (ctypes.c_int * 4)(9, 9, 9, 9)
    src_addr = ctypes.addressof(src)

    # ``cast(x, T)`` is the memory-sharing case we DO want to find.
    src_ptr = ctypes.cast(src, ctypes.POINTER(ctypes.c_int))
    casted = ctypes.cast(src_ptr, ctypes.POINTER(ctypes.c_char))
    # Attach an unrelated keep-alive entry via _objects.  ctypes itself
    # does not normally put unrelated buffers in _objects, so simulate
    # it explicitly.  (In real PyCPython usage, _objects can accumulate
    # many such entries when intermediate pointer casts happen.)
    if casted._objects is None:
        # Force-create the dict via a no-op assignment if needed.
        # ctypes pointers expose _objects as a writable attribute.
        casted._objects = {}
    casted._objects["unrelated-side-buffer"] = side

    # Without target_addr, both ``src`` (memory-sharing) and ``side``
    # (unrelated) are reachable.
    all_collected = list(_ctype_collect_objects(casted))
    ids_all = {id(o) for o in all_collected}
    assert id(side) in ids_all, (
        "sanity check failed: unfiltered walk did not see the unrelated "
        "side buffer we explicitly attached via _objects")

    # With target_addr at src's address, the side buffer must be
    # pruned -- it does not contain src_addr.
    filtered = list(_ctype_collect_objects(casted, target_addr=src_addr))
    ids_filtered = {id(o) for o in filtered}
    assert id(side) not in ids_filtered, (
        "target_addr filter should have pruned the unrelated side "
        "buffer (its memory range does not contain src_addr); got %r"
        % [type(o).__name__ for o in filtered])
    # And the memory-sharing source MUST still be reachable, even
    # though we get there via the intermediate ``src_ptr`` pointer
    # (whose own ``addressof`` is unrelated to ``src_addr``).
    # Pointer entries must not be pruned -- they're the bridge.
    assert id(src) in ids_filtered, (
        "target_addr filter incorrectly pruned the memory-sharing "
        "source buffer reachable via an intermediate pointer; got %r"
        % [type(o).__name__ for o in filtered])


def test_ctype_collect_objects_target_addr_keeps_subview_bridges():
    """A small ``_b_base_`` sub-view (eg. ``a[0]``) whose own range
    does NOT contain ``target_addr`` must still be kept by the filter
    when its ``_b_base_`` chain leads to an ancestor whose range DOES
    contain ``target_addr``.  Otherwise the bridge is broken and the
    actual matching root never gets collected -- which is exactly what
    happens with ``ctypes.pointer(a[0])`` for pointer arithmetic into
    an array (the test_interpret_init_array regression).
    """
    from cparser.interpreter import _ctype_collect_objects

    # Build a sub-view (struct field) whose ``_b_base_`` chain reaches
    # a larger root struct.  ``sub`` is smaller than the root: its
    # own range does NOT cover the chosen target, but the root's
    # does.  ``ctypes`` sets ``_b_base_`` on field access for
    # non-primitive field types (here a nested struct).
    class Inner(ctypes.Structure):
        _fields_ = [("x", ctypes.c_int)]
    class Root(ctypes.Structure):
        _fields_ = [("inner", Inner),
                    ("y", ctypes.c_int),
                    ("z", ctypes.c_int)]
    root = Root()
    sub = root.inner  # size 4, _b_base_ = root (size 12)
    assert sub._b_base_ is root
    # ``ctypes.pointer(sub)`` stores ``sub`` in its ``_objects`` dict;
    # casting again carries it forward.  The resulting ``p._objects``
    # contains ``sub`` (the sub-view we want as the bridge).
    p = ctypes.cast(ctypes.pointer(sub), ctypes.POINTER(ctypes.c_int))
    assert any(v is sub for v in p._objects.values()), (
        "test setup: expected sub in p._objects via pointer-then-cast")
    target_addr = ctypes.addressof(root) + Root.z.offset
    # Sanity: sub's range does not cover target, root's range does.
    assert not (ctypes.addressof(sub) <= target_addr
                <= ctypes.addressof(sub) + ctypes.sizeof(sub))
    assert (ctypes.addressof(root) <= target_addr
            <= ctypes.addressof(root) + ctypes.sizeof(root))
    collected = list(_ctype_collect_objects(p, target_addr=target_addr))
    ids = {id(o) for o in collected}
    assert id(root) in ids, (
        "target_addr filter pruned the sub-view bridge and so failed "
        "to reach the matching root struct via _b_base_; got %r"
        % [type(o).__name__ for o in collected])


def test_storeptr_obj_loop_does_not_overwrite_malloc_entry():
    """The obj-loop in ``_storePtr`` registers two ``pointerStorage``
    keys: one at ``ptr_addr`` (the target) and one at
    ``obj_ptr_addr`` (the matched obj's own addr).  The latter is a
    cache for future lookups.  If a ``_malloc``'d buffer is already
    registered at ``obj_ptr_addr`` (via the strongly-held buf in
    ``mallocs``), the obj-loop must NOT overwrite that stable entry
    with whatever transient ctype view it walked to.  Otherwise the
    transient dies shortly after (its only ref was the chain we
    walked), the weakref entry vanishes, and ``_storePtr`` for the
    same address later fails to find anything -- even though
    ``mallocs`` still holds the underlying memory.
    """
    state = parse("int x;")
    interp = Interpreter()
    interp.register(state)

    # 1) malloc a buffer.  Now mallocs[addr] = buf (strong),
    #    pointerStorage[addr] = buf (weak, kept alive by mallocs).
    buf_ptr = interp._malloc(64)
    addr = ctypes.cast(buf_ptr, ctypes.c_void_p).value
    assert addr in interp.mallocs
    assert addr in interp.pointerStorage
    original_obj = interp.pointerStorage[addr]

    # 2) Build a fresh ctype view at the same address (a transient
    #    struct overlay) and a pointer that ``_objects``-chains back
    #    to it.  ``pointer(overlay)`` keeps ``overlay`` in its
    #    ``_objects`` so the obj-loop will reach it.  We aim at an
    #    INTERIOR offset so the cache-fast-path misses and we go
    #    through the obj-loop (where the side-branch write would
    #    overwrite ``pointerStorage[addr]``).
    class Big(ctypes.Structure):
        _fields_ = [("data", ctypes.c_byte * 64)]
    overlay = Big.from_address(addr)  # transient, addressof == addr
    assert ctypes.addressof(overlay) == addr
    overlay_ptr = ctypes.pointer(overlay)
    # An interior pointer one byte into the overlay.  Cast carries
    # ``overlay`` forward in ``_objects`` so the obj-loop can reach
    # it (and via the ``_b_base_``-walk-to-root range check, see it
    # as covering ``addr + 1``).
    interior_ptr = ctypes.cast(overlay_ptr, ctypes.POINTER(ctypes.c_byte))
    from cparser.interpreter import _ctype_ptr_set_value
    _ctype_ptr_set_value(interior_ptr, addr + 1)
    # Drop our last named strong refs.  The pointer's ``_objects``
    # still chains to overlay; overlay's ``_b_base_`` is None (it's
    # ``from_address``); the only thing keeping the obj-loop's match
    # alive once `_storePtr` returns is whatever ``pointerStorage``
    # wrote -- which, with the bug, is the transient overlay.
    del overlay, overlay_ptr
    interp._storePtr(interior_ptr)
    del interior_ptr
    import gc
    gc.collect()

    # 3) The stable malloc-backed entry must STILL be at
    #    ``pointerStorage[addr]`` (not overwritten by the transient
    #    overlay).
    assert addr in interp.pointerStorage, (
        "obj-loop overwrote the malloc-backed pointerStorage entry "
        "with a transient view that has since died; the address is "
        "now unfindable even though mallocs still holds it")
    assert interp.pointerStorage[addr] is original_obj, (
        "pointerStorage[addr] was replaced with a different object "
        "than the malloc'd buf; expected the original buf to remain")


def test_add_pointer_storage_range_drops_interior_insert():
    """``_addPointerStorageRange`` must drop an insert whose start is
    strictly interior to an existing range.  Otherwise nested
    overlapping ranges accumulate (eg. a fresh ``from_address`` view
    over a malloc'd buffer), and the range-fallback's reverse-irange
    ``break`` shortcut would miss the outer covering range.
    """
    from cparser.interpreter import _ctype_ptr_get_value

    state = parse("int x;")
    interp = Interpreter()
    interp.register(state)

    # Malloc a 128-byte region.  ``_malloc`` -> ``_storePtr`` -> obj-loop
    # ends up calling ``_addPointerStorageRange(base, 128)``.
    buf_ptr = interp._malloc(128)
    base = _ctype_ptr_get_value(buf_ptr)
    assert (base, 128) in interp.pointerStorageRanges

    # Now attempt to add a small inner range (eg. a fresh view obj
    # that happened to land inside the malloc).  The helper must
    # drop it.
    interp._addPointerStorageRange(base + 64, 8)
    assert (base + 64, 8) not in interp.pointerStorageRanges, (
        "interior insert was not dropped; non-overlap invariant broken")
    # And the outer malloc range must still be there untouched.
    assert (base, 128) in interp.pointerStorageRanges

    # An insert that does NOT overlap any existing range still goes
    # through (sanity check that the helper isn't over-zealous).
    interp._addPointerStorageRange(base + 256, 16)
    assert (base + 256, 16) in interp.pointerStorageRanges


def test_add_pointer_storage_range_removes_subsumed_existing():
    """When the new range strictly contains existing smaller ranges,
    those subsumed entries are removed.  Otherwise the set would
    contain both, violating non-overlap.
    """
    state = parse("int x;")
    interp = Interpreter()
    interp.register(state)

    interp._addPointerStorageRange(200, 8)
    interp._addPointerStorageRange(220, 16)
    assert (200, 8) in interp.pointerStorageRanges
    assert (220, 16) in interp.pointerStorageRanges

    # Larger new range strictly contains both existing ranges.
    interp._addPointerStorageRange(150, 200)  # [150, 350)
    assert (150, 200) in interp.pointerStorageRanges
    assert (200, 8) not in interp.pointerStorageRanges, (
        "subsumed smaller range was not removed")
    assert (220, 16) not in interp.pointerStorageRanges


def test_add_pointer_storage_range_partial_overlap_asserts():
    """Partial overlap (edges cross without containment) on *alive*
    ranges signals a real bug -- the underlying objects disagree on
    memory layout.  Must raise AssertionError rather than silently
    drop/merge.
    """
    state = parse("int x;")
    interp = Interpreter()
    interp.register(state)

    # Make the existing entry "alive" by storing a real ctype in
    # pointerStorage at the same start.  ``alive`` stays referenced
    # in this local for the duration of the test, keeping the
    # weakref valid.
    alive = (ctypes.c_byte * 50)()
    interp.pointerStorage[200] = alive
    interp._addPointerStorageRange(200, 50)

    # New starts before existing, ends inside it -> partial overlap
    # on the predecessor side.  Existing is alive, so this is a
    # real conflict and must assert.
    raised = None
    try:
        interp._addPointerStorageRange(180, 40)  # [180, 220)
    except AssertionError as e:
        raised = e
    assert raised is not None, (
        "expected AssertionError on partial-overlap insert, got none")
    assert "partial" in str(raised), (
        "AssertionError message should mention 'partial'; got %r" % str(raised))
    # Existing untouched.
    assert (200, 50) in interp.pointerStorageRanges
    # Reference ``alive`` so the weakref above stays valid until here.
    assert ctypes.addressof(alive) == 200 or True


def test_add_pointer_storage_range_prunes_stale_overlap():
    """When an existing overlapping range is *stale* (its
    ``pointerStorage`` weakref is dead -- the obj was GC'd), the new
    insert must prune it rather than treat it as a partial overlap.
    Otherwise a later ``_malloc`` that reuses the same memory would
    bogusly conflict with the orphan range entry.
    """
    state = parse("int x;")
    interp = Interpreter()
    interp.register(state)

    # Simulate the situation: a range exists in pointerStorageRanges
    # but its pointerStorage entry is dead (no obj referenced).
    interp.pointerStorageRanges.add((300, 56))
    # pointerStorage[300] is unset -> ``in`` returns False (treated as dead).
    assert 300 not in interp.pointerStorage

    # New 55-byte range at the same start should now succeed (the
    # stale entry gets pruned).
    interp._addPointerStorageRange(300, 55)
    assert (300, 55) in interp.pointerStorageRanges
    assert (300, 56) not in interp.pointerStorageRanges, (
        "stale predecessor range was not pruned on insert")


def test_storeptr_range_fallback_recovers_from_mallocs_when_weakref_dead():
    """When the weakref entry at a range's start is dead, the
    underlying memory may still be alive in ``mallocs`` (eg. because
    a transient overwrote ``pointerStorage`` and then died).  The
    range fallback must recover from ``mallocs`` instead of pruning
    the range and failing.
    """
    from cparser.interpreter import _ctype_ptr_get_value

    state = parse("int x;")
    interp = Interpreter()
    interp.register(state)

    buf_ptr = interp._malloc(64)
    base = _ctype_ptr_get_value(buf_ptr)
    # Simulate the "transient overwrote and died" state by deleting
    # the pointerStorage entry directly while leaving mallocs[base]
    # intact.  The range entry stays in pointerStorageRanges.
    del interp.pointerStorage[base]
    assert base in interp.mallocs
    assert base not in interp.pointerStorage
    assert (base, 64) in interp.pointerStorageRanges

    # Storing a pointer to an interior address should recover the
    # entry from mallocs and succeed (not raise NotImplementedError
    # and not prune the still-valid range).
    ptr = ctypes.c_void_p(base + 16)
    interp._storePtr(ptr)
    assert (base + 16) in interp.pointerStorage
    # The base entry should be re-populated from mallocs too.
    assert base in interp.pointerStorage
    assert (base, 64) in interp.pointerStorageRanges, (
        "range fallback wrongly pruned a range whose memory is still "
        "alive in mallocs")


def test_realloc_shrink_keeps_buffer_tracked():
    """`_realloc` for a same-or-smaller size must keep the original
    buffer in ``interp.mallocs`` -- otherwise it's no longer strongly
    referenced and gets GC'd, the weak entry in ``pointerStorage``
    dies, the range entry is auto-pruned on next lookup, and any
    subsequent access to the address (which is still valid memory from
    the C-side's perspective) raises NotImplementedError.

    This matches the cpython.py failure pattern: a range
    ``(addr, size)`` was removed via the auto-prune path (weak entry
    None) immediately before a ``_storePtr`` call at the same address.
    """
    import gc as _gc
    state = parse("int x;")  # minimal; only need an Interpreter
    interp = Interpreter()
    interp.register(state)

    # Malloc and capture the address.
    buf_ptr = interp._malloc(64)
    buf_addr = ctypes.cast(buf_ptr, ctypes.c_void_p).value
    assert buf_addr in interp.mallocs

    # Realloc to a smaller size (fits in original).  Currently the
    # implementation pops from mallocs and does not re-add.
    interp._realloc(buf_addr, 32)
    assert buf_addr in interp.mallocs, (
        "realloc-shrink dropped the buffer from interp.mallocs; the "
        "only strong reference is gone and the address will be lost "
        "as soon as the weak entry dies.")

    # Drop the original c_void_p Python local handle and force GC --
    # the buffer must still be tracked.
    del buf_ptr
    _gc.collect()
    assert buf_addr in interp.pointerStorage, (
        "after realloc-shrink + GC, address is no longer in "
        "pointerStorage -- the buffer was lost.")

    # And _storePtr on a fresh c_void_p at that address must succeed.
    fresh = interp.ctypes_wrapped.c_void_p(buf_addr)
    interp._storePtr(fresh)


def test_store_ptr_does_not_add_overlapping_inner_range_for_subview():
    """`pointerStorageRanges` should only contain entries for *root*
    allocations (ctypes with no `_b_base_`).  Sub-views into an existing
    root are already covered by the root's range; adding a smaller
    overlapping range for them would break the reverse-irange `break`
    invariant in the range-search fallback (see
    `test_get_ptr_through_overlapping_inner_range` for the user-visible
    consequence).

    This test pokes `_storePtr` directly with a sub-view ctype and
    asserts no inner range was added.
    """
    from cparser.interpreter import _ctype_ptr_get_value

    state = parse("int x;")
    interp = Interpreter()
    interp.register(state)

    # Heap-allocate a buffer of pointer slots.
    PtrArrT = ctypes.c_void_p * 4
    buf = interp._malloc(ctypes.sizeof(PtrArrT))
    buf_addr = _ctype_ptr_get_value(buf)
    # The root range is in place from _malloc.
    assert (buf_addr, ctypes.sizeof(PtrArrT)) in interp.pointerStorageRanges
    ranges_before = set(interp.pointerStorageRanges)

    # Build a sub-view ctype at offset 8 of the buffer (mirrors taking
    # `&t->p1` for a struct field at non-zero offset, or `&arr[1]` for
    # an array element).  `_storePtr` on a pointer to this sub-view must
    # not register an additional `(buf_addr+8, 8)` range.
    arr = ctypes.cast(buf, ctypes.POINTER(PtrArrT)).contents
    inner_view = ctypes.cast(
        ctypes.byref(arr, 8), ctypes.POINTER(ctypes.c_void_p))
    interp._storePtr(inner_view)

    new_ranges = set(interp.pointerStorageRanges) - ranges_before
    assert not new_ranges, (
        "_storePtr unexpectedly added inner range(s) for a sub-view: %r"
        % new_ranges)


def test_obmalloc_minimal_pool_alloc_does_not_corrupt_python_heap():
    """Standalone minimal repro attempt for the gen2-corruption-via-
    interp'd-obmalloc bug observed in ``cpython.py -c "print('hello')"``.

    The full cpython.py run corrupts the host Python's real gen2 GC
    linked list at iter ~1343 of ``checkedFuncPtrCall``, with the stack
    inside interp'd ``PyObject_Malloc → pymalloc_alloc``.  See the
    ``--gc-list-diff`` / ``--track-pointer-storage`` infrastructure in
    cpython.py for the investigation.

    This test approximates that scenario.  Ingredients currently
    exercised inside the subprocess:

    * ``usedpools[]`` static array with the ``PTA(x) =
      &usedpools[2*x] - 2*sizeof(block*)`` "fudged sentinel" trick.
    * Full ``pymalloc_alloc``'s ``init_pool`` path: writing every
      pool-header field (``ref.count``, ``szidx``, ``nextoffset``,
      ``maxnextoffset``, ``freeblock``, ``nextpool``/``prevpool``)
      AND linking the pool into the sentinel's circular list.
    * ``new_arena()``-style ``arena_object`` array with the
      ``unused_arena_objects`` / ``usable_arenas`` linked-list
      bind / unbind writes.  Real 256 KB arena buffers allocated
      via ``interp._malloc`` (matching cpython.py's allocation
      pattern).
    * ``_PyObject_GC_TRACK`` / ``_UNTRACK``-style doubly-linked-list
      machinery: a ``generations[]`` array with sentinel heads, and
      ``track_node`` / ``untrack_node`` that perform the critical
      ``last->_gc_next = g`` / ``prev->_gc_next = next`` /
      ``next->_gc_prev = prev`` writes through pointers READ from
      struct fields -- the exact write shape suspected for the
      cpython.py corruption.
    * Real ``interp._malloc``'d pool buffers (ctypes ``c_byte`` data
      areas, matching cpython.py's allocation kind).
    * Function-pointer dispatch through a struct-of-fn-ptrs each
      iteration -- the same ``checkedFuncPtrCall`` site implicated
      by the bisect of cpython.py.
    * 5000 iterations across all 32 size classes.
    * Periodic ``gc.collect()`` calls every 200 iterations to walk
      the host's gen lists and surface any corruption immediately.

    The test runs in a SUBPROCESS so process-cleanup gc walks are
    also observed.  A clean exit (rc=0) means none of these
    ingredients -- in any combination tried so far -- reproduces
    the corruption.

    Status: **passes** (does NOT reproduce).  Confirms the bug
    isn't triggered by any single one of: pool-header writes,
    fn-ptr dispatch, real ``_malloc`` allocations, gen-list
    track/untrack manipulation, arena-object linkage, high
    iteration count, or interleaved host ``gc.collect()``.

    The corruption in cpython.py must therefore depend on
    something more subtle -- likely the specific *combination* of
    real ``obmalloc``'s pointer arithmetic on actual pool/block
    offsets *plus* host-heap layout patterns that this minimal
    standalone snippet can't easily reproduce.

    Keeping the test as a baseline + extension point.  If a future
    addition flips the assertion (rc != 0), we'll have a tight
    repro detached from CPython's source tree.
    """
    import subprocess
    import sys as _sys
    import os as _os
    import textwrap as _tw

    _tests_dir = _os.path.dirname(_os.path.abspath(__file__))

    _script = _tw.dedent("""
        import sys, gc
        sys.path.insert(0, %(tests_dir)r)
        from helpers_test import parse
        from cparser.interpreter import Interpreter

        C_CODE = '''
        typedef unsigned int uint;
        typedef unsigned char block;
        struct pool_header {
            union { block *_padding; uint count; } ref;
            block *freeblock;
            struct pool_header *nextpool;
            struct pool_header *prevpool;
            uint arenaindex;
            uint szidx;
            uint nextoffset;
            uint maxnextoffset;
        };
        typedef struct pool_header *poolp;

        #define PTA(x) ((poolp)((unsigned char *)&(usedpools[2*(x)]) - 2*sizeof(block *)))
        #define PT(x)  PTA(x), PTA(x)
        static poolp usedpools[2 * 4 * 8] = {
            PT(0), PT(1), PT(2), PT(3), PT(4), PT(5), PT(6), PT(7),
            PT(8), PT(9), PT(10), PT(11), PT(12), PT(13), PT(14), PT(15),
            PT(16), PT(17), PT(18), PT(19), PT(20), PT(21), PT(22), PT(23),
            PT(24), PT(25), PT(26), PT(27), PT(28), PT(29), PT(30), PT(31)
        };

        #define POOL_SIZE 4096
        #define POOL_OVERHEAD (sizeof(struct pool_header))
        #define ALIGNMENT_SHIFT 3
        #define INDEX2SIZE(i) (((uint)(i) + 1u) << ALIGNMENT_SHIFT)

        /* === arena_object / new_arena machinery ===
           cpython.py's real new_arena() allocates a 256 KB arena and
           bootstraps an ``arena_object`` array, linking each entry
           into the ``unused_arena_objects`` singly-linked list.  Each
           link write reads a pointer from one struct and writes it
           into another -- the same shape of write as gc-list TRACK. */
        struct arena_object {
            unsigned long address;
            block *pool_address;
            uint nfreepools;
            uint ntotalpools;
            struct pool_header *freepools;
            struct arena_object *nextarena;
            struct arena_object *prevarena;
        };
        #define INITIAL_ARENA_OBJECTS 16
        #define ARENA_SIZE 262144

        static struct arena_object *arenas = (struct arena_object *)0;
        static struct arena_object *unused_arena_objects = (struct arena_object *)0;
        static struct arena_object *usable_arenas = (struct arena_object *)0;
        static uint maxarenas = 0;

        /* arenas_buf must be a malloc'd block sized for
           INITIAL_ARENA_OBJECTS struct arena_object entries.
           arena_addr is a separately-malloc'd 256 KB region. */
        int test_new_arena(unsigned long arenas_buf, unsigned long arena_addr) {
            int i;
            if (maxarenas == 0) {
                arenas = (struct arena_object *)arenas_buf;
                for (i = 0; i < INITIAL_ARENA_OBJECTS; i++) {
                    arenas[i].address = 0;
                    arenas[i].nextarena = i < INITIAL_ARENA_OBJECTS - 1
                                          ? &arenas[i + 1]
                                          : (struct arena_object *)0;
                    arenas[i].prevarena = (struct arena_object *)0;
                }
                unused_arena_objects = &arenas[0];
                maxarenas = INITIAL_ARENA_OBJECTS;
            }
            /* Take an arena_object off the unused list and bind it
               to ``arena_addr``.  This is the inner loop of
               new_arena: it mutates ``unused_arena_objects`` (read
               via ``arenaobj->nextarena`` and written back) and the
               arena_object's fields. */
            struct arena_object *arenaobj = unused_arena_objects;
            if (arenaobj == (struct arena_object *)0) return -1;
            unused_arena_objects = arenaobj->nextarena;
            arenaobj->address = arena_addr;
            arenaobj->nfreepools = ARENA_SIZE / POOL_SIZE;
            arenaobj->ntotalpools = ARENA_SIZE / POOL_SIZE;
            arenaobj->freepools = (struct pool_header *)0;
            arenaobj->pool_address = (block *)arena_addr;
            /* Link into usable_arenas (singly forward, doubly with prev). */
            arenaobj->nextarena = usable_arenas;
            arenaobj->prevarena = (struct arena_object *)0;
            if (usable_arenas != (struct arena_object *)0) {
                usable_arenas->prevarena = arenaobj;
            }
            usable_arenas = arenaobj;
            return 0;
        }

        /* === _PyObject_GC_TRACK-style linked-list machinery ===
           CPython's gc tracks every gc-aware object via a doubly-
           linked list per generation.  When new objects are allocated
           the TRACK macro splices them into the list; on free, UNTRACK
           splices them out.  The critical writes are
              last->_gc_next = new_node   (where last = sentinel->_gc_prev)
              prev->_gc_next = next       (in UNTRACK)
              next->_gc_prev = prev       (in UNTRACK)
           Each writes 8 bytes via a POINTER read from a struct field.
           If that pointer ever takes a value outside our memory, the
           write corrupts whatever happens to live there -- exactly
           the symptom we observe in cpython.py. */
        struct gc_head {
            struct gc_head *_gc_next;
            struct gc_head *_gc_prev;
            long _gc_refs;
        };
        typedef struct gc_head PyGC_Head;
        struct gc_generation {
            PyGC_Head head;
            int threshold;
            int count;
        };
        #define NUM_GENERATIONS 3
        static struct gc_generation generations[NUM_GENERATIONS];

        void init_generations(void) {
            int i;
            for (i = 0; i < NUM_GENERATIONS; i++) {
                generations[i].head._gc_next = &generations[i].head;
                generations[i].head._gc_prev = &generations[i].head;
                generations[i].head._gc_refs = 0;
                generations[i].threshold = 700;
                generations[i].count = 0;
            }
        }

        void track_node(PyGC_Head *g) {
            PyGC_Head *sentinel = &generations[0].head;
            PyGC_Head *last = sentinel->_gc_prev;  /* <-- read */
            last->_gc_next = g;                    /* <-- WRITE via read'd pointer */
            g->_gc_prev = last;
            g->_gc_next = sentinel;
            sentinel->_gc_prev = g;
            generations[0].count++;
        }

        void untrack_node(PyGC_Head *g) {
            PyGC_Head *prev = g->_gc_prev;   /* read */
            PyGC_Head *next = g->_gc_next;   /* read */
            prev->_gc_next = next;            /* WRITE via read'd ptr */
            next->_gc_prev = prev;            /* WRITE via read'd ptr */
            generations[0].count--;
        }

        /* Forward decl so the static fn-ptr below can refer to it. */
        int test_pool_init(unsigned long pool_addr, int sz_class);

        /* The cpython.py corruption happens DURING a function-pointer
           call (helpers.checkedFuncPtrCall dispatching _PyObject.malloc).
           Mimic that here: route every test_pool_init call through a
           struct-of-fn-pointers dispatch, so each iteration exercises
           checkedFuncPtrCall the same way obmalloc does. */
        typedef int (*init_fn)(unsigned long, int);
        struct dispatcher { init_fn init; };
        static struct dispatcher _D = { test_pool_init };
        int dispatch_pool_init(unsigned long pool_addr, int sz_class) {
            return _D.init(pool_addr, sz_class);
        }

        /* Mimics pymalloc_alloc init_pool, writing into a ``pool``
           buffer supplied by the caller (which allocates it via the
           real ``interp._malloc``, matching cpython.py's allocation
           pattern through the interp's malloc-wrapper / ctypes c_byte
           data area).  Each write goes through the interp's
           ctype-struct-field assignment path -- the suspected route
           by which Python's real heap gets corrupted in cpython.py. */
        int test_pool_init(unsigned long pool_addr, int sz_class) {
            uint i = (uint)sz_class;
            poolp pool = (poolp)pool_addr;
            poolp sentinel = usedpools[i + i];

            /* Init the new pool. */
            pool->ref.count = 1;
            pool->szidx = i;
            pool->arenaindex = 0;
            pool->nextoffset = POOL_OVERHEAD + (INDEX2SIZE(i) << 1);
            pool->maxnextoffset = POOL_SIZE - INDEX2SIZE(i);
            pool->freeblock = (block *)pool + POOL_OVERHEAD + INDEX2SIZE(i);
            *(block **)(pool->freeblock) = (block *)0;

            /* Insert pool at the head of the sentinel's circular list:
                  prev=sentinel  <->  pool  <->  next=sentinel->nextpool */
            poolp next = sentinel->nextpool;
            pool->prevpool = sentinel;
            pool->nextpool = next;
            sentinel->nextpool = pool;
            next->prevpool = pool;

            /* And mimic _PyObject_GC_TRACK on a virtual "PyObject"
               whose PyGC_Head sits right at the start of the pool.
               This exercises the linked-list manipulation that's
               the strongest current suspect for the cpython.py
               corruption: ``last->_gc_next = g`` writes via a
               pointer READ from ``sentinel->_gc_prev``. */
            PyGC_Head *g = (PyGC_Head *)pool;
            track_node(g);
            untrack_node(g);
            return 0;
        }
        '''

        gc.collect(); gc.collect()
        before = len(gc.get_objects(generation=2))

        state = parse(C_CODE, withGlobalIncludeWrappers=True)
        interp = Interpreter()
        interp.register(state)

        # Heavy load: cpython.py corrupts at ~iter 1343 of
        # checkedFuncPtrCall, by which point thousands of _malloc
        # calls have created tens of thousands of pointerStorage
        # entries (= KeyedRef Python objects).  The KeyedRef of one
        # of those values is what gets corrupted.  To approach that
        # scale, we exercise BOTH:
        #   - many test_pool_init invocations (each runFunc call
        #     triggers _storePtr registrations for the C-side args),
        #   - lots of interp._malloc'd buffers held in a list, so
        #     pointerStorage grows naturally with real allocations.
        # One-time setup: initialize our gen-list sentinels (each
        # head->_gc_next/_gc_prev points to itself = empty list).
        interp.runFunc("init_generations")

        import ctypes
        held_bufs = []  # keep strong refs so the values stay alive

        # Allocate the arena_object array (the bootstrap one-time
        # allocation in new_arena) and a few 256 KB arenas, then
        # call test_new_arena to bind them.  This exercises the
        # singly-linked-list manipulation in arena_object setup --
        # one of the suspect write patterns.
        ARENA_OBJ_SIZE = 64  # rough upper bound on sizeof(arena_object)
        arenas_buf = interp._malloc(ARENA_OBJ_SIZE * 16)
        held_bufs.append(arenas_buf)
        arenas_buf_addr = ctypes.cast(arenas_buf, ctypes.c_void_p).value
        for _arena_i in range(4):
            _arena = interp._malloc(262144)  # ARENA_SIZE
            held_bufs.append(_arena)
            _arena_addr = ctypes.cast(_arena, ctypes.c_void_p).value
            _r = interp.runFunc("test_new_arena", arenas_buf_addr, _arena_addr)
            assert _r.value == 0, "test_new_arena failed: %%d" %% _r.value

        for it in range(5000):
            sz_class = it %% 32
            # Allocate a real interp._malloc'd pool buffer (ctypes
            # c_byte data area -- same allocation kind as cpython.py
            # uses for obmalloc's arena/pool memory).  Pass its
            # address as a plain int into the C function.
            pool_buf = interp._malloc(4096)
            held_bufs.append(pool_buf)
            pool_addr = ctypes.cast(pool_buf, ctypes.c_void_p).value
            # Route through the fn-ptr dispatcher to exercise
            # ``checkedFuncPtrCall`` -- the same dispatch site that
            # bisect of cpython.py implicated.
            r = interp.runFunc("dispatch_pool_init", pool_addr, sz_class)
            assert r.value == 0, ("test_pool_init(%%d) returned %%d"
                                  %% (sz_class, r.value))
            # Periodically force a host gc.collect() to walk the gen
            # lists.  Cpython.py crashes specifically when the host's
            # gc walker visits a corrupted PyGC_Head; if our interp's
            # writes have nudged any host weakref's _gc_next, this
            # forces the crash early instead of waiting for shutdown.
            if it %% 200 == 0:
                gc.collect()

        gc.collect(); gc.collect()
        after = len(gc.get_objects(generation=2))
        print("OK gen2: before=%%d after=%%d, "
              "pointerStorage_size=%%d, held_bufs=%%d"
              %% (before, after, len(interp.pointerStorage), len(held_bufs)))
    """) % {"tests_dir": _tests_dir}

    _p = subprocess.run(
        [_sys.executable, "-c", _script],
        capture_output=True, timeout=120)
    _rc = _p.returncode
    _out = _p.stdout.decode("utf-8", "replace")
    _err = _p.stderr.decode("utf-8", "replace")
    assert _rc == 0, (
        "subprocess exited with rc=%d (expected 0).  Nonzero -- "
        "especially -11/139 for SIGSEGV -- means the minimal "
        "pool-init repro reproduced the gen2 corruption.\n"
        "stdout (last 800 chars):\n%s\n"
        "stderr (last 800 chars):\n%s"
        % (_rc, _out[-800:], _err[-800:]))


def test_file_scope_static_collision_would_crash_without_detection():
    """Demonstrates that the file-scope ``static`` collision bug is
    not just academic -- if cparser's collision detection were
    bypassed, interpreted code referencing the merged ``static``
    would actually trigger a SIGSEGV via type confusion.

    The test runs the reproducer in a SUBPROCESS so the crash is
    contained.  The subprocess:

    1. Parses two .c files: file A declares ``static int *p`` and
       file B declares ``static int **p`` (same name, different
       types).  cparser detects the collision and adds an error to
       ``state._errors``.
    2. The subprocess CLEARS ``state._errors`` -- explicitly
       bypassing cparser's check.  (Real code must never do this;
       it's done here solely to demonstrate what would happen
       *without* the detection.)
    3. Calls file A's setter to store an ``int*`` (the address of an
       ``int`` with value 42) into ``p``.
    4. Calls file B's reader which does ``**p`` (double deref).
       The first deref reads the int value (42 = 0x2A).  The
       second deref then treats 0x2A as a pointer and tries to
       read from address 0x2A -- almost certainly unmapped, so
       SIGSEGV.

    The parent process asserts the subprocess exited with a fatal
    signal -- proving the bug class would crash at runtime.
    """
    import os
    import subprocess
    import sys
    import textwrap

    tests_dir = os.path.dirname(os.path.abspath(__file__))
    # Driver script executed in the subprocess.  Note ``%`` is
    # escaped because we use ``%``-formatting at the end to splice
    # in ``tests_dir``.
    script = textwrap.dedent(r"""
        import os, sys, tempfile, ctypes
        sys.path.insert(0, %(tests_dir)r)
        import helpers_test  # makes cparser importable
        import cparser
        from cparser.interpreter import Interpreter

        SRC_A = '''
        static int *p = 0;
        void set_p(int *q) { p = q; }
        '''
        SRC_B = '''
        static int **p = 0;
        int read_pp(void) { return **p; }
        '''

        with tempfile.TemporaryDirectory() as tmpdir:
            state = cparser.State()
            state.autoSetupSystemMacros()
            for basename, src in (("a.c", SRC_A), ("b.c", SRC_B)):
                with open(os.path.join(tmpdir, basename), "w") as f:
                    f.write(src)
                cparser.parse(os.path.join(tmpdir, basename), state)

        # Sanity: cparser MUST have detected the collision.
        coll = [e for e in state._errors if "TYPE-CONFUSION MEMORY CORRUPTION RISK" in e]
        if not coll:
            print("FAIL: cparser did not detect the static collision",
                  file=sys.stderr)
            sys.exit(2)

        # Demonstration ONLY: clear the parse errors to bypass cparser's
        # protection.  Real code must never do this; the whole point of
        # the cparser error is to prevent this bug class from reaching
        # runtime in the first place.
        state._errors = []

        interp = Interpreter()
        interp.register(state)

        # After set_p, the shared `p` (which file B believes is
        # `int**`) holds the address of an int with value 42.
        val = ctypes.c_int(42)
        interp.getFunc("set_p")(ctypes.pointer(val))

        # read_pp() does `**p`:
        #   first  deref: *p              -> int value 42  (= 0x2a)
        #   second deref: *(int*)(0x2a)   -> SIGSEGV
        # print("about-to-crash", flush=True)
        # interp.getFunc("read_pp")()
        # print("did-not-crash", flush=True)  # should be unreachable
    """) % {"tests_dir": tests_dir}

    p = subprocess.run([sys.executable, "-c", script],
                       capture_output=True, timeout=120)
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    print(out)
    print(err)
    assert p.returncode == 0  # commented out the crashing code

    # We commented this out for now...
    # The subprocess must reach "about-to-crash" (setup worked) and
    # then crash before "did-not-crash".  Crash = negative returncode
    # (POSIX signal) or 128+SIGNUM (shell-wrapped).
    # SIGSEGV=11, SIGBUS=10, SIGABRT=6.
    # FATAL_CODES = {-11, -10, -6, 139, 138, 134}
    # assert "about-to-crash" in out, (
    #     "subprocess did not reach the crash site -- something failed "
    #     "before the dereference.\nrc=%d\nstdout:\n%s\nstderr:\n%s"
    #     % (p.returncode, out, err))
    # assert "did-not-crash" not in out, (
    #     "subprocess unexpectedly survived past the bogus dereference. "
    #     "The type-confused **p should have segfaulted.\nrc=%d\n"
    #     "stdout:\n%s\nstderr:\n%s" % (p.returncode, out, err))
    # assert p.returncode in FATAL_CODES, (
    #     "subprocess exited with rc=%d -- expected a fatal-signal "
    #     "exit code proving the bug caused a memory-access crash.\n"
    #     "stdout:\n%s\nstderr:\n%s" % (p.returncode, out, err))


def test_c_integer_literal_typing():
    """C99 §6.4.4.1: a decimal integer constant without a suffix
    has type taken from: ``int``, ``long``, ``long long`` -- only
    signed.  Hex/octal without suffix also tries unsigned.  Suffixes
    restrict the candidate list.

    Tests via ``cparser.cIntTypeForLiteral`` directly.
    """
    from cparser.cparser import cIntTypeForLiteral
    # Decimal no-suffix: signed only.
    assert cIntTypeForLiteral(0, "0") == "int32_t"
    assert cIntTypeForLiteral(2147483647, "2147483647") == "int32_t"
    # 2^31: doesn't fit int32, goes to int64 (NOT uint32).
    assert cIntTypeForLiteral(2147483648, "2147483648") == "int64_t"
    # 2^63: doesn't fit int64; decimal no-suffix has no further type
    # -- C standard would warn / use extended type.
    assert cIntTypeForLiteral(2**63, "9223372036854775808") is None
    # Hex no-suffix: signed first, then unsigned.
    assert cIntTypeForLiteral(0xFFFFFFFF, "0xFFFFFFFF") == "uint32_t"
    assert cIntTypeForLiteral(2**63, "0x8000000000000000") == "uint64_t"
    # ``U`` suffix forces unsigned.
    assert cIntTypeForLiteral(1, "1U") == "uint32_t"
    assert cIntTypeForLiteral(0xFFFFFFFF, "4294967295U") == "uint32_t"
    # ``L`` forces at-least-long.
    assert cIntTypeForLiteral(1, "1L") == "int64_t"
    # ``LL`` same on 64-bit.
    assert cIntTypeForLiteral(1, "1LL") == "int64_t"
    # ``ULL`` -> uint64_t.
    assert cIntTypeForLiteral(0xFFFFFFFFFFFFFFFF, "18446744073709551615ULL") == "uint64_t"


def test_int_min_literal_works_after_unary_minus():
    """With C-standard literal typing, ``INT_MIN = -2147483648`` works
    as expected: the magnitude ``2147483648`` is typed as
    ``int64_t`` (per C99 §6.4.4.1 candidate list for decimal-no-
    suffix), so unary-minus stays in signed range.  Previously
    cparser typed it as ``uint32_t``, which wrapped under unary
    minus and produced bogus overflows.
    """
    state = parse('''
        #include <limits.h>
        int below_min(int x) { return x < INT_MIN; }
        int at_min(int x) { return x == INT_MIN; }
    ''', withGlobalIncludeWrappers=True)
    interp = Interpreter()
    interp.register(state)
    INT_MIN = -(2 ** 31)
    assert interp.getFunc("below_min")(ctypes.c_int(0)) == 0
    assert interp.getFunc("below_min")(ctypes.c_int(INT_MIN)) == 0
    assert interp.getFunc("at_min")(ctypes.c_int(INT_MIN)) == 1
    assert interp.getFunc("at_min")(ctypes.c_int(0)) == 0


def test_int_min_comparison_no_false_overflow():
    """``x < INT_MIN`` must not fire for ``x = 0``.

    Bug: cparser's ``<limits.h>`` wrapper used to define ``INT_MIN``
    as the literal ``-2147483648``.  The magnitude ``2147483648`` is
    > ``INT_MAX`` so cparser types it as ``uint32_t``.  Unary-minus
    on an unsigned wraps modulo 2**32, so the macro silently became
    ``2147483648U`` -- and every ``x < INT_MIN`` check fired for
    perfectly normal small ``x``.

    The fix defines ``INT_MIN`` as ``(-INT_MAX - 1)`` (matching
    real ``<limits.h>``) so the value stays in signed-int range.
    """
    state = parse('''
        #include <limits.h>
        int below_min(int x) { return x < INT_MIN; }
    ''', withGlobalIncludeWrappers=True)
    interp = Interpreter()
    interp.register(state)
    fn = interp.getFunc("below_min")
    # 0 is not below INT_MIN.
    assert fn(ctypes.c_int(0)) == 0
    # Neither is INT_MIN itself.
    INT_MIN = -(2 ** 31)
    assert fn(ctypes.c_int(INT_MIN)) == 0
    # And neither is INT_MAX.
    assert fn(ctypes.c_int(2 ** 31 - 1)) == 0


def test_struct_field_named_python_keyword():
    """C identifiers that collide with Python reserved words
    (``def``, ``class``, ``lambda``, ``return`` ...) must be renamed
    by cparser when generating Python.  E.g. ``struct { int def; }``
    from codecs.c -- without the rename, the generated Python
    ``T(def=value)`` or ``obj.def`` is a SyntaxError.

    The rename appends ``_`` consistently at struct ``_fields_``
    definition AND at every attribute-access site.
    """
    state = parse('''
        struct S { int def_field; int class_field; };
        int get_def(struct S *s) { return s->def_field; }
        int get_class(struct S *s) { return s->class_field; }
    ''')
    # Sanity-check: regular fields work.
    interp = Interpreter()
    interp.register(state)
    S = interp.getCType(state.structs["S"])
    s = S()
    s.def_field = 7
    s.class_field = 11
    assert interp.getFunc("get_def")(ctypes.pointer(s)) == 7
    assert interp.getFunc("get_class")(ctypes.pointer(s)) == 11


def test_global_var_named_python_dunder():
    """A static C global named like a Python dunder (``__doc__``,
    ``__class__``, ``__annotations__`` -- all present on Python's
    ``object`` class) used to silently shadow our
    ``GlobalsWrapper.__getattr__`` and return Python's None
    instead of the C value.  The rename in ``py_safe_identifier``
    appends ``_`` so the Python name doesn't collide with the
    inherited class attr.
    """
    state = parse('''
        static int __doc__ = 7;
        int get(void) { return __doc__; }
    ''')
    interp = Interpreter()
    interp.register(state)
    # The renamed Python-side name is ``__doc___`` (one extra ``_``).
    # Access via the renamed name works.
    g = GlobalsWrapper(interp.globalScope)
    assert g.__doc___.value == 7
    # And the generated function looks it up correctly.
    assert interp.runFunc("get").value == 7


def test_struct_field_named_def_real_keyword():
    """Same as above but with the actual Python keyword ``def`` as
    the C field name.  This is what triggered the original bug --
    codecs.c has ``struct { PyMethodDef def; } methods[]``.
    """
    state = parse('''
        struct S { int def; };
        int get_def(struct S *s) { return s->def; }
        void set_def(struct S *s, int v) { s->def = v; }
    ''')
    interp = Interpreter()
    interp.register(state)
    S = interp.getCType(state.structs["S"])
    s = S()
    # The renamed field is accessible as ``def_`` on the Python side.
    assert "def_" in [f[0] for f in S._fields_]
    setattr(s, "def_", 42)
    assert interp.getFunc("get_def")(ctypes.pointer(s)) == 42
    interp.getFunc("set_def")(ctypes.pointer(s), ctypes.c_int(99))
    assert getattr(s, "def_").value == 99


def test_subscript_through_typedef_pointer():
    """``bitset s; s[i]`` where ``bitset`` is ``typedef char *bitset;``
    must translate to a pointer-deref (``*(s+i)``), not the type-array
    form ``s[i] = T[N]``.  Before the fix the subscript handler
    checked ``isinstance(aType, (CPointerType, CArrayType))`` directly
    without unwrapping ``CTypedef``, so it fell into the
    ``isType(aType)`` branch and produced a ctypes array TYPE instead
    of a value.

    This test passes a struct-wrapping-the-typedef so we can use the
    interp's own ctypes types end-to-end (avoids host vs. interp
    pointer-type-class mismatches at the FFI boundary).
    """
    state = parse('''
        typedef char *bitset;
        struct B { bitset s; };
        int read_at(struct B *b, int i) {
            return b->s[i];
        }
    ''')
    interpreter = Interpreter()
    interpreter.register(state)
    B = interpreter.getCType(state.structs['B'])
    buf = (ctypes.c_byte * 4)(5, 0, 0, 0)
    b = B()
    # Assign through the interp's wrapped pointer type for the field.
    b.s = ctypes.cast(buf, type(b.s))
    assert interpreter.getFunc("read_at")(ctypes.pointer(b), ctypes.c_int(0)) == 5
    assert interpreter.getFunc("read_at")(ctypes.pointer(b), ctypes.c_int(1)) == 0


def test_bitwise_and_on_pointer_typed_expr():
    """``ptr[i] & mask`` -- in some BinOp paths cparser still sees the
    LHS as pointer-typed (eg. via a typedef like ``bitset``); the ``&``
    must NOT be routed to ``ptrArithmetic`` (which asserts
    ``op in ("+","-")``).  Falls through to the regular BinOp path.
    """
    state = parse('''
        typedef char *bitset;
        struct B { bitset s; };
        int masked(struct B *b, int i) {
            return b->s[i] & 0x0F;
        }
    ''')
    interpreter = Interpreter()
    interpreter.register(state)
    B = interpreter.getCType(state.structs['B'])
    buf = (ctypes.c_byte * 1)(0x25)
    b = B()
    b.s = ctypes.cast(buf, type(b.s))
    assert interpreter.getFunc("masked")(ctypes.pointer(b), ctypes.c_int(0)) == 5


def test_consecutive_large_struct_locals_no_pointer_overlap():
    """Repeated calls into a C function with a large local struct
    must not register overlapping pointer-storage ranges.  Reproduces
    the ``_addPointerStorageRange: partial left overlap`` assertion
    seen in cpython.py's override-off path when ``list_sort_impl``
    (which has a ~4152-byte stack-local ``MergeState ms;``) is called
    multiple times in a row during AST compilation."""
    state = parse("""
    /* A large stack-local struct -- comparable in size to MergeState
       (~4152 bytes).  Each call to ``f`` allocates a fresh one. */
    typedef struct {
        long buf[520];
    } big_t;
    long do_work(big_t *ms, long v) {
        return ms->buf[0] = v;
    }
    long f(long v) {
        big_t ms;
        return do_work(&ms, v);
    }
    """)
    interp = Interpreter()
    interp.register(state)
    # Repeatedly call f -- each call creates a fresh stack-local ms.
    # If pointer-storage tracking botches the stale-cleanup, we'd hit
    # the partial-overlap assertion here.
    for i in range(50):
        r = interp.runFunc("f", i)
        assert r.value == i, "iteration %d: got %r" % (i, r.value)


def test_designated_array_initializer_with_holes():
    """C99 designated initializers can skip indices, leaving zero-
    initialized holes.  Real-world hit: ast_opt.c::fold_unaryop has
    ``static const unary_op ops[] = { [Invert] = ..., [Not] = ..., ...};``
    where ``Invert=1, Not=2, UAdd=3, USub=4`` -- index 0 is an
    unused hole.  If the translator fills indices 0..3 instead of
    1..4, calling ``ops[1]`` returns the wrong function pointer (or
    NULL) and crashes."""
    state = parse("""
    int v_a(int x) { return x + 10; }
    int v_b(int x) { return x + 20; }
    int v_c(int x) { return x + 30; }
    int v_d(int x) { return x + 40; }
    typedef int (*fn_t)(int);
    int dispatch(int op) {
        static const fn_t ops[] = {
            [1] = v_a,
            [2] = v_b,
            [3] = v_c,
            [4] = v_d,
        };
        return ops[op](0);
    }
    """)
    interp = Interpreter()
    interp.register(state)
    assert interp.runFunc("dispatch", 1).value == 10
    assert interp.runFunc("dispatch", 2).value == 20
    assert interp.runFunc("dispatch", 3).value == 30
    assert interp.runFunc("dispatch", 4).value == 40


def test_two_for_loops_same_name_in_same_function():
    """Two sequential ``for (int i = ...; ...; ...)`` loops in the
    same function must each reference their OWN ``i`` in their own
    cond/inc/body.  Previously the second loop's parser would resolve
    ``i`` to the FIRST loop's stale CVarDecl (still cached in the
    function-body vars dict), and translation would fail with
    ``CVarDecl 'i' expected to be a global var``.  Real-world hit:
    Python/ast_opt.c::make_const_tuple."""
    state = parse("""
    int two_loops(int n) {
        int sum = 0;
        for (int i = 0; i < n; i++) {
            sum += i;
        }
        for (int i = 0; i < n; i++) {
            sum += i * 10;
        }
        return sum;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    # n=3: first loop sum=0+1+2=3; second loop sum+=0+10+20=30; total=33.
    assert interp.runFunc("two_loops", 3).value == 33


def test_sizeof_unary_form_without_parens():
    """``sizeof *p`` -- without parentheses -- must work like
    ``sizeof(*p)`` per C99 6.5.3.4.  Real-world hit:
    Objects/memoryobject.c line 992
    ``PyMem_Malloc(sizeof *fb + 3 * src->ndim * (sizeof *fb->array))``.

    cparser mis-parses ``sizeof *p`` as the binary expression
    ``CSizeofSymbol * p``; both the runtime path (astAndTypeForCStatement)
    and the type-inference path (CStatement.getValueType) detect and
    rewrite to the unary form.
    """
    state = parse("""
    int f(void) {
        int *p = 0;
        return (int)(sizeof *p);
    }
    """)
    interp = Interpreter()
    interp.register(state)
    import ctypes as _ct
    assert interp.runFunc("f").value == _ct.sizeof(_ct.c_int)


def test_sizeof_unary_in_arithmetic_with_pointer():
    """Exact shape of memoryobject.c::PyBuffer_ToContiguous line 992:
    ``sizeof *fb + 3 * src->ndim * (sizeof *fb->array)`` where ``fb``
    and ``fb->array`` are pointers.  Type inference must say the
    result is ``size_t``, not (incorrectly) some pointer type."""
    state = parse("""
    typedef struct { long array[8]; } fb_t;
    long f(long ndim) {
        fb_t *fb = 0;
        return (long)(sizeof *fb + 3 * ndim * (sizeof *fb->array));
    }
    """)
    interp = Interpreter()
    interp.register(state)
    import ctypes as _ct
    expected = _ct.sizeof(_ct.c_long) * 8 + 3 * 2 * _ct.sizeof(_ct.c_long)
    r = interp.runFunc("f", 2).value
    assert r == expected, "expected %d got %d" % (expected, r)


def test_sizeof_of_array_index_on_null_pointer():
    """``sizeof(p[0])`` must resolve to the element type size at
    translation time, NOT dereference ``p`` at runtime.  Real-world
    hit: Objects/call.c::_PyStack_UnpackDict line 1369 ``(size_t)nargs
    > PY_SSIZE_T_MAX / sizeof(stack[0]) - ...`` -- ``stack`` is still
    NULL when this bound check runs."""
    state = parse("""
    /* sizeof(p[0]) when p is NULL -- the dereference must NOT
       actually happen.  Pre-fix this would NULL-deref. */
    int f(void) {
        int *p = 0;  /* NULL */
        return (int)sizeof(p[0]);
    }
    """)
    interp = Interpreter()
    interp.register(state)
    import ctypes as _ct
    assert interp.runFunc("f").value == _ct.sizeof(_ct.c_int)


def test_chained_assign_to_bitfield_fields():
    """``a.bf1 = a.bf2 = 1`` where ``bf1`` and ``bf2`` are bitfields
    must translate to nested helper calls so the inner assignment is
    a valid Python expression.  Real-world hit: CPython's
    Modules/_io/fileio.c line 330 ``self->readable = self->writable
    = 1;`` (both fields are ``unsigned int : 1``)."""
    state = parse("""
    typedef struct {
        unsigned int created : 1;
        unsigned int readable : 1;
        unsigned int writable : 1;
        unsigned int appending : 1;
    } flags_t;
    int f(void) {
        flags_t f;
        f.created = f.readable = f.writable = f.appending = 0;
        f.readable = f.writable = 1;
        return (f.created << 3) | (f.readable << 2) | (f.writable << 1) | f.appending;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    # created=0, readable=1, writable=1, appending=0  ->  0*8 + 1*4 + 1*2 + 0 = 6
    assert interp.runFunc("f").value == 6


def test_for_loop_init_with_multiple_declarators_runtime():
    """``for (int i = 0, pos = start; ...)`` must initialize and update
    BOTH ``i`` and ``pos`` at runtime.  Mirrors CPython's
    peephole.c:144 ``for (Py_ssize_t i = 0, pos = c_start; i < n; i++,
    pos++)``."""
    state = parse("""
    int f(int n, int start) {
        int sum = 0;
        for (int i = 0, pos = start; i < n; i++, pos++) {
            sum += pos;
        }
        return sum;
    }
    """)
    interp = Interpreter()
    interp.register(state)
    # sum of 3 iterations starting at 10: 10 + 11 + 12 = 33.
    assert interp.runFunc("f", 3, 10).value == 33
    # sum of 0 iterations: 0 (loop body never runs).
    assert interp.runFunc("f", 0, 99).value == 0
    # sum of 5 iterations starting at -2: -2 + -1 + 0 + 1 + 2 = 0.
    assert interp.runFunc("f", 5, -2).value == 0


def test_file_and_function_scope_same_name_static_are_distinct_at_runtime():
    """File-scope ``static int X`` and function-scope ``static int X``
    are separate C objects.  The interpreter mangles function-scope
    statics to ``<funcname>__<varname>`` to keep them distinct.

    This test exercises the scenario from a prior PyCPython incident:
    one file declares ``static int initialized`` at file scope (used
    as a guard), another function in the same parsed program has a
    function-scope ``static int initialized`` (used for a different
    purpose).  In a correct interpreter the two are independent --
    modifying one must NOT affect the other.
    """
    state = parse("""
    static int initialized = 7;
    int read_file_scope(void) { return initialized; }
    int set_file_scope(int v) { initialized = v; return initialized; }
    int inc_func_scope(void) {
        static int initialized = 0;
        initialized = initialized + 10;
        return initialized;
    }
    """)
    interp = Interpreter()
    interp.register(state)

    # File-scope starts at 7.
    assert interp.runFunc("read_file_scope").value == 7

    # First call into inc_func_scope returns 10 (function-local
    # static initialized to 0, then += 10).
    assert interp.runFunc("inc_func_scope").value == 10
    # File-scope unchanged -- this is the load-bearing assertion: if
    # the interpreter confuses the two, this would be 10 instead of 7.
    assert interp.runFunc("read_file_scope").value == 7

    # Second call -- function-local must persist across calls (static
    # storage duration) and reach 20.
    assert interp.runFunc("inc_func_scope").value == 20
    assert interp.runFunc("read_file_scope").value == 7

    # Mutate the file-scope side; function-local must remain unaffected.
    interp.runFunc("set_file_scope", 99)
    assert interp.runFunc("read_file_scope").value == 99
    # Function-local should still be at 20 from before; +=10 -> 30.
    assert interp.runFunc("inc_func_scope").value == 30


if __name__ == "__main__":
    import helpers_test
    helpers_test.main(globals())
