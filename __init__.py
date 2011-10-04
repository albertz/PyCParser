import sys
if sys.version_info.major == 2:
	from cparser import *
else:
	from .cparser import *

