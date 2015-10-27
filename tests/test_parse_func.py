
from helpers_test import *

def test_parse_void_func():
	state = parse("void f() {}")
	assert "f" in state.funcs

def test_parse_int_func():
	state = parse("int f() {}")
	assert "f" in state.funcs

def test_parse_static_void_func():
	state = parse("static void f() {}")
	assert "f" in state.funcs
