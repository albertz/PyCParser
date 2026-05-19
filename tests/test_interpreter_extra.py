
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
    # The casting is necessary to avoid "incompatible types" TypeError
    # when the same function is used with different signatures.
    testcode = """
        typedef int (*func1_t)(int);
        typedef int (*func2_t)(int, int);
        
        int my_func(int x) { return x + 10; }
        
        struct S1 { func1_t f; };
        struct S2 { func2_t f; };
        
        int test() {
            struct S1 s1;
            struct S2 s2;
            
            // 1. First use as func1_t
            s1.f = my_func;
            
            // 2. Second use as func2_t (with cast)
            // This would fail without the casting logic in makeFuncPtr
            // because my_func already has a func1_t instance attached.
            s2.f = (func2_t)my_func;
            
            return s1.f(5);
        }
    """
    state = parse(testcode)
    interpreter = Interpreter()
    interpreter.register(state)
    
    r = interpreter.runFunc("test")
    assert r.value == 15


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


if __name__ == "__main__":
    import helpers_test
    helpers_test.main(globals())
