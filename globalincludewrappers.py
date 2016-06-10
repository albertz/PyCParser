# PyCParser - global include wrappers
# by Albert Zeyer, 2011
# code under BSD 2-Clause License

from cparser import *
from interpreter import CWrapValue, _ctype_ptr_get_value, Helpers
import ctypes, _ctypes
import errno, os

libc = ctypes.CDLL(None)

def _fixCType(stateStruct, t):
	if t is ctypes.c_void_p: t = CBuiltinType(("void", "*"))
	if t is ctypes.c_char_p: t = CPointerType(CBuiltinType(("char",)))
	if t is ctypes.c_char: t = CBuiltinType(("char",))
	return t

def wrapCFunc(state, funcname, restype, argtypes, varargs=False):
	f = getattr(libc, funcname)
	restype = _fixCType(state, restype)
	if restype is CVoidType:
		f.restype = None
	else:
		assert restype is not None
		f.restype = getCTypeWrapped(restype, state)
	assert argtypes is not None
	argtypes = [_fixCType(state, arg) for arg in argtypes]
	f.argtypes = [getCTypeWrapped(arg, state) for arg in argtypes]
	state.funcs[funcname] = CWrapValue(
		f, name=funcname, funcname=funcname,
		returnType=restype, argTypes=argtypes)

def wrapCFunc_varargs(state, funcname, wrap_funcname):
	"""
	:param str funcname: e.g. "vprintf"
	:param wrap_funcname: e.g. "printf"
	Will register a new function, where the last arg is expected to be va_list.
	va_list is just a tuple of args.
	Will call the wrap-func with all args and unwraps the va_list args.
	"""
	wrap_func = state.funcs[wrap_funcname]
	assert isinstance(wrap_func, CWrapValue)
	wrap_arg_len = len(wrap_func.value.argtypes)
	def f(*args):
		assert len(args) == wrap_arg_len + 1
		assert isinstance(args[-1], Helpers.VarArgs)
		return wrap_func.value(*(args[:-1] + args[-1].args))
	f.__name__ = funcname
	state.funcs[funcname] = CWrapValue(
		f, name=funcname, funcname=funcname,
		returnType=wrap_func.returnType, argTypes=wrap_func.argTypes)

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
	f = getattr(libc, funcname)
	args = map(_fixCArg, args)
	return f(*args)


