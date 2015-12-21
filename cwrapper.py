# PyCParser - C wrapper
# by Albert Zeyer, 2011
# code under BSD 2-Clause License

import cparser
import ctypes
import sys
if sys.version_info.major == 2:
	from cparser_utils import *
else:
	from .cparser_utils import *

class CStateDictWrapper:
	__doc__ = """generic dict wrapper
	This is a generic dict wrapper to merge multiple dicts to a single one.
	It is intended mostly to merge different dicts from different cparser.State."""
	
	def __init__(self, dicts):
		self._dicts = dicts
	def __setitem__(self, k, v):
		assert False, "read-only in C wrapped state"
	def __getitem__(self, k):
		found = []
		for d in self._dicts:
			try: found += [d[k]]
			except KeyError: pass
		for f in found:
			# prefer items with body set.
			if hasattr(f, "body") and f.body is not None: return f
		if found:
			# fallback, noone has body set.
			return found[0]
		raise KeyError(str(k) + " not found in C wrapped state " + str(self))
	def __contains__(self, k):
		for d in self._dicts:
			if k in d: return True
		return False
	def get(self, k, default = None):
		try: return self.__getitem__(k)
		except KeyError: return default
	def has_key(self, k):
		return self.__contains__(k)
	def __repr__(self): return "CStateDictWrapper(" + repr(self._dicts) + ")"
	def __str__(self): return "CStateDictWrapper(" + str(self._dicts) + ")"

class CStateWrapper:
	__doc__ = """cparser.State wrapper
	Merges multiple cparser.State into a single one."""

	WrappedDicts = ("macros","typedefs","structs","unions","enums","funcs","vars","enumconsts")
	LocalAttribs = ("_cwrapper")
	def __init__(self, cwrapper):
		self._cwrapper = cwrapper
	def __getattr__(self, k):
		if k in self.LocalAttribs: raise AttributeError # normally we shouldn't get here but just in case
		if k == "_errors": return getattr(self._cwrapper, k) # fallthrough to CWrapper to collect all errors there
		if k in self.WrappedDicts:
			return CStateDictWrapper(dicts = map(lambda s: getattr(s, k), self._cwrapper.stateStructs))

		# fallback to first stateStruct
		if len(self._cwrapper.stateStructs) == 0:
			raise AttributeError("CStateWrapper " + str(self) + " doesn't have any state structs set yet")
		stateStruct = self._cwrapper.stateStructs[0]
		attr = getattr(stateStruct, k)
		import types
		if isinstance(attr, types.MethodType):
			attr = rebound_instance_method(attr, self)
		return attr
	def __repr__(self):
		return "<CStateWrapper of " + repr(self._cwrapper) + ">"
	def __str__(self): return self.__repr__()
	def __setattr__(self, k, v):
		self.__dict__[k] = v
	def __getstate__(self):
		assert False, "this is not really prepared/intended to be pickled"

def _castArg(value):
	if isinstance(value, (str,unicode)):
		return ctypes.cast(ctypes.c_char_p(value), ctypes.POINTER(ctypes.c_byte))
	return value
	
class CWrapper:
	__doc__ = """Provides easy access to symbols to be used by Python.
	Wrapped functions are directly callable given the ctypes DLL.
	Use register() to register a new set of (parsed-header-state,dll).
	Use get() to get a symbol-ref (cparser type).
	Use getWrapped() to get a wrapped symbol. In case of a function, this is a
	callable object. In case of some other const, it is its value. In case
	of some type (struct, typedef, enum, ...), it is its ctypes type.
	Use wrapped as an object where its __getattrib__ basically wraps to get().
	"""

	def __init__(selfWrapper):
		selfWrapper._cache = {}
		selfWrapper.stateStructs = []
		class Wrapped(object):
			def __getattribute__(self, attrib):
				if attrib == "_cwrapper": return selfWrapper
				if attrib in ("__dict__","__class__"):
					return object.__getattribute__(self, attrib)
				return selfWrapper.getWrapped(attrib)
		selfWrapper.wrapped = Wrapped()
		selfWrapper._wrappedStateStruct = CStateWrapper(selfWrapper)
		selfWrapper._errors = []
		
	def register(self, stateStruct, clib):
		stateStruct.clib = clib
		self.stateStructs.append(stateStruct)
		def iterAllAttribs():
			for attrib in stateStruct.macros:
				if stateStruct.macros[attrib].args is not None: continue
				yield attrib
			for attrib in stateStruct.typedefs:
				yield attrib
			for attrib in stateStruct.enumconsts:
				yield attrib
			for attrib in stateStruct.funcs:
				yield attrib
		wrappedClass = self.wrapped.__class__
		for attrib in iterAllAttribs():
			if not hasattr(wrappedClass, attrib):
				setattr(wrappedClass, attrib, None)
	
	def resolveMacro(self, stateStruct, macro):
		macro._parseTokens(stateStruct)
		resolvedMacro = macro.getSingleIdentifer(self._wrappedStateStruct) # or just stateStruct?
		if resolvedMacro is not None: self.get(str(resolvedMacro))
		return macro
		
	def get(self, attrib, resolveMacros = True):
		for stateStruct in self.stateStructs:
			if attrib in stateStruct.macros and stateStruct.macros[attrib].args is None:
				if resolveMacros: return self.resolveMacro(stateStruct, stateStruct.macros[attrib])
				else: return stateStruct.macros[attrib]
			elif attrib in stateStruct.typedefs:
				return stateStruct.typedefs[attrib]
			elif attrib in stateStruct.enumconsts:
				return stateStruct.enumconsts[attrib]
			elif attrib in stateStruct.funcs:
				return stateStruct.funcs[attrib]		
		raise AttributeError(attrib + " not found in " + str(self))
		
	def getWrapped(self, attrib):
		cache = self._cache
		if attrib in cache: return cache[attrib]

		s = self.get(attrib)
		assert s
		wrappedStateStruct = self._wrappedStateStruct
		if isinstance(s, cparser.Macro):
			t = s.getCValue(wrappedStateStruct)
		elif isinstance(s, (cparser.CType,cparser.CTypedef,cparser.CStruct,cparser.CEnum)):
			t = s.getCType(wrappedStateStruct)
		elif isinstance(s, cparser.CEnumConst):
			t = s.value
		elif isinstance(s, cparser.CFunc):
			clib = s.parent.body.clib # s.parent.body is supposed to be the stateStruct
			t = s.getCType(wrappedStateStruct)
			f = t((attrib, clib))
			t = lambda *args: f(*map(_castArg, args))			
		else:
			raise AttributeError(attrib + " has unknown type " + repr(s))
		cache[attrib] = t
		return t
	
	def __repr__(self):
		return "<" + self.__class__.__name__  + " of " + repr(self.stateStructs) + ">"
