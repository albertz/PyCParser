import sys
sys.path += [".."]
from pprint import pprint
import test

testcode = """
	int16_t a;
	int b = 42;
	void* c = &b;
	int* d = &b;
	char e, *f = "abc", g, **h = &f;
"""

state = test.parse(testcode)	

from cparser import *

for v in "abcdefgh":
	var = state.vars[v]
	globals()[v] = var
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

