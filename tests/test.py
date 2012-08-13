#!/usr/bin/python

import sys, os
mydir = os.path.dirname(__file__)
sys.path += [mydir + "/.."]

import cparser

def main():
	import types
	
	from glob import glob
	for f in glob(mydir + "/test_*.py"):
		c = compile(open(f).read(), os.path.basename(f), "exec")
		m = {}
		eval(c, m)
		for name,obj in m.items():
			if name.startswith("test") and isinstance(obj, types.FunctionType):
				obj()

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

if __name__ == '__main__':
	main()