class Wrapper:
	def __init__(self, state):
		"""
		:type state: cparser.State
		"""
		self.state = state
		# The Wrapper is supposed to work for parsing also without an interpreter.
		# However, when you are going to call some of the functions from here,
		# this is needed.
		self.interpreter = None

	def handle_limits_h(self, state):
		state.macros["UCHAR_MAX"] = Macro(rightside="255")
		state.macros["INT_MAX"] = Macro(rightside=str(2 ** (ctypes.sizeof(ctypes.c_int) * 8 - 1)))
		state.macros["ULONG_MAX"] = Macro(rightside=str(2 ** (ctypes.sizeof(ctypes.c_ulong) * 8) - 1))
	def handle_stdio_h(self, state):
		state.macros["NULL"] = Macro(rightside="0")
		FileP = CPointerType(CStdIntType("FILE")).getCType(state)
		wrapCFunc(state, "fopen", restype=FileP, argtypes=(ctypes.c_char_p, ctypes.c_char_p))
		wrapCFunc(state, "fclose", restype=ctypes.c_int, argtypes=(FileP,))
		wrapCFunc(state, "fdopen", restype=FileP, argtypes=(ctypes.c_int, ctypes.c_char_p))
		state.vars["stdin"] = CWrapValue(callCFunc("fdopen", 0, "r"), name="stdin")
		state.vars["stdout"] = CWrapValue(callCFunc("fdopen", 1, "a"), name="stdout")
		state.vars["stderr"] = CWrapValue(callCFunc("fdopen", 2, "a"), name="stderr")
		wrapCFunc(state, "printf", restype=ctypes.c_int, argtypes=(ctypes.c_char_p,), varargs=True)
		wrapCFunc(state, "fprintf", restype=ctypes.c_int, argtypes=(FileP, ctypes.c_char_p), varargs=True)
		wrapCFunc(state, "sprintf", restype=ctypes.c_int, argtypes=(ctypes.c_char_p, ctypes.c_char_p), varargs=True)
		wrapCFunc_varargs(state, "vprintf", wrap_funcname="printf")
		wrapCFunc_varargs(state, "vfprintf", wrap_funcname="fprintf")
		wrapCFunc_varargs(state, "vsprintf", wrap_funcname="sprintf")
		wrapCFunc(state, "fputs", restype=ctypes.c_int, argtypes=(ctypes.c_char_p, FileP))
		wrapCFunc(state, "fputc", restype=ctypes.c_int, argtypes=(ctypes.c_int, FileP))
		wrapCFunc(state, "fgets", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p, ctypes.c_int, FileP))
		wrapCFunc(state, "fread", restype=ctypes.c_size_t, argtypes=(ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, FileP))		
		wrapCFunc(state, "fwrite", restype=ctypes.c_size_t, argtypes=(ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, FileP))
		wrapCFunc(state, "fflush", restype=ctypes.c_int, argtypes=(FileP,))
		wrapCFunc(state, "ftell", restype=ctypes.c_long, argtypes=(FileP,))
		wrapCFunc(state, "rewind", restype=CVoidType, argtypes=(FileP,))
		wrapCFunc(state, "ferror", restype=ctypes.c_int, argtypes=(FileP,))
		wrapCFunc(state, "clearerr", restype=CVoidType, argtypes=(FileP,))
		state.vars["errno"] = CWrapValue(0, name="errno") # TODO
		state.macros["EOF"] = Macro(rightside="-1") # TODO?
		wrapCFunc(state, "setbuf", restype=CVoidType, argtypes=(FileP, ctypes.c_char_p))
		wrapCFunc(state, "isatty", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
		wrapCFunc(state, "fileno", restype=ctypes.c_int, argtypes=(FileP,))
		wrapCFunc(state, "getc", restype=ctypes.c_int, argtypes=(FileP,))
		wrapCFunc(state, "ungetc", restype=ctypes.c_int, argtypes=(ctypes.c_int,FileP))
		struct_stat = state.structs["stat"] = CStruct(name="stat") # TODO
		struct_stat.body = CBody(parent=struct_stat)
		CVarDecl(parent=struct_stat, name="st_mode", type=ctypes.c_int).finalize(state)
		state.funcs["fstat"] = CWrapValue(lambda *args: None, returnType=ctypes.c_int, name="fstat") # TODO
		state.macros["S_IFMT"] = Macro(rightside="0") # TODO
		state.macros["S_IFDIR"] = Macro(rightside="0") # TODO
	def handle_stdlib_h(self, state):
		state.macros["EXIT_SUCCESS"] = Macro(rightside="0")
		state.macros["EXIT_FAILURE"] = Macro(rightside="1")
		state.funcs["abort"] = CWrapValue(
			lambda: self.interpreter._abort(),
			returnType=CVoidType,
			name="abort"
		)
		state.funcs["exit"] = CWrapValue(
			lambda s: self.interpreter._exit(s.value),  # int
			returnType=CVoidType,
			name="exit"
		)
		state.funcs["malloc"] = CWrapValue(
			lambda s: self.interpreter._malloc(s.value),  # size_t
			returnType=ctypes.c_void_p,
			name="malloc"
		)
		state.funcs["realloc"] = CWrapValue(
			lambda (p, s): self.interpreter._realloc(_ctype_ptr_get_value(p), s.value),  # void*, size_t
			returnType=ctypes.c_void_p,
			name="realloc"
		)
		state.funcs["free"] = CWrapValue(
			lambda p: self.interpreter._free(_ctype_ptr_get_value(p)),  # void*
			returnType=CVoidType,
			name="free"
		)
		wrapCFunc(state, "strtoul", restype=ctypes.c_ulong, argtypes=(ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p), ctypes.c_int))
		state.funcs["atoi"] = CWrapValue(
			lambda x: ctypes.c_int(int(ctypes.cast(x, ctypes.c_char_p).value)),
			returnType=ctypes.c_int,
			name="atoi"
		)
		state.funcs["getenv"] = CWrapValue(
			lambda x: _fixCArg(ctypes.c_char_p(os.getenv(ctypes.cast(x, ctypes.c_char_p).value))),
			returnType=CPointerType(ctypes.c_byte),
			name="getenv"
		)
	def handle_stdarg_h(self, state):
		state.typedefs["va_list"] = CTypedef(name="va_list", type=CVariadicArgsType())
		def va_start(v, dummy_last):
			assert isinstance(v, Helpers.VarArgs)
			v.idx = 0
		def va_end(v):
			assert isinstance(v, Helpers.VarArgs)
			#assert v.idx == len(v.args), "VarArgs: va_end: not handled all args"  # is this an error?
		def __va_arg(v, inplace_typed):
			assert isinstance(v, Helpers.VarArgs)
			x = v.get_next()
			helpers = v.intp.helpers
			helpers.assignGeneric(inplace_typed, x)
			return inplace_typed
		def __va_arg_getReturnType(stateStruct, stmnt_args):
			assert len(stmnt_args) == 2  # see __va_arg
			return getValueType(stateStruct, stmnt_args[1])
		state.funcs["va_start"] = CWrapValue(va_start, name="va_start", returnType=CVoidType)
		state.funcs["va_end"] = CWrapValue(va_end, name="va_end", returnType=CVoidType)
		state.macros["va_arg"] = Macro(args=("list", "type"), rightside="((__va_arg(list, type())))")
		state.funcs["__va_arg"] = CWrapValue(__va_arg, name="__va_arg",
											 returnType=None, getReturnType=__va_arg_getReturnType)
	def handle_stddef_h(self, state): pass
	def handle_math_h(self, state): pass
	def handle_string_h(self, state):
		wrapCFunc(state, "strlen", restype=ctypes.c_size_t, argtypes=(ctypes.c_char_p,))
		wrapCFunc(state, "strcpy", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
		wrapCFunc(state, "strncpy", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p,ctypes.c_size_t))
		wrapCFunc(state, "strcat", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
		wrapCFunc(state, "strcmp", restype=ctypes.c_int, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
		wrapCFunc(state, "strncmp", restype=ctypes.c_int, argtypes=(ctypes.c_char_p,ctypes.c_char_p,ctypes.c_size_t))
		wrapCFunc(state, "strtok", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
		wrapCFunc(state, "strchr", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_int))
		wrapCFunc(state, "strrchr", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_int))
		wrapCFunc(state, "strstr", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
		wrapCFunc(state, "strdup", restype=ctypes.c_char_p, argtypes=(ctypes.c_char_p,))
		wrapCFunc(state, "strerror", restype=ctypes.c_char_p, argtypes=(ctypes.c_int,))
		wrapCFunc(state, "memset", restype=ctypes.c_void_p, argtypes=(ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t))
		wrapCFunc(state, "memcpy", restype=ctypes.c_void_p, argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t))
		wrapCFunc(state, "memmove", restype=ctypes.c_void_p, argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t))
		wrapCFunc(state, "memchr", restype=ctypes.c_void_p, argtypes=(ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t))
		wrapCFunc(state, "memcmp", restype=ctypes.c_int, argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t))
	def handle_time_h(self, state): pass
	def handle_ctype_h(self, state):
		wrapCFunc(state, "isalpha", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
		wrapCFunc(state, "isalnum", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
		wrapCFunc(state, "isspace", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
		wrapCFunc(state, "isdigit", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
		wrapCFunc(state, "isxdigit", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
		wrapCFunc(state, "islower", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
		wrapCFunc(state, "tolower", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
		wrapCFunc(state, "isupper", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
		wrapCFunc(state, "toupper", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
	def handle_wctype_h(self, state): pass
	def handle_assert_h(self, state):
		def assert_wrap(x):
			if isinstance(x, (ctypes._Pointer, ctypes.Array, ctypes._CFuncPtr)):
				x = ctypes.cast(x, ctypes.c_void_p)
			assert x.value
		state.funcs["assert"] = CWrapValue(assert_wrap, returnType=CVoidType, name="assert")
	def handle_fcntl_h(self, state):
		state.macros["O_RDONLY"] = Macro(rightside="0x0000")
		wrapCFunc(state, "open", restype=ctypes.c_int, argtypes=(ctypes.c_char_p, ctypes.c_int))
		wrapCFunc(state, "read", restype=ctypes.c_int, argtypes=(ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t))  # normally <unistd.h>
		wrapCFunc(state, "close", restype=ctypes.c_int, argtypes=(ctypes.c_int,))  # normally <unistd.h>
		# TODO: these are on OSX. cross-platform? probably not...
		state.macros["EINTR"] = Macro(rightside="4")  # via <sys/errno.h>
		state.macros["ERANGE"] = Macro(rightside="34")  # via <sys/errno.h>
	def handle_signal_h(self, state):
		# typedef void (*sig_t) (int)
		state.typedefs["sig_t"] = CTypedef(
			name="sig_t", type=CFuncPointerDecl(type=CVoidType(), args=[CBuiltinType(("int",))]))
		# There is no safe way to support the native C function.
		# The signal handler can be called at any point and it could be that
		# the GIL is hold. Then the signal handler code deadlocks because it also wants the GIL.
		#wrapCFunc(state, "signal", restype=state.typedefs["sig_t"],
		#		  argtypes=(ctypes.c_int, state.typedefs["sig_t"]))
		def signal(sig, f):
			sig = sig.value
			import signal
			if isinstance(f, CWrapValue):
				f = f.value
			def sig_handler(sig, stack_frame):
				return f(sig)
			if isinstance(f, ctypes._CFuncPtr):
				if _ctype_ptr_get_value(f) == 0:  # place-holder for SIG_DFL
					sig_handler = signal.SIG_DFL
				elif _ctype_ptr_get_value(f) == 1:  # place-holder for SIG_IGN
					sig_handler = signal.SIG_IGN
			old_action = signal.signal(sig, sig_handler)
			# TODO: need to use helpers.makeFuncPtr for old_action.
			# And maybe handle SIG_DFL/SIG_IGN cases?
			return 0  # place-holder for SIG_DFL
		state.funcs["signal"] = CWrapValue(signal, name="signal", returnType=state.typedefs["sig_t"])
		state.macros["SIGINT"] = Macro(rightside="2")
		state.macros["SIG_DFL"] = Macro(rightside="((sig_t)0)")
		state.macros["SIG_IGN"] = Macro(rightside="((sig_t)1)")
		state.macros["SIG_ERR"] = Macro(rightside="((sig_t)-1)")
	def handle_locale_h(self, state):
		struct_lconv = state.structs["lconv"] = CStruct(name="lconv") # TODO
		struct_lconv.body = CBody(parent=struct_lconv)
		CVarDecl(parent=struct_lconv, name="grouping", type=ctypes.c_char_p).finalize(state)
		CVarDecl(parent=struct_lconv, name="thousands_sep", type=ctypes.c_char_p).finalize(state)
		wrapCFunc(state, "localeconv", restype=struct_lconv, argtypes=())
	def handle_sys_types_h(self, state):
		pass  # dummy

	def find_handler_func(self, filename):
		funcname = "handle_" + filename.replace("/", "_").replace(".", "_")
		return getattr(self, funcname, None)

	def readGlobalInclude(self, state, oldFunc, filename):
		f = self.find_handler_func(filename)
		if f is not None:
			def reader():
				if filename in state._global_include_list: return  # already included
				f(state)
				state._global_include_list.append(filename)
				return
				yield None # to make it a generator
			return reader(), None
		return oldFunc(filename) # fallback

	def install(self):
		state = self.state
		oldFunc = state.readGlobalInclude
		state.readGlobalInclude = lambda fn: self.readGlobalInclude(state, oldFunc, fn)

	def add_all_to_state(self, state):
		for funcname in dir(self):
			if not funcname.startswith("handle_"): continue
			f = getattr(self, funcname)
			f(state)
