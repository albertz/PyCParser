
from helpers_test import parse
from cparser.interpreter import Interpreter, GlobalsWrapper, getAstNodeForVarType, FuncEnv
from cparser.cparser import State, CArrayType, CBuiltinType, CStatement, CIdentifier, CVarDecl, CPointerType
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
    assert r.value == 0, "expected 0, got %r" % r


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


if __name__ == "__main__":
    import helpers_test
    helpers_test.main(globals())
