# idea:
#   for each parsed file:
#     keep list of which macros have been used, i.e.
#        the dependency list of macros.
#     keep list of all C-stuff which has been added.
#     check last change time of file and all other files we open from here
#        and also store this list.
#     save all.
#  when opening a new file, macro-dependencies, check the last change time
#     of all files and if everything matches, use the cache.

import cparser

class MyDict(dict):
	def __setattr__(self, key, value):
		self[key] = value
	def __getattr__(self, key):
		try: return self[key]
		except KeyError: raise AttributeError
	def __hash__(self):
		t = tuple(sorted(self.iteritems()))
		return hash(t)
		
def State__cached_preprocess_file(stateStruct, filename, local):
	
	
	pass

class StateDictWrapper:
	def __init__(self, addList, d):
		self._addList = addList
		self._dict = d
	def __getattr__(self, k):
		return getattr(self._dict, k)
	def __setitem__(self, k, v):
		self._addList += [(k,v)]
		self._dict[k] = v
		
class StateListWrapper:
	def __init__(self, addList, l):
		self._addList = addList
		self._list = l
	def __getattr__(self, k):
		return getattr(self._list, k)
	def __iadd__(self, l):
		self._addList += l
		self._list.extend(l)
		return self
	def append(self, v):
		self._addList += [v]
		self._list.append(v)

class StateWrapper:
	WrappedDicts = ("macros","typedefs","structs","unions","enums","funcs","vars","enumconsts")
	WrappedLists = ("contentlist",)
	def __init__(self, stateStruct):
		self._stateStruct = stateStruct
		self._additions = {} # dict/list attrib -> addition list
	def __getattr__(self, k):
		if k in self.WrappedDicts:
			self._additions[k] = self._additions.get(k, [])
			return StateDictWrapper(self._additions[k], getattr(self._stateStruct, k))
		if k in self.WrappedLists:
			self._additions[k] = self._additions.get(k, [])
			return StateListWrapper(self._additions[k], getattr(self._stateStruct, k))
		return getattr(self._stateStruct, k)
	def __repr__(self):
		return "<StateWrapper of " + repr(self._stateStruct) + ">"
	def __setattr__(self, k, v):
		if k in ("_stateStruct", "_additions"):
			self.__dict__[k] = v
			return
		if k in self.WrappedLists and isinstance(v, StateListWrapper): return # ignore. probably iadd or so.
		raise AttributeError, str(self) + " has attribute '" + k + "' read-only, cannot set to " + repr(v)
	
def setupParserCache(state, cachedir):
	pass
