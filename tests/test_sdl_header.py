
from cparser import *
from pprint import pprint


def parse_file():
	import better_exchook
	better_exchook.install()

	state = State()
	state.autoSetupSystemMacros()

	filename = "/Library/Frameworks/SDL.framework/Headers/SDL.h"
	preprocessed = state.preprocess_file(filename, local=True)
	tokens = cpre2_parse(state, preprocessed)

	token_list = []
	def copy_hook(input, output):
		for x in input:
			output.append(x)
			yield x
	tokens = copy_hook(tokens, token_list)


	cpre3_parse(state, tokens)
	print "tokens:"
	pprint(token_list)
	print "parse errors:"
	pprint(state._errors)
	assert not state._errors

	return state, token_list
