
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


if __name__ == "__main__":
    import helpers_test
    helpers_test.main(globals())
