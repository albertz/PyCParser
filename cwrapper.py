# PyCParser - C wrapper
# by Albert Zeyer, 2011
# code under LGPL

class CStateDictWrapper:
	def __init__(self, dicts):
		self._dicts = dicts
	def __setitem__(self, k, v):
		assert False, "read-only in C wrapped state"
	def __getitem__(self, k):
		for d in self._dicts:
			try: return d[k]
			except KeyError: pass
		raise KeyError, str(k) + " not found in C wrapped state " + str(self)
	def __contains__(self, k):
		for d in self._dicts:
			if k in d: return True
		return False
	def has_key(self, k):
		return self.__contains__(k)
	def __repr__(self): return "CStateDictWrapper(" + repr(self._dicts) + ")"
	def __str__(self): return "CStateDictWrapper(" + str(self._dicts) + ")"
	
class CStateWrapper:
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
			raise AttributeError, "CStateWrapper " + str(self) + " doesn't have any state structs set yet"		
		stateStruct = self._cwrapper.stateStructs[0]
		attr = getattr(stateStruct, k)
		import types
		if isinstance(attr, types.MethodType):
			# rebound
			attr = types.MethodType(attr.im_func, self, self.__class__)
		return attr
	def __repr__(self):
		return "<CStateWrapper of " + repr(self._cwrapper) + ">"
	def __str__(self): return self.__repr__()
	def __setattr__(self, k, v):
		if k in self.LocalAttribs:
			self.__dict__[k] = v
			return
		assert False, "read-only CStateWrapper " + str(self)
	def __getstate__(self):
		assert False, "this is not really prepared/intended to be pickled"
	
class CWrapper:
	def __init__(selfWrapper):
		selfWrapper._cache = {}
		selfWrapper.stateStructs = []
		class Wrapped(object):
			def __getattribute__(self, attrib):
				if attrib == "_cwrapper": return selfWrapper
				if attrib in ("__dict__","__class__"):
					return object.__getattribute__(self, attrib)
				return selfWrapper.get(attrib)
		selfWrapper.wrapped = Wrapped()
		selfWrapper._wrappedStateStruct = CStateWrapper(selfWrapper)
		selfWrapper._errors = []
		
	def register(self, stateStruct, clib):
		stateStruct.clib = clib
		self.stateStructs.append(stateStruct)
		def iterAllAttribs():
			for attrib in stateStruct.macros:
				if len(stateStruct.macros[attrib].args) > 0: continue
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
	
	def get(self, _attrib):
		cache = self._cache
		if _attrib in cache: return cache[_attrib]
		wrappedStateStruct = self._wrappedStateStruct
		for stateStruct in self.stateStructs:
			attrib = _attrib
			while attrib in stateStruct.macros and len(stateStruct.macros[attrib].args) == 0:
				stateStruct.macros[attrib]._parseTokens(stateStruct)
				resolvedMacro = stateStruct.macros[attrib].getSingleIdentifer(wrappedStateStruct)
				if resolvedMacro is not None: attrib = str(resolvedMacro)
				else: break
			if attrib in stateStruct.macros and len(stateStruct.macros[attrib].args) == 0:
				t = stateStruct.macros[attrib].getCValue(wrappedStateStruct)
			elif attrib in stateStruct.typedefs:
				t = stateStruct.typedefs[attrib].getCType(wrappedStateStruct)
			elif attrib in stateStruct.enumconsts:
				t = stateStruct.enumconsts[attrib].value
			elif attrib in stateStruct.funcs:
				t = stateStruct.funcs[attrib].getCType(wrappedStateStruct)
				t = t((attrib, stateStruct.clib))
			else:
				continue
			cache[_attrib] = t
			return t
			
		raise AttributeError, _attrib + " not found in " + str(self)
	
	def __repr__(self):
		return "<" + self.__class__.__name__  + " of " + repr(self.stateStructs) + ">"
