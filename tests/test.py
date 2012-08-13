#!/usr/bin/python

import sys, os
mydir = os.path.dirname(__file__)
sys.path += [mydir + "/.."]

import better_exchook
better_exchook.install()

import cparser
from pprint import pprint

def main():
	import types
	
	from glob import glob
	for f in glob(mydir + "/test_*.py"):
		c = compile(open(f).read(), os.path.basename(f), "exec")
		m = {}
		eval(c, m)

def newState(testcode, testfn = "test.c"):
	state = cparser.State()
	state.autoSetupSystemMacros()
	
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

def parse(testcode):
	state = newState(testcode)
	cparser.parse("test.c", state)
	if state._errors:
		print "parsing errors:"
		pprint(state._errors)
		assert False, "there are parsing errors"
	return state

if __name__ == '__main__':
	main()
