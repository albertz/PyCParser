
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

def test_parse_aritmethic_1():
	parse("if(0.5) {}")

def test_parse_aritmethic_1a():
	parse("if(0 == 0.5) {}")

def test_parse_aritmethic_1b():
	parse("if((0) * 0.5 == (0)) {}")

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

def test_parse_cast_ptr_attrib_access():
	parse("""
	typedef void *(*allocfunc)(void *, int);
	typedef struct {
		allocfunc tp_alloc;
	} MetaType;
	typedef struct {} PyTypeObject;
	void foo() {
		MetaType* metatype;
		PyTypeObject* type = (PyTypeObject *)metatype->tp_alloc(0, 0);
	}
	""")

def test_parse_cmp_null():
	parse("""
	#define NULL 0
	void* foo() {
		void* x;
		if(x == NULL) {}
	}
	""")

def test_parse_var_decl_existing_typedef():
	parse("""
	typedef struct {} PyObject;
	typedef struct {} state;
	void foo() {
		PyObject *state;
	}
	""")

def test_parse_var_decl_existing_typedef_asign():
	parse("""
	typedef struct {} PyObject;
	typedef struct {} state;
	void foo() {
		PyObject *state;
		state = 42;
		if(state * state == 0) {}
	}
	""")

def test_parse_nested_body():
	parse("void foo() {{ int x; }}")

def test_parse_two_nested_bodies():
	parse("void foo() { {int x;} {int x;} }")

def test_parse_nested_body_after_while():
	parse("void foo() { while(0) {int x;} {int x;} }")

def test_parse_nested_body_after_do_while():
	parse("void foo() { do {int x;} while(0); {int x;} }")

def test_parse_nested_body_after_do_while_while():
	parse("void foo() { do {} while(0); while(0) {} {} }")

def test_parse_while_after_do_while():
	parse("void foo() { do {} while(0); while(0) {} }")

def test_parse_goto_label():
	parse("""
	void foo() {
		label:
		int x = 1;
	}
	""")

def test_parse_goto_label_single_stmnt():
	parse("""
	void foo() {
		int x = 0;
		if(0) {}
		else
			label:
				x = 1;
	}
	""")

def test_parse_array():
	s = parse("int x[10];")
	x = s.vars["x"]
	print "x:", x
	assert isinstance(x, CVarDecl)
	assert isinstance(x.type, CArrayType)
	assert isinstance(x.type.arrayLen, CArrayStatement)
	assert x.type.arrayOf == CBuiltinType(("int",))
	l = getConstValue(s, x.type.arrayLen)
	assert l == 10

