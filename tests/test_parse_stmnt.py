
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
	state = parse("int* v = (int*) 42;")
	v = state.vars["v"]
	assert isinstance(v.body, CStatement)
	# TODO ...
