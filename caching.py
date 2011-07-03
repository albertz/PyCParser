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

class DbObj(MyDict):
	def __init__(self, namespace, key):
		pass
	@classmethod
	def Load(cls, namespace, key):
		# TODO
		return cls()
	@staticmethod
	def Delete(namespace, key):
		obj = DbObj.Load(namespace, key)
		obj.delete()
	# TODO
	def delete(self): pass
	def save(self): pass
	
def getLastChangeUnixTime(filename):
	# TODO
	pass

class FileCacheRef:
	@classmethod
	def FromCacheData(cls, cache_data):
		ref = cls()
		ref.filedepslist = map(lambda fn: (fn,getLastChangeUnixTime(fn)), cache_data.filenames)
		ref.macros = {} # TODO
		return ref
	def match(self, stateStruct):
		for macro in self.macros:
			if stateStruct.macros[macro] != self.macros[macro]:
				return False
		return True
	def checkFileDepListUpToDate(self):
		for fn,unixtime in self.filedepslist:
			if getLastChangeUnixTime(fn) > unixtime:
				return False
		return True		

class FileCaches(DbObj, list):
	pass

class FileCache(DbObj):
	# TODO
	def apply(self, stateStruct): pass

	
def check_cache(stateStruct, full_filename):	
	filecaches = DbObj.Load("file-cache-refs", full_filename)
	for filecache in filecaches:
		if not filecache.match(stateStruct): continue
		if not filecache.checkFileDepListUpToDate():
			DbObj.Delete("file-cache", filecache)
			filecaches.remove(filecache)
			filecaches.save()
			return None
		return DbObj.Load("file-cache", filecache)
	
	return None

def save_cache(cache_data, full_filename):
	filecaches = DbObj.Load("file-cache-refs", full_filename)
	filecache = FileCacheRef.FromCacheData(cache_data)
	filecaches.append(filecache)
	filecaches.save()
	

# Note: This does more than State.preprocess_file. In case it hits a cache,
# it applies all effects up to cpre3 and ignores the preprocessing.
# Note also: This is a generator. In the cache hit case, it yields nothing.
# Otherwise, it doesn't do any further processing and it just yields the rest.
def State__cached_preprocess(stateStruct, reader, full_filename, filename):
	if not full_filename:
		# shortcut. we cannot use caching if we don't have the full filename.
		for c in cparser.State.preprocess(stateStruct, reader, full_filename, filename):
			yield c
		return
	
	if stateStruct._cpre3_atBaseLevel:
		cached_entry = check_cache(stateStruct, full_filename)
		if cached_entry:
			cached_entry.apply(stateStruct)
			return

	assert isinstance(stateStruct, StateWrapper)
	stateStruct.cache_pushLevel()
	stateStruct._filenames.append(full_filename)
	for c in cparser.State.preprocess(stateStruct, full_filename, filename):
		yield c
	cache_data = stateStruct.cache_popLevel()
	
	save_cache(cache_data, full_filename)
	
class StateDictWrapper:
	def __init__(self, addList, d):
		self._addList = addList
		self._dict = d
	def __getattr__(self, k):
		return getattr(self._dict, k)
	def __setitem__(self, k, v):
		assert v is not None
		self._dict[k] = v
		self._addList += [(k,v)]
	def pop(self, k):
		self._dict.pop(k)
		self._addList += [(k,None)]
		
class StateListWrapper:
	def __init__(self, addList, l):
		self._addList = addList
		self._list = l
	def __getattr__(self, k):
		return getattr(self._list, k)
	def __iadd__(self, l):
		self._list.extend(l)
		self._addList += l
		return self
	def append(self, v):
		self._list.append(v)
		self._addList += [v]

class StateWrapper:
	WrappedDicts = ("macros","typedefs","structs","unions","enums","funcs","vars","enumconsts")
	WrappedLists = ("contentlist",)
	def __init__(self, stateStruct):
		self._stateStruct = stateStruct
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
		if k in ("_stateStruct", "_additions", "_cpre3_atBaseLevel"):
			self.__dict__[k] = v
			return
		if k in self.WrappedLists and isinstance(v, StateListWrapper): return # ignore. probably iadd or so.
		raise AttributeError, str(self) + " has attribute '" + k + "' read-only, cannot set to " + repr(v)
	def cache_pushLevel(self):
		self._additions = {} # dict/list attrib -> addition list
		self._filenames = []
	def cache_popLevel(self):
		pass
	preprocess_file = State__cached_preprocess_file

def parse(filename, state = None):
	if state is None:
		state = cparser.State()
		state.autoSetupSystemMacros()
	
	preprocessed = state.preprocess_file(filename, local=True)
	tokens = cpre2_parse(state, preprocessed)
	cpre3_parse(state, tokens)
	
	return state
	
def setupParserCache(state, cachedir):
	pass
