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

def setupParserCache(state, cachedir):
	pass
