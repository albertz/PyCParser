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

def sha1(obj):
	import hashlib
	h = hashlib.sha1()
	if isinstance(obj, (str,unicode)):
		h.update(obj)
	elif isinstance(obj, MyDict):
		h.update("{")
		for k,v in sorted(obj.iteritems()):
			h.update(k)
			h.update(":")
			h.update(sha1(v))
			h.update(",")
		h.update("}")
	elif isinstance(obj, list):
		h.update("[")
		for v in sorted(obj):
			h.update(sha1(v))
			h.update(",")
		h.update("]")
	else:
		raise TypeError, "sha1 does not support obj " + str(obj)
	return h.hexdigest()

class MyDict(dict):
	def __setattr__(self, key, value):
		assert isinstance(key, (str,unicode))
		self[key] = value
	def __getattr__(self, key):
		try: return self[key]
		except KeyError: raise AttributeError

class DbObj:
	def __init__(self, key):
		pass
	@classmethod
	def Load(cls, key):
		# TODO
		return cls(key)
	@classmethod
	def Delete(cls, key):
		obj = cls.Load(key)
		obj.delete()
	# TODO
	def delete(self): pass
	def save(self): pass
	
def getLastChangeUnixTime(filename):
	import os
	s = os.stat(filename)
	return s.st_mtime

class FileCacheRef(MyDict):
	@classmethod
	def FromCacheData(cls, cache_data):
		ref = cls()
		ref.filedepslist = map(lambda fn: (fn,getLastChangeUnixTime(fn)), cache_data.filenames)
		ref.macros = {}
		for m in cache_data.macroAccessSet:
			ref.macros[m] = cache_data.oldMacros[m]
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

class FileCacheRefs(DbObj, list):
	Namespace = "file-cache-refs"

class FileCache(DbObj, MyDict):
	Namespace = "file-cache"
	# TODO
	def apply(self, stateStruct): pass

	
def check_cache(stateStruct, full_filename):	
	filecaches = FileCacheRefs.Load(full_filename)
	for filecache in filecaches:
		if not filecache.match(stateStruct): continue
		if not filecache.checkFileDepListUpToDate():
			FileCache.Delete(filecache)
			filecaches.remove(filecache)
			filecaches.save()
			return None
		return FileCache.Load(filecache)
	
	return None

def save_cache(cache_data, full_filename):
	filecaches = FileCacheRefs.Load(full_filename)
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
	def __init__(self, d, addList, addSet=None, accessSet=None):
		self._addList = addList
		self._addSet = addSet
		self._accessSet = accessSet
		self._dict = d
	def __getattr__(self, k):
		return getattr(self._dict, k)
	def __setitem__(self, k, v):
		assert v is not None
		self._dict[k] = v
		self._addList.append((k,v))
		if self._addSet is not None:
			self._addSet.add(k)
	def __getitem__(self, k):
		if self._accessSet is not None:
			assert self._addSet is not None
			if not k in self._addSet: # we only care about it if we didn't add it ourself
				self._accessSet.add(k)
		return self._dict[k]
	def pop(self, k):
		self._dict.pop(k)
		self._addList.append((k,None))
		if self._addSet is not None:
			self._addSet.remove(k)
		
class StateListWrapper:
	def __init__(self, l, addList):
		self._addList = addList
		self._list = l
	def __getattr__(self, k):
		return getattr(self._list, k)
	def __iadd__(self, l):
		self._list.extend(l)
		self._addList.extend(l)
		return self
	def append(self, v):
		self._list.append(v)
		self._addList.append(v)

class StateWrapper:
	WrappedDicts = ("macros","typedefs","structs","unions","enums","funcs","vars","enumconsts")
	WrappedLists = ("contentlist",)
	def __init__(self, stateStruct):
		self._stateStruct = stateStruct
		self._cache_stack = []
	def __getattr__(self, k):
		if k in self.WrappedDicts:
			kwattr = {'d': getattr(self._stateStruct, k), 'addList': self._additions[k]}
			if k == "macros":
				kwattr["accessSet"] = self._macroAccessSet
				kwattr["addSet"] = self._macroAddSet
			return StateDictWrapper(**kwattr)
		if k in self.WrappedLists:
			return StateListWrapper(getattr(self._stateStruct, k), addList=self._additions[k])
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
		for k in WrappedDicts + WrappedLists: self._additions[k] = []
		self._macroAccessSet = set()
		self._macroAddSet = set()
		self._filenames = []
		self._cache_stack.append(
			MyDict(
				oldMacros = dict(self._stateStruct.macros),
				additions = self._additions,
				macroAccessSet = self._macroAccessSet,
				macroAddSet = self._macroAddSet,
				filenames = self._filenames
				))
	def cache_popLevel(self):
		cache_data = self._cache_stack.pop()
		if len(self._cache_stack) == 0:
			del self._additions
			del self._macroAccessSet
			del self._macroAddSet
			del self._filenames		
		else:
			# recover last
			last = self._cache_stack[-1]
			self._additions = last.additions
			self._macroAccessSet = last.macroAccessSet
			self._macroAddSet = last.macroAddSet
			self._filenames = last.filenames
			# merge with popped frame
			for k in WrappedDicts + WrappedLists:
				self._additions[k].extend(cache_data.additions[k])
			self._macroAddSet.update(cache_data.macroAddSet)
			for k in cache_data.macroAccessSet:
				if k not in self._macroAddSet:
					self._macroAccessSet.add(k)
			self._filenames.extend(cache_data.filenames)
		return cache_data
	preprocess = State__cached_preprocess

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
