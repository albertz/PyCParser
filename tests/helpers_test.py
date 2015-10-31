#!/usr/bin/python

import better_exchook
better_exchook.install()
better_exchook.replace_traceback_format_tb()

import cparser
from pprint import pprint


def parse(testcode, withSystemMacros=True, withGlobalIncludeWrappers=False):
	state = cparser.State()
	if withSystemMacros: state.autoSetupSystemMacros()
	if withGlobalIncludeWrappers: state.autoSetupGlobalIncludeWrappers()
	cparser.parse_code(testcode, state)
	if state._errors:
		print "parsing errors:"
		pprint(state._errors)
		assert False, "there are parsing errors"
	return state
