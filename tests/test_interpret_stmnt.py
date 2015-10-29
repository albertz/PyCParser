
from cparser import *
from interpreter import *
from helpers_test import *
import ctypes


def test_interpret_c_cast():
	state = parse("int f()\n { int v = (int) 42; return v; } \n")
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42

def test_interpret_c_cast_ptr():
	state = parse("void f()\n { int* v = (int*) 42; } \n")
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r


def test_interpret_c_cast_ptr_2_a():
	state = parse("void f()\n { unsigned int v = (unsigned int) 42; } \n")
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r

def test_interpret_c_cast_ptr_2_b():
	state = parse("void f()\n { void* v = (void*) 42; } \n")
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r


def test_interpret_c_cast_ptr_2():
	state = parse(""" void f() {
		int x;
		int* v = (int*) x;
	} """)
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r

def test_interpret_c_cast_ptr_3():
	state = parse("""
	int g(int*) { return 3; }
	int f() {
		g((int*) 42);
		return 5;
	} """)
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5


def test_interpret_c_cast_ptr_4():
	state = parse("""
	int g(unsigned char * buff) { return 3; }
	int f() {
		g((unsigned char *) 42);
		return 5;
	} """)
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5


def test_interpret_auto_cast():
	state = parse("""
	void g(unsigned long) {}
	int f() {
		g((long) 42);
		return 5;
	} """)
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5

def test_interpret_auto_cast_2():
	state = parse("""
	void g(const char*, const char*) {}
	int f() {
		g(0, "foo");
		return 5;
	} """)
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5
