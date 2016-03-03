
import helpers_test
from cparser import *
from interpreter import *
from helpers_test import *
import ctypes


def test_interpret_c_cast():
	state = parse("int f()\n { int v = (int) 42; return v; } \n")
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42

def test_interpret_c_cast_ptr():
	state = parse("void f()\n { int* v = (int*) 0; } \n")
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r


def test_interpret_c_cast_ptr_2_a():
	state = parse("void f()\n { unsigned int v = (unsigned int) 42; } \n")
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r

def test_interpret_c_cast_ptr_2_b():
	state = parse("void f()\n { void* v = (void*) 0; } \n")
	interpreter = Interpreter()
	interpreter.register(state)

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

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r

def test_interpret_c_cast_ptr_3():
	state = parse("""
	int g(int*) { return 3; }
	int f() {
		g((int*) 0);
		return 5;
	} """)
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("g", output=sys.stdout)
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
		g((unsigned char *) "x");
		return 5;
	} """)
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("g", output=sys.stdout)
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

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5


def test_interpret_call_void_func():
	state = parse("""
	int g() { return 0; }
	int f() {
		(void) g();
		return 5;
	} """)
	interpreter = Interpreter()
	interpreter.register(state)

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
	assert isinstance(call_stmnt._leftexpr.base, CBuiltinType)
	assert call_stmnt._leftexpr.base.builtinType == ("void", )

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

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5


def test_interpret_goto_with_if_else():
	state = parse("""
	int f() {
		int x = 1;
		goto here;
		here:
		if(x <= 3) x = 5;
		else x = 13;
		return x;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)

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

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 4


