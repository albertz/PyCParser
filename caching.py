# PyCParser caching logic
# by Albert Zeyer, 2011
# code under LGPL

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
import os, os.path
import types

# Note: It might make sense to make this somehow configureable.
# However, for now, I'd like to keep things as simple as possible.
# Using /tmp or (a bit better) /var/tmp might have been another
# possibility. However, it makes sense to keep this more permanent
# because when compiling a lot, it can be very time-critical if
# we just remove all the data.
# If wasted space becomes an issue, it is easy to write a script
# which would remove all old/obsolete entries from the cache.
# It makes sense also to keep this global for the whole system
# because the caching system should be able to handle this
# and it should thus only improve the performance.
# It is saved though in the user directory because most probably
# we wouldn't have write permission otherwise.
CACHING_DIR = os.path.expanduser("~/.cparser_caching/")

def sha1(obj):
	import hashlib
	h = hashlib.sha1()
	if isinstance(obj, (str,unicode)):
		h.update(obj)
	elif isinstance(obj, dict):
		h.update("{")
		for k,v in sorted(obj.iteritems()):
			h.update(sha1(k))
			h.update(":")
			h.update(sha1(v))
			h.update(",")
		h.update("}")
	elif isinstance(obj, (list,tuple)):
		h.update("[")
		for v in sorted(obj):
			h.update(sha1(v))
			h.update(",")
		h.update("]")
	else:
		h.update(str(obj))
	return h.hexdigest()

class MyDict(dict):
	def __setattr__(self, key, value):
		assert isinstance(key, (str,unicode))
		self[key] = value
	def __getattr__(self, key):
		try: return self[key]
		except KeyError: raise AttributeError
	def __repr__(self): return "MyDict(" + dict.__repr__(self) + ")"
	def __str__(self): return "MyDict(" + dict.__str__(self) + ")"
	
class DbObj:
	@classmethod
	def GetFilePath(cls, key):
		h = sha1(key)
		prefix = CACHING_DIR + cls.Namespace
		return prefix + "/" + h[:2] + "/" + h[2:]
	@classmethod
	def Load(cls, key, create=False):
		fn = cls.GetFilePath(key)
		try: f = open(fn)
		except:
			if create:
				obj = cls()
				obj.__dict__["_key"] = key
				return obj
			else:
				return None
		import pickle
		obj = pickle.load(f)
		f.close()
		return obj
	@classmethod
	def Delete(cls, key):
		fn = cls.GetFilePath(key)
		os.remove(fn)
	def delete(self): self.Delete(self._key)
	def save(self):
		fn = self.GetFilePath(self._key)
		try: os.makedirs(os.path.dirname(fn))
		except: pass # ignore file-exists or other errors
		f = open(fn, "w")
		import pickle
		pickle.dump(self, f)
		f.close()
	
def getLastChangeUnixTime(filename):
	import os.path
	return os.path.getmtime(filename)

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
	@classmethod
	def FromCacheData(cls, cache_data, key):
		obj = cls()
		obj.__dict__["_key"] = key
		obj.additions = cache_data.additions
		return obj
	def apply(self, stateStruct):
		for k,l in self.additions.iteritems():
			a = getattr(stateStruct, k)
			if isinstance(a, (list,StateListWrapper)):
				a.extend(l)
			elif isinstance(a, (dict,StateDictWrapper)):
				for dk,dv in l:
					if dv is None:
						a.pop(dk)
					else:
						a[dk] = dv
			else:
				assert False, "unknown attribute " + k + ": " + str(a)

def check_cache(stateStruct, full_filename):	
	filecaches = FileCacheRefs.Load(full_filename)
	if filecaches is None: return None
	
	for filecacheref in filecaches:
		if not filecacheref.match(stateStruct):
			continue
		if not filecacheref.checkFileDepListUpToDate():
			FileCache.Delete(filecacheref)
			filecaches.remove(filecacheref)
			filecaches.save()
			return None
		filecache = FileCache.Load(filecacheref)
		assert filecache is not None, sha1(filecacheref) + " not found in " + FileCache.Namespace
		return filecache
	
	return None

def save_cache(cache_data, full_filename):
	filecaches = FileCacheRefs.Load(full_filename, create=True)
	filecacheref = FileCacheRef.FromCacheData(cache_data)
	filecaches.append(filecacheref)
	filecaches.save()
	filecache = FileCache.FromCacheData(cache_data, key=filecacheref)
	filecache.save()

