import sys
sys.path += [".."]
from pprint import pprint
import cparser, test

testcode = """
	int16_t (*motion_val[2])[2];
"""

state = test.parse(testcode)	

pprint(state.contentlist)
pprint(state.vars)
