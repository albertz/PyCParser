# PyCParser - interpreter
# by Albert Zeyer, 2011
# code under LGPL

import cparser
from cwrapper import CStateWrapper

import ctypes
import ast


class Interpreter:
	def __init__(self):
		self.stateStructs = []
		self._cStateWrapper = CStateWrapper(self)
		self._func_cache = {}
		
	def register(self, stateStruct):
		self.stateStructs += [stateStruct]
	
	def getCType(self, obj):
		wrappedStateStruct = self._cStateWrapper
		for T,DictName in [(cparser.CStruct,"structs"), (cparser.CUnion,"unions"), (cparser.CEnum,"enums")]:
			if isinstance(obj, T):
				if obj.name is not None:
					return getattr(wrappedStateStruct, DictName)[obj.name].getCValue(wrappedStateStruct)
				else:
					return obj.getCValue(wrappedStateStruct)
		return obj.getCValue(wrappedStateStruct)
	
	def translateFuncToPy(self, funcname):
		func = self._cStateWrapper.funcs[funcname]
		for c in func.body.contentlist:
			# TODO :)
			pass
		return lambda *args: None # dummy return
	
	def runFunc(self, funcname, *args):
		if funcname in self._func_cache:
			func = self._func_cache[funcname]
		else:
			func = self.translateFuncToPy(funcname)
			self._func_cache[funcname] = func
		func(*args)
