
from cparser import *
import helpers_test


def test_parse1():
    helpers_test.parse("int16_t (*f)();")

def test_parse2():
    helpers_test.parse("int16_t (*g)(char a, void*);")

def test_parse3():
    helpers_test.parse("int (*h);")

def test_parse4():
    helpers_test.parse("int fx(void), *fip(), (*pfi)();")

def test_parse5():
    helpers_test.parse("int (*apfi[3])(int *x, int *y);")

def test_parse6():
    # TODO...
    #helpers_test.parse("int (*fpfi(int (*)(long), int))(int, ...);")
    pass

def test_parse6_a():
    # TODO...
    #helpers_test.parse("int (*fpfi(int (*)(long), int))(int);")
    pass



def test_funcptrdecl():
    testcode = """
		int16_t (*f)();
		int16_t (*g)(char a, void*);
		int (*h);

		// ISO/IEC 9899:TC3 : C99 standard
		int fx(void), *fip(), (*pfi)(); // example 1, page 120
		int (*apfi[3])(int *x, int *y); // example 2, page 120
		//int (*fpfi(int (*)(long), int))(int, ...); // example 3, page 120
	"""

    state = helpers_test.parse(testcode)

    f = state.vars["f"]
    g = state.vars["g"]

    assert f.name == "f"
    assert isinstance(f.type, CFuncPointerDecl)
    assert f.type.type == CStdIntType("int16_t")
    assert f.type.args == []

    assert isinstance(g.type, CFuncPointerDecl)
    gargs = g.type.args
    assert isinstance(gargs, list)
    assert len(gargs) == 2
    assert isinstance(gargs[0], CFuncArgDecl)
    assert gargs[0].name == "a"
    assert gargs[0].type == CBuiltinType(("char",))
    assert gargs[1].name is None
    assert gargs[1].type == CBuiltinType(("void","*"))

    h = state.vars["h"]
    #assert h.type == CPointerType(CBuiltinType(("int",)))  # TODO?

    # TODO?
    #fx = state.funcs["fx"] # fx is a function `int (void)`
    #assert fx.type == CBuiltinType(("int",))
    #assert fx.args == []

    # TODO?
    #fip = state.funcs["fip"] # fip is a function `int* (void)`
    #assert fip.type == CPointerType(CBuiltinType(("int",)))
    #assert fip.args == []

    pfi = state.vars["pfi"] # pfi is a function-ptr to `int ()`
    assert isinstance(pfi.type, CFuncPointerDecl)
    assert pfi.type.type == CBuiltinType(("int",))
    assert pfi.type.args == []

    apfi = state.vars["apfi"] # apfi is an array of three function-ptrs `int (int*,int*)`
    # ...

    # TODO...
    #fpfi = state.funcs["fpfi"] # function which returns a func-ptr
    # the function has the parameters `int(*)(long), int`
    # the func-ptr func returns `int`
    # the func-ptr func has the parameters `int, ...`

def test_kr_function_typed_parameter():
    """K&R style ``int f(int g(int))`` -- the inner ``g`` is a
    function-typed parameter, equivalent (C standard 6.7.6.3p8) to
    ``int (*g)(int)``.  cparser must accept this and produce a
    ``CFuncPointerDecl`` for ``g``.
    """
    state = helpers_test.parse('''
        static int call_me(int get_char(int));
        static int call_me(int get_char(int)) {
            return get_char(5);
        }
    ''')
    fn = state.funcs["call_me"]
    assert len(fn.args) == 1
    arg = fn.args[0]
    assert arg.name == "get_char"
    # arg.type should be a CFuncPointerDecl (or equivalent), NOT
    # a plain ``int``.  Before the fix this was just ``int``.
    from cparser.cparser import CFuncPointerDecl, CBuiltinType
    assert isinstance(arg.type, CFuncPointerDecl), \
        "K&R function-typed parameter should be a function pointer, " \
        "got: %r" % (arg.type,)


def test_cast_to_function_pointer_then_call():
    """``((int (*)(int))p)(x)`` -- cast a ``void *`` to a function
    pointer and then call it.  Used in CPython's
    ``Objects/moduleobject.c:PyModule_ExecDef``:

        ret = ((int (*)(PyObject *))cur_slot->value)(module);

    Before the fix cparser parsed the type-name ``int (*)(int)`` as
    an expression ``int()(int)`` (chain of function calls), which
    the interpreter then rejected with
    "Func ptr call: base ... is not a func ptr".
    """
    state = helpers_test.parse('''
        int call_via_cast(void *p, int x) {
            return ((int (*)(int))p)(x);
        }
    ''')
    from cparser.interpreter import Interpreter
    import ctypes
    interp = Interpreter()
    interp.register(state)
    fn = interp.getFunc("call_via_cast")
    assert fn is not None
    # Build a real C callback (``doubled``) on the host side, pass
    # its address as ``void *`` -- the interpreted ``call_via_cast``
    # casts it to ``int (*)(int)`` and invokes it.
    CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int)
    cb = CB(lambda v: v * 2)
    p = ctypes.cast(cb, ctypes.c_void_p)
    r = fn(p, ctypes.c_int(7))
    # ``r`` is a Python int (the unwrapped c_int return).
    assert r == 14, "expected 14, got %r" % (r,)


def test_ctypes_type_caching():
    # Fix: Global caching of CFUNCTYPE and POINTER
    state = State()

    # Test POINTER caching
    ptr1 = CPointerType(CBuiltinType(("int",))).getCType(state)
    ptr2 = CPointerType(CBuiltinType(("int",))).getCType(state)
    assert ptr1 is ptr2

    # Test CFUNCTYPE caching
    func1 = CFuncPointerDecl(type=CBuiltinType(("int",)), args=[CFuncArgDecl(type=CBuiltinType(("int",)))]).getCType(state)
    func2 = CFuncPointerDecl(type=CBuiltinType(("int",)), args=[CFuncArgDecl(type=CBuiltinType(("int",)))]).getCType(state)
    assert func1 is func2
