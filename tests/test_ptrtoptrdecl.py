
from pprint import pprint
import cparser, helpers_test

def test_ptrtoptrdecl():
	testcode = """
		int16_t (*motion_val[2])[2];
	"""

	state = helpers_test.parse(testcode)

	v = state.vars["motion_val"]

	pprint((v, v.type))
