# PyCParser - global include wrappers
# by Albert Zeyer, 2011
# code under LGPL

from cparser import *

class Wrapper:
	def handle_limits_h(self, state):
		state.macros["UCHAR_MAX"] = Macro(rightside="255")
	def handle_stdio_h(self, state):
		state.macros["NULL"] = Macro(rightside="0")
		state.vars["stdin"] = CVarDecl(type=CPointerType(CStdIntType("FILE")), name="stdin")
		state.vars["stdout"] = CVarDecl(type=CPointerType(CStdIntType("FILE")), name="stdout")
		state.vars["stderr"] = CVarDecl(type=CPointerType(CStdIntType("FILE")), name="stderr")
		state.funcs["fprintf"] = lambda *args: None # TODO
		state.funcs["fputs"] = lambda *args: None # TODO
		state.funcs["fopen"] = lambda *args: None # TODO
		state.funcs["fclose"] = lambda *args: None # TODO
		state.vars["errno"] = CVarDecl(type=CStdIntType("int"), name="errno")
		state.macros["EOF"] = Macro(rightside="-1")
		state.funcs["setbuf"] = lambda *args: None # TODO
		state.funcs["isatty"] = lambda *args: None # TODO
		state.funcs["fileno"] = lambda *args: None # TODO
		state.funcs["getc"] = lambda *args: None # TODO
		state.funcs["ungetc"] = lambda *args: None # TODO
		state.structs["stat"] = CStruct(name="stat") # TODO
		state.funcs["fstat"] = lambda *args: None # TODO
		state.macros["S_IFMT"] = Macro(rightside="0")
		state.macros["S_IFDIR"] = Macro(rightside="0")
	def handle_stdlib_h(self, state):
		state.funcs["malloc"] = lambda *args: None # TODO
		state.funcs["free"] = lambda *args: None # TODO
	def handle_stdarg_h(self, state): pass
	def handle_math_h(self, state): pass
	def handle_string_h(self, state):
		state.funcs["strlen"] = lambda *args: None # TODO
		state.funcs["strcpy"] = lambda *args: None # TODO
		state.funcs["strcat"] = lambda *args: None # TODO
		state.funcs["strcmp"] = lambda *args: None # TODO
		state.funcs["strtok"] = lambda *args: None # TODO
		state.funcs["strerror"] = lambda *args: None # TODO
	def handle_time_h(self, state): pass
	def handle_ctype_h(self, state): pass
	def handle_wctype_h(self, state): pass
	def handle_assert_h(self, state): pass

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
		