def test_interpret_ptr_array():
	state = parse("""
	typedef struct _object { long foo; } PyObject;
	typedef struct _tuple {
		PyObject *ob_item[1];
	} PyTupleObject;
	#define PyTuple_GET_ITEM(op, i) (((PyTupleObject *)(op))->ob_item[i])

	PyObject tupleGlobal;

	void* f() {
		PyObject* tuple = &tupleGlobal;
		PyObject* obj = PyTuple_GET_ITEM(tuple, 0);
		return obj;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	print "PyTupleObject:", state.typedefs["PyTupleObject"]
	assert isinstance(state.typedefs["PyTupleObject"].type, CStruct)
	print "PyTupleObject body:"
	assert isinstance(state.typedefs["PyTupleObject"].type.body, CBody)
	pprint(state.typedefs["PyTupleObject"].type.body.contentlist)
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_void_p)
	assert r.value != 0


def test_interpret_global_obj():
	state = parse("""
	typedef struct _object { long foo; } PyObject;
	PyObject obj;
	void* f() {
		return &obj;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_void_p)
	assert r.value != 0


def test_interpret_array():
	state = parse("""
	int f() {
		int a[5];
		a[1] = 5;
		a[2] = 13;
		return a[1];
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5


def test_interpret_func_call_auto_cast():
	state = parse("""
	int add(int n) { return n; }
	int f() {
		return add(3 + 2);
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("add", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5


def test_interpret_init_struct():
	state = parse("""
	typedef struct _A { int a, b, c; } A;
	int f() {
		A s = {1, 2, 3};
		return s.b;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	vardecl = state.funcs["f"].body.contentlist[0]
	assert isinstance(vardecl, CVarDecl)
	assert vardecl.name == "s"
	print "var decl s body:"
	print vardecl.body
	print "_A:"
	print state.structs["_A"]
	print "_A body:"
	print state.structs["_A"].body

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 2


def test_interpret_init_struct_via_self():
	state = parse("""
	#include <assert.h>
	typedef struct _A { void* self; int x; } A;
	A s = {&s, 42};
	int f() {
		assert((&s) == s.self);
		return s.x;
	}
	""",
	withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	print "s:", state.vars["s"]
	print "s body:", state.vars["s"].body
	s = state.vars["s"]
	s_body = s.body
	assert isinstance(s_body, CStatement)
	assert isinstance(s_body._leftexpr, CCurlyArrayArgs)
	s_body = s_body._leftexpr
	assert len(s_body.args) == 2
	assert isinstance(s_body.args[0], CStatement)
	assert s_body.args[0]._leftexpr is None
	assert s_body.args[0]._op == COp("&")
	assert isinstance(s_body.args[0]._rightexpr, CStatement)
	s_body_ref = s_body.args[0]._rightexpr
	assert s_body_ref._leftexpr is state.vars["s"]

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_init_array():
	state = parse("""
	int f() {
		int a[] = {1, 2, 3};
		return a[2];
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	vardecl = state.funcs["f"].body.contentlist[0]
	assert isinstance(vardecl, CVarDecl)
	assert vardecl.name == "a"
	print "var decl a body:"
	print vardecl.body
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 3


def test_interpret_init_array_sizeof():
	state = parse("""
	int f() {
		int a[] = {1, 2, 3, 4, 5};
		return sizeof(a);
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	vardecl = state.funcs["f"].body.contentlist[0]
	assert isinstance(vardecl, CVarDecl)
	assert vardecl.name == "a"
	print "var decl a body:"
	print vardecl.body
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5 * ctypes.sizeof(ctypes.c_int)


def test_interpreter_char_array():
	state = parse("""
	int f() {
		char name[] = "foo";
		return sizeof(name);
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	vardecl = state.funcs["f"].body.contentlist[0]
	assert isinstance(vardecl, CVarDecl)
	assert vardecl.name == "name"
	print "var decl a body:"
	print vardecl.body
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 4


def test_interpreter_global_char_array():
	state = parse("""
	static char name[] = "foo";
	int f() {
		return sizeof(name);
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 4


def test_interpreter_offset_of_direct():
	state = parse("""
	typedef struct _typeobject { long foo; long bar; } PyTypeObject;
	int f() {
		int a = (int) &((PyTypeObject*)(0))->bar;
		return a;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	vardecl = state.funcs["f"].body.contentlist[0]
	assert isinstance(vardecl, CVarDecl)
	assert vardecl.name == "a"
	print "var decl a body:"
	print vardecl.body
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ctypes.sizeof(ctypes.c_long)


def test_interpreter_num_cast():
	state = parse("""
	int f() {
		int a = (int) 'A';
		return a;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	vardecl = state.funcs["f"].body.contentlist[0]
	assert isinstance(vardecl, CVarDecl)
	assert vardecl.name == "a"
	print "var decl a body:"
	print vardecl.body
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ord('A')


def test_interpreter_func_ptr():
	state = parse("""
	typedef int (*F) ();
	int i() { return 42; }
	int f() {
		F fp = i;
		int v = fp();
		return v;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpreter_func_ptr_return_ptr():
	state = parse("""
	typedef int* (*F) ();
	int _i = 42;
	int* i() { return &_i; }
	int f() {
		F fp = i;
		int* vp = fp();
		return *vp;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpreter_func_ptr_struct_init():
	state = parse("""
	#include <assert.h>
	typedef int (*F) ();
	typedef struct _S { int x; F f; } S;
	int i() { return 42; }
	S s = {3, i};
	int f() {
		assert(s.x == 3);
		//assert(s.f == (F) i);  // not sure what's needed for this
		return s.x + s.f();
	}
	""", withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("i", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	#s = interpreter.globalScope.vars["s"]
	#print s, s._fields_, s.x, s.f
	assert isinstance(r, ctypes.c_int)
	assert r.value == 45


def test_interpreter_func_ptr_struct_init_unknown():
	state = parse("""
	#include <assert.h>
	typedef long (*F) ();
	typedef struct _S { int x; F f; } S;
	long unknown_func();
	S s = {3, unknown_func};
	int f() {
		assert(s.x == 3);
		assert((void*) s.f != 0);
		return s.x + s.f();
	}
	""", withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	# Because the unknown_func will by default return 0.
	assert r.value == 3


def test_interpret_op_precedence_ref():
	state = parse("""
	#include <assert.h>
	typedef struct _A { int* x; } A;
	int f() {
		int a = 42;
		A b = {&a};
		assert(&a == b.x);
		*b.x += 1;
		return a;
	}
	""",
	withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	interpreter = Interpreter()
	interpreter.register(state)

	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 43


def test_interpret_multiple_vars():
	state = parse("""
	int f() {
		int a = 23, b, c;
		c = 42;
		return c;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_sizeof_ptr():
	state = parse("""
	int f() {
		return sizeof(int*);
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ctypes.sizeof(ctypes.c_void_p)


def test_interpret_multi_stmnt():
	state = parse("""
	int f() {
		int j = 0;
		int i, n = 1;
		for (i = 0; i < n; i++, j++) {
		}
		return i;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 1


def test_interpret_multi_stmnt_body():
	state = parse("""
	int f() {
		int i = 1, j = 2;
		i++, j++;
		return i + j;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5


def test_interpret_prefix_inc_ret():
	state = parse("""
	int f() {
		int i = 0;
		return ++i;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 1


def test_interpret_postfix_inc_ret():
	state = parse("""
	int f() {
		int i = 0;
		return i++;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 0


def test_interpret_postfix_inc():
	state = parse("""
	int f() {
		int i = 0;
		i++;
		return i;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 1


def test_interpret_return_ptr():
	state = parse("""
	const char* g() { return "hey"; }
	int f() {
		const char* s = g();
		return *s;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("g", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ord("h")


def test_interpret_malloc():
	state = parse("""
	#include <stdlib.h>
	#include <string.h>
	char* g() {
		char* s = malloc(5);
		strcpy(s, "hey");
		return s;
	}
	int f() {
		char* s = g();
		char c = *s;
		free(s);
		return c;
	}
	""",
	withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("g", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ord("h")


def test_interpret_malloc_with_cast():
	state = parse("""
	#include <stdlib.h>
	#include <string.h>
	char* g() {
		char* s = (char*) malloc(5);
		strcpy(s, "hey");
		return s;
	}
	int f() {
		char* s = g();
		char c = *s;
		free(s);
		return c;
	}
	""",
	withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("g", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ord("h")


def test_interpret_noname_struct_init():
	state = parse("""
	typedef struct { int x; } S;
	int f() {
		S s;
		s.x = 42;
		return s.x;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_struct_ambig_name():
	# https://github.com/albertz/PyCParser/issues/2
	state = parse("""
	typedef struct
	{
		int number;
	} Number;
	struct XYZ
	{
		Number Number[10];
	};
	int f() {
		struct XYZ s;
		s.Number[1].number = 42;
		s.Number[2].number = 3;
		return s.Number[1].number;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_condition():
	# https://github.com/albertz/PyCParser/issues/3
	state = parse("""
	int f()
	{
		int i = 5, j = 6, k = 1;
		if ((i=j && k == 1) || k > j)
			return i;
		return -17;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	# Note: i = (j && (k == 1)).
	assert r.value == 1


def test_interpret_void_ptr_cast():
	state = parse("""
	int g(int *) { return 42; }
	int f() {
		void* obj = 0;
		return g((int *)obj);
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_void_cast_two_args():
	state = parse("""
	int f() {
		int a, b;
		(void) (a = 1, (b = 2, &a));
		return b;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 2


def test_interpret_macro_file_line():
	state = parse("""
	void PyErr_BadInternalCall(void) {}
	void _PyErr_BadInternalCall(char *filename, int lineno) {}
	#define PyErr_BadInternalCall() _PyErr_BadInternalCall(__FILE__, __LINE__)
	int f() {
		PyErr_BadInternalCall();
		return 42;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_reserved_global_varname():
	state = parse("""
	void h() {}
	int f() {
		h();
		int g = 42;
		return g;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_stmnt_no_space():
	state = parse("""
	int f() {
		int foo = 6, bar = 3;
		if (foo/bar == 2)
			return 13;
		return 5;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 13


def test_interpret_marco_if0():
	state = parse("""
	int f() {
	#if 0
		return 13;
	#endif
		return 5;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 5


def test_interpret_varname_like_struct():
	state = parse("""
	typedef struct { int x; } PyGC_Head;
	typedef int node; // problematic
	void g(PyGC_Head *node) {
		node->x = 13;
	}
	int f() {
		PyGC_Head node;
		g(&node);
		return node.x;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 13


def test_interpret_malloc_macro():
	state = parse("""
	#include <stdlib.h>
	typedef int PyGC_Head;
	#define PY_SSIZE_T_MAX ((long)(((size_t)-1)>>1))
	#define PyObject_MALLOC         PyMem_MALLOC
	#define PyObject_FREE           PyMem_FREE
	#define PyMem_MALLOC(n)		((size_t)(n) > (size_t)PY_SSIZE_T_MAX ? 0 \
					: malloc((n) ? (n) : 1))
	#define PyMem_FREE		free
	int f() {
		int basicsize = 20;
		PyGC_Head* g;
		g = (PyGC_Head *)PyObject_MALLOC(
			sizeof(PyGC_Head) + basicsize);
		PyObject_FREE(g);
		return 42;
	}
	""",
	withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_malloc_in_ternary():
	state = parse("""
	#include <stdlib.h>
	int f() {
		void* g = 0 ? 0 : malloc(12);
		free(g);
		return 42;
	}
	""",
	withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_double_macro():
	state = parse("""
	#define M1 M2
	#define M2(n) (n * 2)
	int f() {
		int x = M1(5);
		return x;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 10


def test_interpret_max_uint16():
	state = parse("""
	#include <stdint.h>
	int64_t f() {
		int64_t x = (uint16_t) -1;
		return x;
	}
	""",
	withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int64)
	assert r.value == 2 ** 16 - 1


def test_interpret_max_uint16_plus1():
	state = parse("""
	#include <stdint.h>
	int64_t f() {
		int64_t x = (int32_t)(uint16_t)(-1) + 1;
		return x;
	}
	""",
	withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int64)
	assert r.value == 2 ** 16


def test_interpret_ternary_second():
	state = parse("""
	long f() {
		long max_ushort = (unsigned short)(-1);
		long x = (long)(max_ushort) + 1;
		long g = 0 ? (unsigned short)(0) : x;
		return g;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_long)
	assert r.value == 256 ** ctypes.sizeof(ctypes.c_short)


def test_interpret_double_cast():
	state = parse("""
	long f() {
		long x = (int)(unsigned short)(-1);
		return x;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_long)
	assert r.value == 256 ** ctypes.sizeof(ctypes.c_short) - 1


def test_interpret_int_float():
	state = parse("""
	int f() {
		int x = 4 * 0.5;
		return x;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 2


def test_interpret_float_cast():
	state = parse("""
	int f() {
		int x = (int) 2.2;
		return x;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 2


def test_interpret_double():
	state = parse("""
	double f() {
		double x = 2.5;
		return x;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_double)
	assert r.value == 2.5


def test_interpret_strlen_plus1():
	state = parse("""
	#include <stdint.h>
	#include <string.h>
	size_t f() {
		size_t x = strlen("foo") + 1;
		return x;
	}
	""",
	withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_size_t)
	assert r.value == 4


def test_interpret_cond_c_str():
	state = parse("""
	const char* f() {
		const char* s = 0 ? "foo" : "bazz";
		return 0 ? "blubber" : s;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	wrapped_c_byte = interpreter.globalsDict["ctypes_wrapped"].c_byte
	assert isinstance(r, ctypes.POINTER(wrapped_c_byte))  # char is always byte in the interpreter
	r = ctypes.cast(r, ctypes.c_char_p)
	assert r.value == "bazz"


def test_interpret_cstr():
	state = parse("""
	int f() {
		const char* p = 0;
		p = 0 ? 0 : "P";
		return *p;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ord("P")


def test_interpret_cstr_indirect():
	state = parse("""
	const char* g() { return "foo"; }
	int f() {
		const char* p = 0;
		p = 0 ? 0 : g();
		return *p;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ord("f")


def test_interpret_struct_forward_type():
	state = parse("""
	typedef struct _A {
		struct _B *b;
	} A;
	typedef struct _B {
		int x;
	} B;
	int f() {
		A a;
		B b;
		a.b = &b;
		a.b->x = 42;
		return a.b->x + 1;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 43


def test_interpret_struct_array():
	state = parse("""
	/* GC information is stored BEFORE the object structure. */
	typedef union _gc_head {
		struct {
			union _gc_head *gc_next;
			union _gc_head *gc_prev;
			unsigned long gc_refs;
		} gc;
		long double dummy;  /* force worst-case alignment */
	} PyGC_Head;

	struct gc_generation {
		PyGC_Head head;
		int threshold; /* collection threshold */
		int count; /* count of allocations or collections of younger
					  generations */
	};

	#define NUM_GENERATIONS 3
	#define GEN_HEAD(n) (&generations[n].head)

	/* linked lists of container objects */
	static struct gc_generation generations[NUM_GENERATIONS] = {
		/* PyGC_Head,                               threshold,      count */
		{{{GEN_HEAD(0), GEN_HEAD(0), 0}},           700,            0},
		{{{GEN_HEAD(1), GEN_HEAD(1), 0}},           10,             0},
		{{{GEN_HEAD(2), GEN_HEAD(2), 0}},           10,             0},
	};

	int f() {
		// via _PyObject_GC_Malloc
	    generations[0].count++; /* number of allocated GC objects */
		return generations[0].count;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 1


def test_interpret_global_array():
	state = parse("""
	int x[3] = {3,2,1};
	int f() {
	    x[1]++;
		return x[1];
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)
	print "x:", state.vars["x"]

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 3


def test_interpret_gc_malloc():
	state = parse("""
	#include <stdlib.h>

	typedef struct _PyObject { int x; } PyObject;

	/* GC information is stored BEFORE the object structure. */
	typedef union _gc_head {
		struct {
			union _gc_head *gc_next;
			union _gc_head *gc_prev;
			long gc_refs;
		} gc;
		long double dummy;  /* force worst-case alignment */
	} PyGC_Head;

	/* Get an object's GC head */
	#define AS_GC(o) ((PyGC_Head *)(o)-1)

	/* Get the object given the GC head */
	#define FROM_GC(g) ((PyObject *)(((PyGC_Head *)g)+1))

	PyObject* PyObject_GC_Malloc(size_t basicsize) {
		PyObject *op;
		PyGC_Head *g;
		g = (PyGC_Head *)malloc(sizeof(PyGC_Head) + basicsize);
		g->gc.gc_refs = -1;
		op = FROM_GC(g);
		return op;
	}

	void PyObject_GC_Del(void *op) {
		PyGC_Head *g = AS_GC(op);
		free(g);
	}

	int f() {
		PyObject* obj = PyObject_GC_Malloc(16);
		PyObject_GC_Del(obj);
		return 42;
	}
	""",
	withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("PyObject_GC_Malloc", output=sys.stdout)
	interpreter.dumpFunc("PyObject_GC_Del", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_get_opt():
	state = parse("""
	#include <stdio.h>
	#include <string.h>

	int _PyOS_opterr = 1;          /* generate error messages */
	int _PyOS_optind = 1;          /* index into argv array   */
	char *_PyOS_optarg = NULL;     /* optional argument       */
	static char *opt_ptr = "";

	int _PyOS_GetOpt(int argc, char **argv, char *optstring) {
		char *ptr;
		int option;

		if (*opt_ptr == '\0') {

			if (_PyOS_optind >= argc)
				return -1;

			else if (argv[_PyOS_optind][0] != '-' ||
					 argv[_PyOS_optind][1] == '\0' /* lone dash */ )
				return -1;

			else if (strcmp(argv[_PyOS_optind], "--") == 0) {
				++_PyOS_optind;
				return -1;
			}

			else if (strcmp(argv[_PyOS_optind], "--help") == 0) {
				++_PyOS_optind;
				return 'h';
			}

			else if (strcmp(argv[_PyOS_optind], "--version") == 0) {
				++_PyOS_optind;
				return 'V';
			}


			opt_ptr = &argv[_PyOS_optind++][1];
		}

		if ((option = *opt_ptr++) == '\0')
			return -1;

		if (option == 'J') {
			if (_PyOS_opterr)
				fprintf(stderr, "-J is reserved for Jython\n");
			return '_';
		}

		if (option == 'X') {
			if (_PyOS_opterr)
				fprintf(stderr,
					"-X is reserved for implementation-specific arguments\n");
			return '_';
		}

		if ((ptr = strchr(optstring, option)) == NULL) {
			if (_PyOS_opterr)
				fprintf(stderr, "Unknown option: -%c\n", option);

			return '_';
		}

		if (*(ptr + 1) == ':') {
			if (*opt_ptr != '\0') {
				_PyOS_optarg  = opt_ptr;
				opt_ptr = "";
			}

			else {
				if (_PyOS_optind >= argc) {
					if (_PyOS_opterr)
						fprintf(stderr,
							"Argument expected for the -%c option\n", option);
					return '_';
				}

				_PyOS_optarg = argv[_PyOS_optind++];
			}
		}

		return option;
	}

	int f() {
		int c;
		int argc = 3;
		char* argv[] = {"./cpython.py", "-c", "print 'hello'", 0};
	    while ((c = _PyOS_GetOpt(argc, argv, "3bBc:dEhiJm:OQ:RsStuUvVW:xX?")) != -1) {
		}
		return 42;
	}
	""",
	withGlobalIncludeWrappers=True)
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("_PyOS_GetOpt", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_char_p_substract():
	state = parse("""
	int f() {
	    const char* a = "hello";
	    const char* b = a + 3;
		return (int) (b - a);
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 3


def test_interpret_ptr_comma_tuple():
	state = parse("""
	int f() {
	    const char* a = "hello";
	    const char* b;
		return (b = a), 42;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_octal():
	state = parse("""
	int f() {
		return (int) '\\014';
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 12


def test_interpret_macro_version_hex():
	state = parse("""
	/* Values for PY_RELEASE_LEVEL */
	#define PY_RELEASE_LEVEL_ALPHA	0xA
	#define PY_RELEASE_LEVEL_BETA	0xB
	#define PY_RELEASE_LEVEL_GAMMA	0xC     /* For release candidates */
	#define PY_RELEASE_LEVEL_FINAL	0xF	/* Serial should be 0 here */
						/* Higher for patch releases */

	/* Version parsed out into numeric values */
	/*--start constants--*/
	#define PY_MAJOR_VERSION	2
	#define PY_MINOR_VERSION	7
	#define PY_MICRO_VERSION	5
	#define PY_RELEASE_LEVEL	PY_RELEASE_LEVEL_FINAL
	#define PY_RELEASE_SERIAL	0

	/* Version as a string */
	#define PY_VERSION      	"2.7.5"
	/*--end constants--*/

	/* Subversion Revision number of this file (not of the repository). Empty
	   since Mercurial migration. */
	#define PY_PATCHLEVEL_REVISION  ""

	/* Version as a single 4-byte hex number, e.g. 0x010502B2 == 1.5.2b2.
	   Use this for numeric comparisons, e.g. #if PY_VERSION_HEX >= ... */
	#define PY_VERSION_HEX ((PY_MAJOR_VERSION << 24) | \
				(PY_MINOR_VERSION << 16) | \
				(PY_MICRO_VERSION <<  8) | \
				(PY_RELEASE_LEVEL <<  4) | \
				(PY_RELEASE_SERIAL << 0))

	long f() {
		return PY_VERSION_HEX;
	}
	""")
	print "Parsed:"
	print "f:", state.funcs["f"]
	print "f body:"
	assert isinstance(state.funcs["f"].body, CBody)
	pprint(state.funcs["f"].body.contentlist)

	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r, hex(r.value)
	assert isinstance(r, ctypes.c_long)
	assert r.value == 0x20705f0


def test_interpret_double_macro_rec():
	"""
	Check cpre2_parse() for correctly substituting macros
	-- not applying the same macro twice in recursion.
	"""
	state = parse("""
	int a() { return 2; }
	int b() { return 3; }
	#define a b
	#define b a
	int f_a() { return a(); }
	int f_b() { return b(); }
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f_a", output=sys.stdout)
	interpreter.dumpFunc("f_b", output=sys.stdout)
	print "Run:"
	r_a = interpreter.runFunc("f_a")
	r_b = interpreter.runFunc("f_b")
	print "result:", r_a, r_b
	assert r_a.value == 2
	assert r_b.value == 3


def test_interpret_simple_add_two_b():
	state = parse("""
	int a() { return 2; }
	int f() { return 1 + a() + a(); }
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 5


def test_interpret_double_macro_rec_linear():
	state = parse("""
	int a() { return 2; }
	#define b a
	#define x (1 + b() + b())
	int f() { return x; }
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 5


def test_interpret_undefined_macro():
	state = parse("""
	int f() {
	#if not_defined_macro
		return -3;
	#endif
		return 5;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 5


def test_interpret_macro_call_twice():
	state = parse("""
	#define INC(x) (x + 1)
	int f(int a) {
		return INC(INC(a));
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f", 3)
	print "result:", r
	assert r.value == 5


def test_interpret_macro_concat():
	state = parse("""
	#define PREFIX( x) foo_ ## x
	int f() {
		int foo_bar = 5;
		return PREFIX( bar);
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 5


def test_interpret_cast_const_void_p():
	state = parse("""
	int f(const char *target) {
		const void * x = 0;
		x = (const void *)(target);
		return 5;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f", "x")
	print "result:", r
	assert r.value == 5


def test_interpret_cast_const_int():
	state = parse("""
	int f() {
		int x = 0;
		x = (const int)(5);
		return x;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 5


def test_interpret_for_if_else():
	state = parse("""
	int f() {
		int i;
		for (i = 0; i < 10; ++i)
		if (i <= 2) {}
		else {
			return 5;
		}
		return -1;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 5



def test_interpret_char_array_cast_len_int():
	state = parse("""
	int f() {
		char formatbuf[(int)5];
		return sizeof(formatbuf);
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 5


def test_interpret_char_array_cast_len_sizet():
	state = parse("""
	int f() {
		char formatbuf[(size_t)5];
		return sizeof(formatbuf);
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 5


def test_interpret_int_float_cast():
	state = parse("""
	int f() {
		return int(3.2);
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 3


def test_interpret_char_mask_ptr_deref():
	state = parse("""
	typedef struct { char ob_sval[1]; } PyStringObject;
	#define Py_CHARMASK(c)		((unsigned char)((c) & 0xff))
	int f() {
		PyStringObject _a, _b;
		_a.ob_sval[0] = 'A'; _b.ob_sval[0] = 'B';
		PyStringObject *a = &_a, *b = &_b;
        int c = Py_CHARMASK(*a->ob_sval) - Py_CHARMASK(*b->ob_sval);
		return c;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 255


def test_interpret_char_mask_subscript():
	state = parse("""
	#define Py_CHARMASK(c)		((unsigned char)((c) & 0xff))
	int f() {
		const char* s = "hello";
        int c = Py_CHARMASK(s[1]);
		return c;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == ord('e')


def test_interpret_op_mod():
	state = parse("""
	int f() {
		int j = 11, tabsize = 8;
        return tabsize - (j % tabsize);
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 5


def test_interpret_py_init_slots_array():
	state = parse("""
	typedef int PyObject;
	typedef PyObject * (*binaryfunc)(PyObject *, PyObject *);
	typedef struct {
		binaryfunc nb_add;
	} PyNumberMethods;
	typedef struct _heaptypeobject {
		PyNumberMethods as_number;
	} PyHeapTypeObject;
	static PyObject *
	wrap_binaryfunc_l(PyObject *self, PyObject *args, void *wrapped) { return 0; }
	#define SLOT1BINFULL(FUNCNAME, TESTFUNC, SLOTNAME, OPSTR, ROPSTR) \\
	static PyObject * FUNCNAME(PyObject *self, PyObject *other) { return 0; }
	#define SLOT1BIN(FUNCNAME, SLOTNAME, OPSTR, ROPSTR) \\
		SLOT1BINFULL(FUNCNAME, FUNCNAME, SLOTNAME, OPSTR, ROPSTR)
	SLOT1BIN(slot_nb_add, nb_add, "__add__", "__radd__")
	typedef PyObject *(*wrapperfunc)(PyObject *self, PyObject *args,
									 void *wrapped);
	struct wrapperbase {
		char *name;
		int offset;
		void *function;
		wrapperfunc wrapper;
		char *doc;
		int flags;
		PyObject *name_strobj;
	};
	typedef struct wrapperbase slotdef;
	#define offsetof(type, member) ( (int) & ((type*)0) -> member )
	#define ETSLOT(NAME, SLOT, FUNCTION, WRAPPER, DOC) \\
	{NAME, offsetof(PyHeapTypeObject, SLOT), (void *)(FUNCTION), WRAPPER, \\
	 DOC, 42}
	#define BINSLOT(NAME, SLOT, FUNCTION, DOC) \\
	ETSLOT(NAME, as_number.SLOT, FUNCTION, wrap_binaryfunc_l, \\
			"x." NAME "(y) <==> x" DOC "y")
	static slotdef slotdefs[] = {
		BINSLOT("__add__", nb_add, slot_nb_add, "+"),
		{0}
	};
	int f() {
		return slotdefs[0].flags;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 42


def test_interpret_py_init_slots_array_simple():
	state = parse("""
	typedef int PyObject;
	typedef PyObject * (*binaryfunc)(PyObject *, PyObject *);
	typedef struct {
		binaryfunc nb_add;
	} PyNumberMethods;
	typedef struct _heaptypeobject {
		PyNumberMethods as_number;
	} PyHeapTypeObject;
	typedef struct {
		char *name;
		int offset;
		int flags;
	} slotdef;
	#define offsetof(type, member) ( (int) & ((type*)0) -> member )
	static slotdef slotdefs[] = {
		{"__add__", offsetof(PyHeapTypeObject, as_number.nb_add), 42},
		{0}
	};
	int f() {
		return slotdefs[0].flags;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 42


def test_interpret_offsetof():
	state = parse("""
	typedef int PyObject;
	typedef PyObject * (*binaryfunc)(PyObject *, PyObject *);
	typedef struct {
		long placeholder;
		binaryfunc nb_add;
	} PyNumberMethods;
	#define offsetof(type, member) ( (int) & ((type*)0) -> member )
	int f() {
		int offset = offsetof(PyNumberMethods, nb_add);
		return offset;
    }
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == ctypes.sizeof(ctypes.c_long)


def test_interpret_offsetof_substruct():
	state = parse("""
	typedef int PyObject;
	typedef PyObject * (*binaryfunc)(PyObject *, PyObject *);
	typedef struct {
		long placeholder;
		binaryfunc nb_add;
	} PyNumberMethods;
	typedef struct _heaptypeobject {
		PyNumberMethods as_number;
	} PyHeapTypeObject;
	#define offsetof(type, member) ( (int) & ((type*)0) -> member )
	int f() {
		int offset = offsetof(PyHeapTypeObject, as_number.nb_add);
		return offset;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == ctypes.sizeof(ctypes.c_long)


def test_interpret_offsetof_subsubstruct():
	state = parse("""
	typedef struct {
		long placeholder;
		long here;
	} SubSubStruct;
	typedef struct {
		long placeholder;
		SubSubStruct sub;
	} SubStruct;
	typedef struct {
		SubStruct sub;
	} BaseStruct;
	#define offsetof(type, member) ( (int) & ((type*)0) -> member )
	int f() {
		int offset = offsetof(BaseStruct, sub.sub.here);
		return offset;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == ctypes.sizeof(ctypes.c_long) * 2


def test_interpret_ptr_with_offset_in_array():
	state = parse("""
	typedef struct PyHeapTypeObject {
		long a, b;
	} PyHeapTypeObject;
	typedef struct slotdef {
		char *name;
		int offset;
		int flags;
	} slotdef;
	#define offsetof(type, member) ( (int) & ((type*)0) -> member )
	static slotdef slotdefs[] = {
		{"a", offsetof(PyHeapTypeObject, a), 1},
		{"b", offsetof(PyHeapTypeObject, b), 2},
		{0}
	};
	int f() {
		slotdef *p;
		for (p = slotdefs; p->name; p++) {
			if(p[1].name && p->offset > p[1].offset)
				return -1;
		}
		return slotdefs[1].offset;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == ctypes.sizeof(ctypes.c_long)


def test_interpret_func_ptr_ternary():
	state = parse("""
	typedef int (*func)(int);
	static int g(int x) { return x + 1; }
	int f() {
		func fp = 1 ? g : 0;
		if(!fp)
			return -1;
		return (*fp)(4);
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 5


def test_interpret_ternary_void_p_and_int_p():
	state = parse("""
	int f() {
		int x = 5;
		int* xp = 1 ? &x : ((void*)0);
		return *xp;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 5


def test_interpret_if_if_else_hanging():
	state = parse("""
	int f() {
		int a = 1, b = 2, c = 3, x = -5;
		if (a == 2) {
			x = 1;
			if (b == 2)
				return -1;
		}
		else {
			x = 2;
			if (c == 2) {
				return -2;
			}
		}
		return x;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 2


def test_interpret_func_ptr_call_with_check():
	state = parse("""
	#define NULL 0
	typedef struct _obj {
		struct _type* ob_type;
	} PyObject;
	typedef long (*hashfunc)(PyObject *);
	typedef struct _type {
	    hashfunc tp_hash;
	} PyTypeObject;
	long PyObject_Hash(PyObject *v) {
		PyTypeObject *tp = v->ob_type;
		if (tp->tp_hash != NULL)
			return (*tp->tp_hash)(v);
		return -10;
	}
	static long hash1(PyObject*) { return 1; }
	int f() {
		PyTypeObject t1 = { hash1 };
		PyObject o1 = { &t1 };
		int x1 = PyObject_Hash(&o1);
		PyTypeObject t2 = { NULL };
		PyObject o2 = { &t2 };
		int x2 = PyObject_Hash(&o2);
		return x1 - x2;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("PyObject_Hash", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 11


def test_interpret_func_ptr_via_created_obj():
	state = parse("""
	#include <stdlib.h>
	#include <assert.h>
	typedef struct _obj {
		int dummy;
	} PyObject;
	typedef long (*hashfunc)(PyObject *);
	typedef struct _type {
		PyObject base;
	    hashfunc tp_hash;
	} PyTypeObject;
	static long hash1(PyObject*);
	static long hash2(PyObject*) { return -5; }
	PyObject* new_type() {
		PyObject* obj = (PyObject*) malloc(sizeof(PyTypeObject));
		PyTypeObject* tobj = (PyTypeObject*) obj;
		tobj->tp_hash = 0;
		assert(tobj->tp_hash == 0);
		tobj->tp_hash = hash1;
		PyTypeObject dummy = {{}, hash1};
		assert(dummy.tp_hash != 0);
		assert(dummy.tp_hash == hash1);
		assert(dummy.tp_hash != hash2);
		assert(tobj->tp_hash != 0);
		assert(tobj->tp_hash == dummy.tp_hash);
		return obj;
	}
	static long hash1(PyObject*) { return 42; }
	int f() {
		PyObject* obj = new_type();
		PyTypeObject* tobj = (PyTypeObject*) obj;
		int x = tobj->tp_hash(0);
		free(obj);
		return x;
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("new_type", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 42


def test_interpret_local_obj_bracy_init_func_ptr():
	state = parse("""
	#include <assert.h>
	typedef int (*hashfunc)(int);
	typedef struct _obj {
		hashfunc v;
	} PyObject;
	static int hash1(int) { return 42; }
	static int hash2(int) { return 43; }
	int f() {
		PyObject obj = {hash1};
		assert(obj.v != 0);
		assert(obj.v == hash1);
		assert(obj.v != hash2);
		int x = obj.v(13);
		obj.v = 0;
		assert(obj.v == 0);
		obj.v = hash2;
		assert(obj.v == hash2);
		return x;
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 42


def test_interpret_func_ptr_bracy_init():
	state = parse("""
	#include <assert.h>
	typedef long (*hashfunc)(long);
	typedef struct _type {
	    hashfunc tp_hash;
	} PyTypeObject;
	static long hash1(long) { return 42; }
	static long hash2(long) { return -5; }
	int f() {
		hashfunc h;
		h = hash1;
		PyTypeObject dummy = {hash1};
		assert(dummy.tp_hash != 0);
		assert(dummy.tp_hash == hash1);
		assert(dummy.tp_hash != hash2);
		return dummy.tp_hash(13);
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 42


def test_interpret_array_access_ptr_heap():
	state = parse("""
	#include <stdio.h>
	#include <stdlib.h>
	#include <string.h>
	#include <assert.h>
	typedef struct _object { int v; } PyObject;
	typedef long Py_ssize_t;
	typedef struct _dictentry {
		Py_ssize_t me_hash;
		PyObject *me_key;
		PyObject *me_value;
	} PyDictEntry;
	#define PyDict_MINSIZE 8
	typedef struct _dictobject PyDictObject;
	struct _dictobject {
		PyObject base;
		Py_ssize_t ma_mask;
		PyDictEntry *ma_table;
		PyDictEntry *(*ma_lookup)(PyDictObject *mp, PyObject *key, long hash);
		PyDictEntry ma_smalltable[PyDict_MINSIZE];
	};
	static int _iwashere = 0;
	static PyDictEntry *
	lookdict_string(PyDictObject *mp, PyObject *key, register long hash) {
		register size_t i;
		register size_t mask = (size_t)mp->ma_mask;
		PyDictEntry *ep0 = mp->ma_table;
		register PyDictEntry *ep;

		i = hash & mask;
		ep = &ep0[i];
		_iwashere = 1;
		if (ep->me_key == NULL || ep->me_key == key)
			return ep;
		return 0;
	}
	typedef union _gc_head {
		struct {
			union _gc_head *gc_next;
			union _gc_head *gc_prev;
			Py_ssize_t gc_refs;
		} gc;
		long double dummy;  /* force worst-case alignment */
	} PyGC_Head;
	#define AS_GC(o) ((PyGC_Head *)(o)-1)
	#define FROM_GC(g) ((PyObject *)(((PyGC_Head *)g)+1))
	PyObject* _PyObject_GC_Malloc(size_t basicsize) {
		PyObject *op;
		PyGC_Head *g;
		g = (PyGC_Head *)malloc(sizeof(PyGC_Head) + basicsize);
		memset(g, 0, sizeof(PyGC_Head));
		g->gc.gc_refs = -1;
		op = FROM_GC(g);
		return op;
	}
	void PyObject_GC_Del(void *op) {
		PyGC_Head *g = AS_GC(op);
		free(g);
	}
	#define INIT_NONZERO_DICT_SLOTS(mp) do {  \\
		(mp)->ma_table = (mp)->ma_smalltable; \\
		(mp)->ma_mask = PyDict_MINSIZE - 1;   \\
		} while(0)
	static PyObject* dict_new() {
		PyObject *self;
		self = (PyObject*) _PyObject_GC_Malloc(sizeof(PyDictObject));
		memset(self, 0, sizeof(PyDictObject));
		PyDictObject *d = (PyDictObject *)self;
		assert(d->ma_table == NULL);
		INIT_NONZERO_DICT_SLOTS(d);
		d->ma_lookup = lookdict_string;
		return self;
	}
	int f() {
		PyDictObject* d = (PyDictObject*) dict_new();
		PyObject key_stack;
		PyDictEntry* entry = d->ma_lookup(d, &key_stack, 13);
		assert(_iwashere);
		assert(entry);
		PyObject_GC_Del(d);
		return 42;
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("dict_new", output=sys.stdout)
	interpreter.dumpFunc("lookdict_string", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 42


def test_interpret_for_loop_continue():
	state = parse("""
	int f() {
		int i = 0;
		for (; i < 5; ++i) {
			continue;
		}
		return i;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert r.value == 5


def test_interpret_void_p_p():
	state = parse("""
	static void** slotptr() {
		const char* s = "foo";
		return (void**) s;
	}
	int f() {
		void** p = slotptr();
		return ((const char*) p)[1];
	}
	""")
	print "Parsed:"
	print "slotptr:", state.funcs["slotptr"]
	assert isinstance(state.funcs["slotptr"].body, CBody)
	f_content = state.funcs["slotptr"].body.contentlist
	assert isinstance(f_content[1], CReturnStatement)
	print "slotptr return body:"
	pprint(f_content[1].body)
	assert isinstance(f_content[1].body, CStatement)
	assert isinstance(f_content[1].body._leftexpr, CFuncCall)
	cast_base = f_content[1].body._leftexpr.base
	pprint(cast_base)
	assert isType(cast_base)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("slotptr", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ord('o')


def test_interpret_void_p_p_incr():
	state = parse("""
	static void** slotptr() {
		const char* ptr = "foobar";
		long offset = 1;
		if (ptr != 0)
			ptr += offset;
		return (void**) ptr;
	}
	int f() {
		void** p = slotptr();
		return ((const char*) p)[2];
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("slotptr", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ord('b')


def test_interpret_static_func_ptr_to_void_p():
	state = parse("""
	typedef int (*unaryfunc)(int);
	typedef struct _typeobj {
		unaryfunc tp_repr;
	} PyTypeObject;
	static int type_repr(int x) { return x; }
	static void look(void* wrapper) {
		void* w;
		w = wrapper;
	}
	int f() {
		PyTypeObject my_type = {type_repr};
		look((void*) my_type.tp_repr);
		return 42;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("look", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_func_to_void_p():
	state = parse("""
	static int* type_repr(int x) { return x; }
	static void look(void* wrapper) {
		void* w;
		w = wrapper;
	}
	int f() {
		look((void*) type_repr);
		return 42;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("look", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_func_addr_to_void_p():
	state = parse("""
	static int* type_repr(int x) { return x; }
	static void look(void* wrapper) {
		void* w;
		w = wrapper;
	}
	int f() {
		look((void*) &type_repr);
		return 42;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("look", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_func_call_pass_array():
	state = parse("""
	typedef struct PyMethodDef {
		char* name;
	} PyMethodDef;
	typedef int PyObject;
	static PyObject* PyCFunction_New(PyMethodDef*) { return 0; }
	static struct PyMethodDef tp_new_methoddef[] = {
		{"__new__"},
		{0}
	};
	int f() {
		PyObject *func;
		func = PyCFunction_New(tp_new_methoddef);
		if (func == 0)
			return 13;
		return -1;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 13


def test_interpret_struct_same_name_as_typedef():
	state = parse("""
	typedef struct PyMethodDef {
		char* ml_name;
	} PyMethodDef;
	int f() {
		PyMethodDef m = {"foo"};
	    struct PyMethodDef* mp = &m;
		return mp->ml_name[1];
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ord('o')


def test_interpret_struct_same_name_as_typedef_2():
	state = parse("""
	typedef struct PyMethodDef {
		char* ml_name;
	} PyMethodDef;
	int f() {
	    struct PyMethodDef m = {"foo"};
		return m.ml_name[1];
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ord('o')


def test_interpret_func_ptr_in_static_array():
	state = parse("""
	typedef struct _methdef {
		char* ml_name;
	} PyMethodDef;
	typedef struct _typeobj {
		char* name;
	    PyMethodDef *tp_methods;
	} PyTypeObject;
	static PyMethodDef object_methods[] = {
		{"__reduce_ex__"},
		{"__reduce__"},
		{0}
	};
	PyTypeObject PyBaseObject_Type = {
		"foo",
    	object_methods /* tp_methods */
	};
	typedef int PyObject;
	PyObject* PyDescr_NewMethod(PyTypeObject *type, PyMethodDef *method) {
		PyMethodDef* m;
		m = method;
		return 0;
	}
	static int add_methods(PyTypeObject *type, PyMethodDef *meth) {
		for (; meth->ml_name != 0; meth++) {
			PyObject *descr;
			descr = PyDescr_NewMethod(type, meth);
		}
		return 0;
	}
	int f() {
		add_methods(&PyBaseObject_Type, PyBaseObject_Type.tp_methods);
		return 42;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("add_methods", output=sys.stdout)
	interpreter.dumpFunc("PyDescr_NewMethod", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_sys_types_h():
	state = parse("""
	#include <sys/types.h>
	int f() {
		size_t x = 42;
		return (int) x;
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_local_func_ptr_type():
	state = parse("""
	typedef int PyObject;
	PyObject* g(PyObject* x) { return x; }
	int f() {
	    PyObject *(*fp)(PyObject *);
	    fp = g;
	    PyObject x = 42;
	    PyObject* y = fp(&x);
		return *y;
	}
	""")
	pprint(state.funcs["f"].body.contentlist[0])
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_struct_return():
	state = parse("""
	typedef struct _complex {
		int real;
		int imag;
	} Py_complex;
	Py_complex c_sum(Py_complex a, Py_complex b) {
		Py_complex r;
		r.real = a.real + b.real;
		r.imag = a.imag + b.imag;
		return r;
	}
	int f() {
		Py_complex s;
		Py_complex a = {1, 2};
		Py_complex b = {3, 5};
		s = c_sum(a, b);
		return s.real + s.imag;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 11


def test_interpret_struct_init_assign():
	state = parse("""
	#include <assert.h>
	typedef struct _complex {
		int real;
		int imag;
	} Py_complex;
	typedef struct _A {
		int x;
		Py_complex a;
		Py_complex b;
	} A;
	int f() {
		Py_complex z = {1, 2};
		A o1 = {1, {2, 3}, z};
		assert(o1.x == 1);
		assert(o1.a.real == 2);
		assert(o1.b.imag == 2);
		A o2; o2 = o1;
		assert(o2.x == 1);
		assert(o2.a.real == 2);
		assert(o2.b.imag == 2);
		A o3 = o2;
		assert(o3.x == 1);
		assert(o3.a.real == 2);
		assert(o3.b.imag == 2);
		return o3.x + o3.b.imag + o2.x + o2.a.real + o1.b.real;
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 7


def test_interpret_var_args_noop():
	state = parse("""
	#include <stdarg.h>
	typedef int PyObject;
	PyObject* PyErr_Format(PyObject *exception, const char *format, ...) {
		va_list vargs;
		PyObject* string;
		va_start(vargs, format);
		va_end(vargs);
		return 0;
	}
	int f() {
		PyErr_Format(0, "foo%i%i%s", 1, 2, "bar");
		return 7;
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("PyErr_Format", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 7


def test_interpret_var_args_vsprintf():
	state = parse("""
	#include <stdarg.h>
	#include <stdio.h>
	#include <assert.h>
	#include <string.h>
	typedef int PyObject;
	char buffer[100];
	void g(const char *format, ...) {
		va_list vargs;
		va_start(vargs, format);
		vsprintf(buffer, format, vargs);
		va_end(vargs);
	}
	int f() {
		g("foo%i%i%s", 1, 2, "bar");
		assert(strcmp(buffer, "foo12bar") == 0);
		return (int) buffer[4];
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("g", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == ord('2')


def test_interpret_var_args_va_list_param():
	state = parse("""
	#include <stdarg.h>
	void h(va_list) {}
	void g(const char* format, ...) {
		va_list vargs;
		va_start(vargs, format);
		h(vargs);
		va_end(vargs);
	}
	int f() {
		g("foo");
		return 42;
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("g", output=sys.stdout)
	interpreter.dumpFunc("h", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_goto_named_func():
	state = parse("""
	int g() { return 42; }
	int f() {
		int a;
		a = g();
		goto g;
		a = 13;
	g:
		return a;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("g", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_enum_return():
	state = parse("""
	typedef enum {PyGILState_LOCKED, PyGILState_UNLOCKED} PyGILState_STATE;
	PyGILState_STATE PyGILState_Ensure(void) { return PyGILState_UNLOCKED; }
	int f() {
		return PyGILState_Ensure();
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("PyGILState_Ensure", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 1


def test_interpret_enum_cast():
	state = parse("""
	enum why_code {A, B, C};
	int f() {
		enum why_code why;
		why = (enum why_code) 2;
		return why;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 2


def test_interpret_enum_stmnt_bitor():
	state = parse("""
	enum why_code {A=1, B=2, C=4};
	int f() {
		enum why_code why = A;
		if (why & (A | B))
			return 42;
		return -1;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_attrib_access_after_cast_in_iif():
	state = parse("""
	struct _typeobj;
	typedef struct _obj { struct _typeobj* ob_type; } PyObject;
	typedef struct _typeobj { PyObject base; } PyTypeObject;
	typedef struct _instobj { PyObject base; PyObject* in_class; } PyInstanceObject;
	int f() {
		PyInstanceObject a;
		PyObject *x = &a, *b;
		b = 1
		  ? (PyObject*)((PyInstanceObject*)(x))->in_class
		  : (PyObject*)((x)->ob_type);
		return 3;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 3


def test_interpret_attrib_access_after_cast_simple():
	state = parse("""
	typedef struct _obj { int v; } PyObject;
	typedef struct _instobj { PyObject base; PyObject* in_class; } PyInstanceObject;
	int f() {
		PyInstanceObject _a;
		PyInstanceObject *a = &_a;
		PyObject *b;
		b = (PyObject*) (a)->in_class;
		return 3;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 3


def test_interpret_cast_precedence_over_op():
	state = parse("""
	typedef unsigned char uchar;
	int f() {
		uchar a = 240, b = 240;
		return (int) a + b;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 480


def test_interpret_struct_ptr_to_itself_indirect():
	state = parse("""
	struct B;
	struct A { struct B* x; };
	struct B { struct A  x; };
	int f() {
		struct A a;
		struct B b;
		return 3;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 3


def test_interpret_struct_ptr_to_itself_indirect2():
	state = parse("""
	struct C;
	struct B { struct C* x; };
	struct A { struct B  x; };
	struct C { struct A  x; };
	int f() {
		struct A a;
		struct B b;
		struct C c;
		return 3;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 3


def test_interpret_struct_with_itself_indirect_error():
	state = parse("""
	struct B; typedef struct B B;
	struct A { B x; };
	struct B { struct A x; };
	int f() {
		struct A a;
		return 3;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	try:
		interpreter.dumpFunc("f", output=sys.stdout)
	except RecursiveStructConstruction as e:
		print repr(e)
		pass  # ok, we expect that
	else:
		assert False, "Not expected, no error!"


def test_interpret_py_atexit():
	state = parse("""
	#define NEXITFUNCS 32
	static void (*exitfuncs[NEXITFUNCS])(void);
	static int nexitfuncs = 0;
	int Py_AtExit(void (*func)(void)) {
		if (nexitfuncs >= NEXITFUNCS)
			return -1;
		exitfuncs[nexitfuncs++] = func;
		return 0;
	}
	static void call_ll_exitfuncs(void) {
		while (nexitfuncs > 0)
			(*exitfuncs[--nexitfuncs])();
	}
	static int iwashere = -1;
	static void g() { iwashere = 42; }
	int f() {
		Py_AtExit(g);
		call_ll_exitfuncs();
		return iwashere;
	}
	""")
	print state.vars["exitfuncs"]
	print state.vars["exitfuncs"].type
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("Py_AtExit", output=sys.stdout)
	interpreter.dumpFunc("call_ll_exitfuncs", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 42


def test_interpret_local_typedef_var():
	state = parse("""
	int f() {
		typedef int Int;
		Int x = 43;
		return x;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 43


def test_interpret_func_ptr_local_typedef_va_arg():
	state = parse("""
	#include <stdarg.h>
	typedef int PyObject;
	PyObject* p(void* a) { return (PyObject*) a; }
	PyObject* h(va_list *p_va) {
		typedef PyObject *(*converter)(void *);
		converter func = va_arg(*p_va, converter);
		void *arg = va_arg(*p_va, void *);
		return (*func)(arg);
	}
	int g(int x, ...) {
		va_list vargs;
		va_start(vargs, x);
		PyObject* r_p;
		r_p = h(&vargs);
		int r = *r_p;
		va_end(vargs);
		return r + x;
	}
	int f() {
		int x = 43;
		return g(13, p, &x) + 1;
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("g", output=sys.stdout)
	interpreter.dumpFunc("h", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 1 + 13 + 43


def test_interpret_va_arg_custom():
	state = parse("""
	#include <stdarg.h>
	#include <string.h>
	int g(const char* format, ...) {
		int res = 0;
		va_list vargs;
		va_start(vargs, format);
		char c;
		for(; c = *format; ++format) {
			switch(c) {
			case 'c': res += va_arg(vargs, char); break;
			case 'i': res += va_arg(vargs, int); break;
			case 'l': res += va_arg(vargs, long); break;
			case 's': res += strlen(va_arg(vargs, char*)); break;
			default: return -1;
			}
		}
		va_end(vargs);
		return res;
	}
	int f() {
		return g("iscl", 13, "foo", 'A', 11);
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("g", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 13 + len("foo") + ord('A') + 11


def test_interpret_va_arg_copy():
	state = parse("""
	#include <stdarg.h>
	static int va_build_value(const char *format, va_list va) {
		va_list lva;
	#ifdef VA_LIST_IS_ARRAY
		memcpy(lva, va, sizeof(va_list));
	#else
	#ifdef __va_copy
		__va_copy(lva, va);
	#else
		lva = va;
	#endif
	#endif
		return va_arg(lva, int) + va_arg(lva, int);
	}
	int g(const char* format, ...) {
		va_list vargs;
		va_start(vargs, format);
		int r = va_build_value(format, vargs);
		va_end(vargs);
		return r;
	}
	int f() {
		return g("iscl", 13, 11);
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("g", output=sys.stdout)
	interpreter.dumpFunc("va_build_value", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 13 + 11


def test_interpret_assign_func_ptr():
	state = parse("""
	typedef int PyObject;
	PyObject* p(void* a) { return (PyObject*) a; }
	int f() {
		int r = 0;
		typedef PyObject *(*converter)(void *);
		int x = 1;
		converter func = p;
		r += *func(&x);
		converter func2 = func;
		r += *func2(&x);
		func = func2;
		r += *func(&x);
		return r;
	}
	""")
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 3


def test_interpret_sig_handler():
	state = parse("""
	#include <signal.h>
	typedef void (*PyOS_sighandler_t)(int);
	PyOS_sighandler_t PyOS_getsig(int sig) {
		PyOS_sighandler_t handler;
		handler = signal(sig, SIG_IGN);
		if (handler != SIG_ERR)
			signal(sig, handler);
		return handler;
	}
	int f() {
		PyOS_getsig(SIGINT);
		return 3;
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("PyOS_getsig", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 3


def test_interpret_locale_include():
	state = parse("""
	#include <locale.h>
	int f() { return 3; }
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 3


def test_interpret_fcntl_open_close():
	state = parse("""
	#include <fcntl.h>
	typedef long Py_ssize_t;
	static void dev_urandom_noraise() {
		int fd;
		fd = open("/dev/urandom", O_RDONLY);
		close(fd);
	}
	int f() {
		dev_urandom_noraise();
		return 3;
	}
	""", withGlobalIncludeWrappers=True)
	interpreter = Interpreter()
	interpreter.register(state)
	print "Func dump:"
	interpreter.dumpFunc("f", output=sys.stdout)
	interpreter.dumpFunc("dev_urandom_noraise", output=sys.stdout)
	print "Run f:"
	r = interpreter.runFunc("f")
	print "result:", r
	assert isinstance(r, ctypes.c_int)
	assert r.value == 3
