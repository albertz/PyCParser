#!/usr/bin/python
# Test interpreter
# by Albert Zeyer, 2011
# code under GPL

import sys, os, os.path
if __name__ == '__main__':
	MyDir = os.path.dirname(sys.argv[0]) or "."
else:
	MyDir = "."

sys.path.append(MyDir + "/../..") # so that 'import cparser' works as expected
sys.path.append(MyDir + "/..") # so that 'import better_exchook' works

import better_exchook
better_exchook.install()

import cparser

input = sys.stdin

def input_reader_handler(state):
	oldErrNum = len(state._errors)
	oldContentListNum = len(state.contentlist)
	
	while True:
		c = input.read(1)
		if len(c) == 0: break
		if c == "\n":
			for m in state._errors[oldErrNum:]:
				print "Error:", m
			oldErrNum = len(state._errors)
			for m in state.contentlist[oldContentListNum:]:
				print "Parsed:", m
			oldContentListNum = len(state.contentlist)	
		yield c

def prepareState():
	state = cparser.State()
	state.autoSetupSystemMacros()	
	state.autoSetupGlobalIncludeWrappers()	
	def readInclude(fn):
		if fn == "<input>":
			reader = input_reader_handler(state)
			return reader, None
		return cparser.State.readLocalInclude(state, fn)
	state.readLocalInclude = readInclude
	return state

state = prepareState()

if __name__ == '__main__':
	cparser.parse("<input>", state)

