import sys
sys.path += [".."]
from pprint import pprint
from cparser import *
import test

testcode = """
	int16_t (*f)();
	int16_t (*g)(char a, void*);
	int (*h);
"""

state = test.parse(testcode)	

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

# TODO: actually, I'm not sure. what is h?
#h = state.vars["h"]
#pprint(h)
