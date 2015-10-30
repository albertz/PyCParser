
from cparser import *
from helpers_test import *

def test_parse_void_func():
	state = parse("void f() {}")
	assert "f" in state.funcs
	f = state.funcs["f"]
	print f
	assert isinstance(f, CFunc)

def test_parse_int_func():
	state = parse("int f() {}")
	assert "f" in state.funcs
	f = state.funcs["f"]
	print f
	assert isinstance(f, CFunc)
	assert isinstance(f.type, CBuiltinType)

def test_parse_static_void_func():
	state = parse("static void f() {}")
	assert "f" in state.funcs

def test_parse_variadic_args():
	state = parse("void f(...) {}")
	assert "f" in state.funcs
	f = state.funcs["f"]
	print f
	assert isinstance(f, CFunc)
	assert len(f.args) == 1
	arg0 = f.args[0]
	assert isinstance(arg0, CFuncArgDecl)
	assert isinstance(arg0.type, CVariadicArgsType)

def test_parse_void_func_self_call():
	state = parse("void f() { f(); }")
	assert "f" in state.funcs
	f = state.funcs["f"]
	print f
	assert isinstance(f, CFunc)
