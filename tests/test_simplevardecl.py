
from pprint import pprint
import helpers_test
from cparser import *

def test_simplevardecl():
    testcode = """
		int16_t a;
		int b = 42;
		void* c = &b;
		int* d = &b;
		char e, *f = "abc", g, **h = &f;
	"""

    state = helpers_test.parse(testcode)

    a = state.vars["a"]
    b = state.vars["b"]
    c = state.vars["c"]
    d = state.vars["d"]
    e = state.vars["e"]
    f = state.vars["f"]
    g = state.vars["g"]
    h = state.vars["h"]

    for v in "abcdefgh":
        var = locals()[v]
        assert state.vars[v] is var
        assert var.name == v

    assert a.type == CStdIntType("int16_t")
    assert a.body is None
    assert b.type == CBuiltinType(("int",))
    assert b.body is not None
    assert b.body.getConstValue(state) == 42
    assert c.type == CBuiltinType(("void","*"))
    #pprint(c.body) TODO: check <CStatement <COp '&'> <CStatement <CVarDecl 'b' ...
    assert d.type == CPointerType(CBuiltinType(("int",)))
    assert e.type == CBuiltinType(("char",))
    assert f.type == CPointerType(e.type)
    assert h.type == CPointerType(f.type)
    assert f.body.getConstValue(state) == "abc"
    #pprint(h.body)

def test_array_pointer_decl_reset():
    # Fix: self.type = None in clearDeclForNextVar
    testcode = """
        void _Py_DumpHexadecimal() {
            char buffer[17], *ptr, *end;
        }
    """
    state = helpers_test.parse(testcode)
    func = state.funcs["_Py_DumpHexadecimal"]
    vars = {v.name: v for v in func.body.contentlist if isinstance(v, CVarDecl)}

    assert "buffer" in vars
    assert "ptr" in vars
    assert "end" in vars

    assert isinstance(vars["buffer"].type, CArrayType)
    assert isinstance(vars["ptr"].type, CPointerType)
    assert isinstance(vars["end"].type, CPointerType)

    assert vars["ptr"].type.pointerOf == CBuiltinType(("char",))
    assert vars["end"].type.pointerOf == CBuiltinType(("char",))
