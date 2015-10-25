
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

