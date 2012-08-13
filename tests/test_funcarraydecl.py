import sys
sys.path += [".."]
from pprint import pprint
import cparser, test

testcode = """
	int16_t (*motion_val[2])[2];
"""

state = test.newState(testcode)

def test():
	cparser.parse("test.c", state)
	pprint(state._errors)
	
if __name__ == '__main__':
	test()
	