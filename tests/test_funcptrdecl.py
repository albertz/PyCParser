
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
