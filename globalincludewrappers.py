# PyCParser - global include wrappers
# by Albert Zeyer, 2011
# code under LGPL

from cparser import *
from interpreter import CWrapValue
import ctypes, _ctypes
import errno, os

def _fixCType(t, wrap=False):
	if t is ctypes.c_char_p: t = ctypes.POINTER(ctypes.c_byte)
	if t is ctypes.c_char: t = ctypes.c_byte
	if wrap: return wrapCTypeClassIfNeeded(t)
	return t

def wrapCFunc(state, funcname, restype=None, argtypes=None):
	f = getattr(ctypes.pythonapi, funcname)
	if restype is None: restype = ctypes.c_int
	if restype is CVoidType:
		f.restype = None
	elif restype is not None:
		f.restype = restype = _fixCType(restype, wrap=True)
	if argtypes is not None:
		f.argtypes = map(_fixCType, argtypes)
	state.funcs[funcname] = CWrapValue(f, funcname=funcname, returnType=restype)

def _fixCArg(a):
	if isinstance(a, unicode):
		a = a.encode("utf-8")
	if isinstance(a, str):
		a = ctypes.c_char_p(a)
	if isinstance(a, ctypes.c_char_p) or (isinstance(a, _ctypes._Pointer) and a._type_ is ctypes.c_char):
		return ctypes.cast(a, ctypes.POINTER(ctypes.c_byte))
	if isinstance(a, ctypes.c_char):
		return ctypes.c_byte(ord(a.value))
	return a

def callCFunc(funcname, *args):
	f = getattr(ctypes.pythonapi, funcname)
	args = map(_fixCArg, args)
	return f(*args)

class Wrapper:
	def handle_limits_h(self, state):
		state.macros["UCHAR_MAX"] = Macro(rightside="255")
		state.macros["INT_MAX"] = Macro(rightside=str(2 ** (ctypes.sizeof(ctypes.c_int) * 8 - 1)))
	def handle_stdio_h(self, state):
		state.macros["NULL"] = Macro(rightside="0")
		wrapCFunc(state, "printf", restype=ctypes.c_int, argtypes=(ctypes.c_char_p,))
		FileP = CPointerType(CStdIntType("FILE")).getCType(state)
		wrapCFunc(state, "fopen", restype=FileP, argtypes=(ctypes.c_char_p, ctypes.c_char_p))
		wrapCFunc(state, "fclose", restype=ctypes.c_int, argtypes=(FileP,))
		wrapCFunc(state, "fdopen", restype=FileP, argtypes=(ctypes.c_int, ctypes.c_char_p))
		state.vars["stdin"] = CWrapValue(callCFunc("fdopen", 0, "r"))
		state.vars["stdout"] = CWrapValue(callCFunc("fdopen", 1, "a"))
		state.vars["stderr"] = CWrapValue(callCFunc("fdopen", 2, "a"))
		wrapCFunc(state, "fprintf", restype=ctypes.c_int, argtypes=(FileP, ctypes.c_char_p))
		wrapCFunc(state, "fputs", restype=ctypes.c_int, argtypes=(ctypes.c_char_p, FileP))
		wrapCFunc(state, "fgets", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p, ctypes.c_int, FileP))
		wrapCFunc(state, "fflush", restype=ctypes.c_int, argtypes=(FileP,))
		state.vars["errno"] = CWrapValue(0) # TODO
		state.macros["EOF"] = Macro(rightside="-1") # TODO?
		wrapCFunc(state, "setbuf", restype=CVoidType, argtypes=(FileP, ctypes.c_char_p))
		wrapCFunc(state, "isatty", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
		wrapCFunc(state, "fileno")
		wrapCFunc(state, "getc")
		wrapCFunc(state, "ungetc", restype=ctypes.c_int, argtypes=(ctypes.c_int,FileP))
		struct_stat = state.structs["stat"] = CStruct(name="stat") # TODO
		struct_stat.body = CBody(parent=struct_stat)
		CVarDecl(parent=struct_stat, name="st_mode", type=ctypes.c_int).finalize(state)
		state.funcs["fstat"] = CWrapValue(lambda *args: None, returnType=CVoidType()) # TODO
		state.macros["S_IFMT"] = Macro(rightside="0") # TODO
		state.macros["S_IFDIR"] = Macro(rightside="0") # TODO
	def handle_stdlib_h(self, state):
		wrapCFunc(state, "abort", restype=CVoidType, argtypes=())
		wrapCFunc(state, "malloc", restype=ctypes.c_void_p, argtypes=(ctypes.c_size_t,))
		wrapCFunc(state, "free", restype=CVoidType, argtypes=(ctypes.c_void_p,))
		state.funcs["atoi"] = CWrapValue(
			lambda x: ctypes.c_int(int(ctypes.cast(x, ctypes.c_char_p).value)),
			returnType=ctypes.c_int
		)
		state.funcs["getenv"] = CWrapValue(
			lambda x: _fixCArg(ctypes.c_char_p(os.getenv(ctypes.cast(x, ctypes.c_char_p).value))),
			returnType=CPointerType(ctypes.c_byte)
		)
	def handle_stdarg_h(self, state): pass
	def handle_stddef_h(self, state): pass
	def handle_math_h(self, state): pass
	def handle_string_h(self, state):
		wrapCFunc(state, "strlen", restype=ctypes.c_size_t, argtypes=(ctypes.c_char_p,))
		wrapCFunc(state, "strcpy", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
		wrapCFunc(state, "strcat", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
		wrapCFunc(state, "strcmp", restype=ctypes.c_int, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
		wrapCFunc(state, "strtok", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
		wrapCFunc(state, "strchr", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_int))
		wrapCFunc(state, "strstr", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
		wrapCFunc(state, "strdup", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,))
		wrapCFunc(state, "strerror", restype=ctypes.c_char_p, argtypes=(ctypes.c_int,))
	def handle_time_h(self, state): pass
	def handle_ctype_h(self, state): pass
	def handle_wctype_h(self, state): pass
	def handle_assert_h(self, state): pass
	def handle_signal_h(self, state):
		wrapCFunc(state, "signal")
		state.macros["SIGINT"] = Macro(rightside="2")
		state.macros["SIG_DFL"] = Macro(rightside="(void (*)(int))0")
		
	def find_handler_func(self, filename):
		funcname = "handle_" + filename.replace("/", "__").replace(".", "_")
		return getattr(self, funcname, None)
		
	def readGlobalInclude(self, state, oldFunc, filename):
		f = self.find_handler_func(filename)
		if f is not None:
			def reader():
				f(state)
				return
				yield None # to make it a generator
			return reader(), None
		return oldFunc(filename) # fallback
	
	def install(self, state):
		oldFunc = state.readGlobalInclude
		state.readGlobalInclude = lambda fn: self.readGlobalInclude(state, oldFunc, fn)
		