# Note: This does more than State.preprocess. In case it hits a cache,
# it applies all effects up to cpre3 and ignores the preprocessing.
# Note also: This is a generator. In the cache hit case, it yields nothing.
# Otherwise, it doesn't do any further processing and it just yields the rest.
def State__cached_preprocess(stateStruct, reader, full_filename, filename):
	if not full_filename:
		# shortcut. we cannot use caching if we don't have the full filename.
		for c in cparser.State.preprocess.im_func(stateStruct, reader, full_filename, filename):
			yield c
		return
	
	if stateStruct._cpre3_atBaseLevel:
		try:
			cached_entry = check_cache(stateStruct, full_filename)
			if cached_entry is not None:
				cached_entry.apply(stateStruct)
				return
		except Exception, e:
			print "(Safe to ignore) Error while reading C parser cache for", filename, ":", e
			# Try to delete old references if possible. Otherwise we might always hit this.
			try: FileCacheRefs.Delete(full_filename)
			except: pass

	assert isinstance(stateStruct, StateWrapper)
	stateStruct.cache_pushLevel()
	stateStruct._filenames.add(full_filename)
	for c in cparser.State.preprocess.im_func(stateStruct, reader, full_filename, filename):
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
	def __contains__(self, k): return self.has_key(k)
	def has_key(self, k):
		haskey = self._dict.has_key(k)
		if haskey and self._accessSet is not None:
			assert self._addSet is not None
			if not k in self._addSet: # we only care about it if we didn't add it ourself
				self._accessSet.add(k)
		return haskey
	def pop(self, k):
		self._dict.pop(k)
		self._addList.append((k,None))
		if self._addSet is not None:
			self._addSet.discard(k)
	def __repr__(self): return "StateDictWrapper(" + repr(self._dict) + ")"
	def __str__(self): return "StateDictWrapper(" + str(self._dict) + ")"
		
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
	def extend(self, l):
		self._list.extend(l)
		self._addList.extend(l)
	def __repr__(self): return "StateListWrapper(" + repr(self._list) + ")"
	def __str__(self): return "StateListWrapper(" + str(self._list) + ")"

class StateWrapper:
	WrappedDicts = ("macros","typedefs","structs","unions","enums","funcs","vars","enumconsts")
	WrappedLists = ("contentlist",)
	LocalAttribs = ("_stateStruct", "_cache_stack", "_additions", "_macroAccessSet", "_macroAddSet", "_filenames", "_cpre3_atBaseLevel")
	def __init__(self, stateStruct):
		self._stateStruct = stateStruct
		self._cache_stack = []
	def __getattr__(self, k):
		if k in self.LocalAttribs: raise AttributeError # normally we shouldn't get here but just in case
		if len(self._cache_stack) > 0:
			if k in self.WrappedDicts:
				kwattr = {'d': getattr(self._stateStruct, k), 'addList': self._additions[k]}
				if k == "macros":
					kwattr["accessSet"] = self._macroAccessSet
					kwattr["addSet"] = self._macroAddSet
				return StateDictWrapper(**kwattr)
			if k in self.WrappedLists:
				return StateListWrapper(getattr(self._stateStruct, k), addList=self._additions[k])
		attr = getattr(self._stateStruct, k)
		if isinstance(attr, types.MethodType):
			# rebound
			attr = types.MethodType(attr.im_func, self, self.__class__)
		return attr
	def __repr__(self):
		return "<StateWrapper of " + repr(self._stateStruct) + ">"
	def __setattr__(self, k, v):
		if k in self.LocalAttribs:
			self.__dict__[k] = v
			return
		if k in self.WrappedLists and isinstance(v, StateListWrapper): return # ignore. probably iadd or so.
		setattr(self._stateStruct, k, v)
	def cache_pushLevel(self):
		self._additions = {} # dict/list attrib -> addition list
		for k in self.WrappedDicts + self.WrappedLists: self._additions[k] = []
		self._macroAccessSet = set()
		self._macroAddSet = set()
		self._filenames = set()
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
			for k in self.WrappedDicts + self.WrappedLists:
				self._additions[k].extend(cache_data.additions[k])
			self._macroAddSet.update(cache_data.macroAddSet)
			for k in cache_data.macroAccessSet:
				if k not in self._macroAddSet:
					self._macroAccessSet.add(k)
			self._filenames.update(cache_data.filenames)
		return cache_data
	preprocess = State__cached_preprocess
	def __getstate__(self):
		# many C structure objects refer to this as their parent.
		# when we pickle those objects, it should be safe to ignore to safe this.
		# we also don't really have any other option because we don't want to
		# dump this whole object.
		return None
		
def parse(filename, state = None):
	if state is None:
		state = cparser.State()
		state.autoSetupSystemMacros()
	
	wrappedState = StateWrapper(state)
	preprocessed = wrappedState.preprocess_file(filename, local=True)
	tokens = cparser.cpre2_parse(wrappedState, preprocessed)
	cparser.cpre3_parse(wrappedState, tokens)
	
	return state

def test():
	import better_exchook
	better_exchook.install()
	
	state = parse("/Library/Frameworks/SDL.framework/Headers/SDL.h")
	
	return state

if __name__ == '__main__':
	print test()
