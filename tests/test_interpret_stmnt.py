
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


def test_interpreter_offset_of():
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

