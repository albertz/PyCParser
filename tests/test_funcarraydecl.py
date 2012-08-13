import sys
sys.path += [".."]
from pprint import pprint
import cparser, test

testcode = """
	int16_t (*motion_val[2])[2];
"""

state = test.parse(testcode)	

v = state.vars["motion_val"]

pprint((v, v.type))
