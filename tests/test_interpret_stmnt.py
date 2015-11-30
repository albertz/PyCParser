
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
	state = parse("void f()\n { int* v = (int*) 42; } \n")
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
	state = parse("void f()\n { void* v = (void*) 42; } \n")
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
		g((int*) 42);
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


def test_interpret_c_cast_ptr_4():
	state = parse("""
	int g(unsigned char * buff) { return 3; }
	int f() {
		g((unsigned char *) 42);
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
	int g() {}
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


def test_interpreter_func_ptr_return_ptr():
	state = parse("""
	typedef int* (*F) (int*);
	int* i(int* v) { return v; }
	int f() {
		F fp = i;
		int v = 42;
		int* vp = fp(&v);
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
