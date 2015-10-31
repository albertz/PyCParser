
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
	parse("""
	#define macro(x) (x)
	int v = 0;
	if(macro(v)) {}
	""")

def test_parse_aritmethic():
	parse("""
	if(0 * 0.5) {}
	""")

def test_parse_macro_2a():
	state = cparser.State()
	preprocessed = state.preprocess_source_code("""
	#define Py_IS_INFINITY(X) ((X) * 0.5 == (X))
	if(Py_IS_INFINITY(0)) {}
	""")
	# preproccessed code will *not* substitute macros. that's handled by cpre2_parse.
	preprocessed = "".join(preprocessed)
	preprocessed = [l.strip() for l in preprocessed.splitlines()]
	preprocessed = "".join([l + "\n" for l in preprocessed if l])
	print("preprocessed:")
	pprint(preprocessed)
	tokens = cpre2_parse(state, preprocessed)
	if state._errors:
		print("parse errors after cpre2_parse:")
		pprint(state._errors)
	tokens = list(tokens)
	print("token list:")
	pprint(tokens)
	cpre3_parse(state, tokens)
	if state._errors:
		print("parse errors:")
		pprint(state._errors)
		assert False, "parse errors"

def test_parse_macro_2():
	parse("""
	#define Py_FORCE_DOUBLE(X) (X)
	#define Py_IS_NAN(X) ((X) != (X))
	#define Py_IS_INFINITY(X) ((X) &&                                   \
	                          (Py_FORCE_DOUBLE(X)*0.5 == Py_FORCE_DOUBLE(X)))
	#define Py_IS_FINITE(X) (!Py_IS_INFINITY(X) && !Py_IS_NAN(X))
	int v = 0;
	if(Py_IS_FINITE(v)) {}
	""")

