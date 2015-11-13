
import helpers_test
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

def test_interpret_var_init_wrap_value():
	state = cparser.State()
	state.autoSetupGlobalIncludeWrappers()

	cparser.parse_code("""
	#include <stdio.h>  // stdout
	int f() {
		FILE* f = stdout;
		return 5;
	} """, state)
	print "Parse errors:", state._errors
	assert not state._errors

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


def test_interpret_var_init_wrap_value_2():
	state = cparser.State()
	state.autoSetupGlobalIncludeWrappers()

	cparser.parse_code("""
	#include <stdio.h>  // stdout / stderr
	int f() {
		int v = 0;
		FILE* f = v ? stdout : stderr;
		return 5;
	} """, state)
	print "Parse errors:", state._errors
	assert not state._errors

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


def test_interpret_call_void_func():
	state = parse("""
	int g() {}
	int f() {
		(void) g();
		return 5;
	} """)
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Parsed funcs:"
	pprint(state.funcs["g"])
	pprint(state.funcs["g"].args)
	pprint(state.funcs["g"].body)
	pprint(state.funcs["f"])
	pprint(state.funcs["f"].args)
	pprint(state.funcs["f"].body)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	f = state.funcs["f"]
	assert isinstance(f, CFunc)
	assert isinstance(f.body, CBody)
	assert len(f.body.contentlist) == 2
	call_stmnt = f.body.contentlist[0]
	print "Call statement:", call_stmnt
	assert isinstance(call_stmnt, CStatement)
	assert isinstance(call_stmnt._leftexpr, CFuncCall)
	assert isinstance(call_stmnt._leftexpr.base, CStatement)
	assert isinstance(call_stmnt._leftexpr.base._leftexpr, CBuiltinType)
	assert call_stmnt._leftexpr.base._leftexpr.builtinType == ("void", )

	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5


def test_interpret_goto_forward():
	state = parse("""
	int f() {
		goto final;
		return 3;
	final:
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


def test_interpret_goto_backward():
	state = parse("""
	int f() {
		int x = 0;
	again:
		if(x > 0)
			return 42;
		x += 1;
		goto again;
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
	assert r.value == 42

def test_interpret_do_while():
	state = parse("""
	int f() {
		int x = 0;
		do {
			x += 1;
		} while(0);
		return x;
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
	assert r.value == 1

def test_interpret_inplacce_add():
	state = parse("""
	int f() {
		int x = 42;
		x += 1;
		return x;
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
	assert r.value == 43

def test_interpret_do_while_while():
	state = parse("""
	int f() {
		int x = 0;
		do {
			x += 1;
		} while(0);
		while(x < 3) {
			x++;
		}
		return x;
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
	assert r.value == 3

def test_interpret_goto_label_single_stmnt():
	state = parse("""
	int f() {
		int x = 0;
		if(1) {}
		else
			label:
				x = 1;
		if(x == 0)
			goto label;
		return x;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 1

def test_interpret_goto_in_nested():
	state = parse("""
	int f() {
		int x = 0;
		while(1) {
			x = 1;
		again:
			if(x >= 5)
				break;
			x += 1;
			goto again;
		}
		return x;
	}
	""")
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

def test_interpret_goto_into_nested():
	state = parse("""
	int f() {
		int x = 1;
		goto here;
		while(1) {
			x += 3;
			break;
		here:
			x *= 2;
		}
		return x;
	}
	""")
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


def test_interpret_goto_into_nested_for_loop():
	state = parse("""
	int f() {
		int x = 1;
		goto here;
		for(x=0; ; x++) {
			x += 2;
			break;
		here:
			x *= 2;
		}
		return x;
	}
	""")
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


def test_interpret_for_loop_empty():
	state = parse("""
	int f() {
		for(;;) {
			break;
		}
		return 5;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Parsed func body:"
	pprint(state.funcs["f"].body)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5


def test_interpret_nested_var():
	state = parse("""
	int f() {
		int x = 1;
		{
			int x = 2;
			x = 3;
		}
		x = 4;
		return x;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	interpreter.registerFinalize()

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 4

