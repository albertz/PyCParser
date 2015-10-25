#!/usr/bin/python

import better_exchook
better_exchook.install()
better_exchook.replace_traceback_format_tb()

import cparser
from pprint import pprint

def newState(testcode, testfn = "test.c", withSystemMacros=True, withGlobalIncludeWrappers=False):
	state = cparser.State()
	if withSystemMacros: state.autoSetupSystemMacros()
	if withGlobalIncludeWrappers: state.autoSetupGlobalIncludeWrappers()
		
	origReadLocal = state.readLocalInclude
	def readLocalIncludeWrapper(fn):
		if fn == testfn:
			def reader():
				for c in testcode:
					yield c
			reader = reader()
			return reader, fn
		return origReadLocal(fn)
	state.readLocalInclude = readLocalIncludeWrapper
	
	return state

def parse(testcode, **kwargs):
	state = newState(testcode, **kwargs)
	cparser.parse("test.c", state)
	if state._errors:
		print "parsing errors:"
		pprint(state._errors)
		assert False, "there are parsing errors"
	return state
