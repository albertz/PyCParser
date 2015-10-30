
from cparser import *
from helpers_test import *


def test_parse_var_decl():
	state = parse("int v;")
	assert "v" in state.vars
	v = state.vars["v"]
	assert isinstance(v.type, CBuiltinType)
	assert v.type.builtinType == ("int", )

def test_parse_var_decl_body():
	state = parse("int v = 42;")
	v = state.vars["v"]
	assert isinstance(v.body, CStatement)
	value = v.body._leftexpr
	assert isinstance(value, CNumber)
	assert value.content == 42

def test_parse_var_decl_ptr():
	state = parse("int* v;")
	assert "v" in state.vars
	v = state.vars["v"]
	assert isinstance(v.type, CPointerType)
	assert isinstance(v.type.pointerOf, CBuiltinType)
	assert v.type.pointerOf.builtinType == ("int", )

def test_parse_var_decl_ptr_body():
	state = parse("int* v = 42;")
	v = state.vars["v"]
	assert isinstance(v.body, CStatement)
	value = v.body._leftexpr
	assert isinstance(value, CNumber)
	assert value.content == 42

def test_parse_c_cast():
	state = parse("int v = (int) 42;")
	v = state.vars["v"]
	assert isinstance(v.body, CStatement)
	# TODO ...

def test_parse_c_cast_ptr():
	state = parse("unsigned int v = (unsigned int) 42;")
	v = state.vars["v"]
	assert isinstance(v.body, CStatement)
	# TODO ...

def test_parse_macro():
	state = parse("""
	#define macro(x) (x)
	int v = 0;
	if(macro(v)) {}
	""")

def test_parse_macro_2():
	state = parse("""
	#define Py_FORCE_DOUBLE(X) (X)
	#define Py_IS_NAN(X) ((X) != (X))
	#define Py_IS_INFINITY(X) ((X) &&                                   \
	                          (Py_FORCE_DOUBLE(X)*0.5 == Py_FORCE_DOUBLE(X)))
	#define Py_IS_FINITE(X) (!Py_IS_INFINITY(X) && !Py_IS_NAN(X))
	int v = 0;
	if(Py_IS_FINITE(v)) {}
	""")

