# PyCParser main file
# by Albert Zeyer, 2011
# code under BSD 2-Clause License

import ctypes, _ctypes
from inspect import isclass

SpaceChars = " \t"
LowercaseLetterChars = "abcdefghijklmnopqrstuvwxyz"
LetterChars = LowercaseLetterChars + LowercaseLetterChars.upper()
NumberChars = "0123456789"
OpChars = "&|=!+-*/%<>^~?:,."
LongOps = [c+"=" for c in  "&|=+-*/%<>^~!"] + ["--","++","->","<<",">>","&&","||","<<=",">>=","::",".*","->*"]
OpeningBrackets = "[({"
ClosingBrackets = "})]"

# NOTE: most of the C++ stuff is not really supported yet
OpPrecedences = {
	"::": 1,
	"++": 2, # as postfix; 3 as prefix
	"--": 2, # as postfix; 3 as prefix
	".": 2,
	"->": 2,
	"typeid": 2,
	"const_cast": 2,
	"dynamic_cast": 2,
	"reinterpret_cast": 2,
	"static_cast": 2,
	"!": 3,
	"~": 3,
	"sizeof": 3,
	"new": 3,
	"delete": 3,
	".*": 4,
	"->*": 4,
	"*": 5, # as bin op; 3 as prefix
	"/": 5,
	"%": 5,
	"+": 6, # as bin op; 3 as prefix
	"-": 6, # as bin op; 3 as prefix
	"<<": 7,
	">>": 7,
	"<": 8,
	"<=": 8,
	">": 8,
	">=": 8,
	"==": 9,
	"!=": 9,
	"&": 10, # as bin op; 3 as prefix
	"^": 11,
	"|": 12,
	"&&": 13,
	"||": 14,
	"?": 15, # a ? b : c
	"?:": 15, # this is the internal op representation when we have got all three sub nodes
	"=": 16,
	"+=": 16,
	"-=": 16,
	"*=": 16,
	"/=": 16,
	"%=": 16,
	"<<=": 16,
	">>=": 16,
	"&=": 16,
	"^=": 16,
	"|=": 16,
	"throw": 17,
	",": 18
}

OpsRightToLeft = set([
	"=",
	"+=", "-=",
	"*=", "/=", "%=",
	"<<=", ">>=",
	"&=", "^=", "|="
])

OpPrefixFuncs = {
	"+": (lambda x: +x),
	"-": (lambda x: -x),
	"&": (lambda x: ctypes.pointer(x)),
	"*": (lambda x: x.content),
	"++": (lambda x: ++x),
	"--": (lambda x: --x),
	"!": (lambda x: not x),
	"~": (lambda x: ~x),
}

OpPostfixFuncs = {
	"++", "--"
}

OpBinFuncs = {
	"+": (lambda a,b: a + b),
	"-": (lambda a,b: a - b),
	"*": (lambda a,b: a * b),
	"/": (lambda a,b: a / b),
	"%": (lambda a,b: a % b),
	"<<": (lambda a,b: a << b),
	">>": (lambda a,b: a >> b),
	"<": (lambda a,b: a < b),
	"<=": (lambda a,b: a <= b),
	">": (lambda a,b: a > b),
	">=": (lambda a,b: a >= b),
	"==": (lambda a,b: a == b),
	"!=": (lambda a,b: a != b),
	"&": (lambda a,b: a & b),
	"^": (lambda a,b: a ^ b),
	"|": (lambda a,b: a | b),
	"&&": (lambda a,b: a and b),
	"||": (lambda a,b: a or b),
	",": (lambda a,b: b),
	# NOTE: These assignment ops don't really behave like maybe expected
	# but they return the somewhat expected.
	"=": (lambda a,b: b),
	"+=": (lambda a,b: a + b),
	"-=": (lambda a,b: a - b),
	"*=": (lambda a,b: a * b),
	"/=": (lambda a,b: a / b),
	"%=": (lambda a,b: a % b),
	"<<=": (lambda a,b: a << b),
	">>=": (lambda a,b: a >> b),
	"&=": (lambda a,b: a & b),
	"^=": (lambda a,b: a ^ b),
	"|=": (lambda a,b: a | b),
}

# WARNING: this isn't really complete
def simple_escape_char(c):
	if c == "n": return "\n"
	elif c == "t": return "\t"
	elif c == "a": return "\a"
	elif c == "b": return "\b"
	elif c == "f": return "\f"
	elif c == "r": return "\r"
	elif c == "v": return "\v"
	elif c == "0": return "\0"
	elif c == "\n": return ""
	elif c == '"': return '"'
	elif c == "'": return "'"
	elif c == "\\": return "\\"
	else:
		# Just to be sure so that users don't run into trouble.
		assert False, "simple_escape_char: cannot handle " + repr(c) + " yet"
		return c

def escape_cstr(s):
	return s.replace('"', '\\"')

def parse_macro_def_rightside(stateStruct, argnames, input):
	assert input is not None
	if stateStruct is None:
		class Dummy:
			def error(self, s): pass
		stateStruct = Dummy()

	def f(*args):
		assert len(args) == len(argnames or ())
		args = {k: v for (k, v) in zip(argnames or (), args)}

		ret = ""
		state = 0
		lastidentifier = ""
		for c in input:
			if state == 0:
				if c in SpaceChars: ret += c
				elif c in LetterChars + "_":
					state = 1
					lastidentifier = c
				elif c in NumberChars:
					state = 2
					ret += c
				elif c == '"':
					state = 4
					ret += c
				elif c == "#": state = 6
				else: ret += c
			elif state == 1: # identifier
				if c in LetterChars + NumberChars + "_":
					lastidentifier += c
				elif c == "#":
					if lastidentifier in args:
						ret += args[lastidentifier]
					else:
						ret += lastidentifier
					lastidentifier = ""
					state = 9
				else:
					if lastidentifier in args:
						ret += args[lastidentifier]
					else:
						ret += lastidentifier
					lastidentifier = ""
					ret += c
					state = 0
			elif state == 2: # number
				ret += c
				if c in NumberChars: pass
				elif c == "x": state = 3
				elif c in LetterChars + "_": pass # even if invalid, stay in this state
				else: state = 0
			elif state == 3: # hex number
				ret += c
				if c in NumberChars + LetterChars + "_": pass # also ignore invalids
				else: state = 0
			elif state == 4: # str
				ret += c
				if c == "\\": state = 5
				elif c == '"': state = 0
				else: pass
			elif state == 5: # escape in str
				state = 4
				ret += simple_escape_char(c)
			elif state == 6: # after "#"
				if c in SpaceChars + LetterChars + "_":
					lastidentifier = c.strip()
					state = 7
				elif c == "#":
					ret = ret.rstrip()
					state = 8
				else:
					# unexpected, just recover
					stateStruct.error("unfold macro: unexpected char '" + c + "' after #")
					state = 0
			elif state == 7: # after single "#"	with identifier
				if c in LetterChars + NumberChars + "_":
					lastidentifier += c
				else:
					if lastidentifier not in args:
						stateStruct.error("unfold macro: cannot stringify " + lastidentifier + ": not found")
					else:
						ret += '"' + escape_cstr(args[lastidentifier]) + '"'
					lastidentifier = ""
					state = 0
					ret += c
			elif state == 8: # after "##"
				if c in SpaceChars: pass
				else:
					lastidentifier = c
					state = 1
			elif state == 9: # after identifier + "#"
				if c == "#": state = 10
				else:
					stateStruct.error("unfold macro: unexpected char %r after in state %i" % (c, state))
					state = 0  # recover
			elif state == 10: # after identifier + "##"
				if c in LetterChars + "_":
					lastidentifier = c
					state = 1
				else:
					stateStruct.error("unfold macro: unexpected char %r after in state %i" % (c, state))
					state = 0  # recover
			else:
				stateStruct.error("unfold macro: internal error, char %r, in state %i" % (c, state))
				state = 0  # recover
		# Final check.
		if state == 1:
			if lastidentifier in args:
				ret += args[lastidentifier]
			else:
				ret += lastidentifier

		return ret

	return f

class Macro(object):
	def __init__(self, state=None, macroname=None, args=None, rightside=None):
		self.name = macroname
		self.args = args
		self.rightside = rightside if (rightside is not None) else ""
		self.defPos = state.curPosAsStr() if state else "<unknown>"
		self._tokens = None
	def __str__(self):
		if self.args is not None:
			return "(" + ", ".join(self.args) + ") -> " + self.rightside
		else:
			return "_ -> " + self.rightside
	def __repr__(self):
		return "<Macro: " + str(self) + ">"
	def eval(self, state, args):
		if len(args) != len(self.args or ()): raise TypeError("invalid number of args (" + str(args) + ") for " + repr(self))
		func = parse_macro_def_rightside(state, self.args, self.rightside)
		return func(*args)
	def __call__(self, *args):
		return self.eval(None, args)
	def __eq__(self, other):
		if not isinstance(other, Macro): return False
		return self.args == other.args and self.rightside == other.rightside
	def __ne__(self, other): return not self == other
	def _parseTokens(self, stateStruct):
		assert self.args is None
		if self._tokens is not None: return
		preprocessed = stateStruct.preprocess(self.rightside, None, repr(self))
		self._tokens = list(cpre2_parse(stateStruct, preprocessed))		
	def getSingleIdentifer(self, stateStruct):
		assert self._tokens is not None
		if len(self._tokens) == 1 and isinstance(self._tokens[0], CIdentifier):
			return self._tokens[0].content
		return None
	def getCValue(self, stateStruct):
		tokens = self._tokens
		assert tokens is not None
		
		if all([isinstance(t, (CIdentifier,COp)) for t in tokens]):
			t = tuple([t.content for t in tokens])
			if t in stateStruct.CBuiltinTypes:
				return stateStruct.CBuiltinTypes[t].getCType(stateStruct)
			
		valueStmnt = CStatement()
		input_iter = iter(tokens)
		for token in input_iter:
			if isinstance(token, COpeningBracket):
				valueStmnt._cpre3_parse_brackets(stateStruct, token, input_iter)
			else:
				valueStmnt._cpre3_handle_token(stateStruct, token)
		valueStmnt.finalize(stateStruct)
		
		return valueStmnt.getConstValue(stateStruct)

# either some basic type, another typedef or some complex like CStruct/CUnion/...
class CType(object):
	def __init__(self, **kwargs):
		for k,v in kwargs.items():
			setattr(self, k, v)
	def __repr__(self):
		return self.__class__.__name__ + " " + str(self.__dict__)
	def __eq__(self, other):
		if not hasattr(other, "__class__"): return False
		return self.__class__ is other.__class__ and self.__dict__ == other.__dict__
	def __ne__(self, other): return not self == other
	def __hash__(self): return hash(self.__class__) + 31 * hash(tuple(sorted(self.__dict__.items())))
	def getCType(self, stateStruct):
		raise NotImplementedError(str(self) + " getCType is not implemented")
	def asCCode(self, indent=""):
		raise NotImplementedError(str(self) + " asCCode not implemented")

class CUnknownType(CType):
	def asCCode(self, indent=""): return indent + "/* unknown */ int"
class CVoidType(CType):
	def __repr__(self): return "void"
	def getCType(self, stateStruct): return None
	def asCCode(self, indent=""): return indent + "void"
class CVariadicArgsType(CType):
	def getCType(self, stateStruct): return None
	def asCCode(self, indent=""): return indent + "..."

class CPointerType(CType):
	def __init__(self, ptr): self.pointerOf = ptr
	def getCType(self, stateStruct):
		try:
			t = getCType(self.pointerOf, stateStruct)
			if t is None:
				ptrType = getCType(ctypes.c_void_p, stateStruct)
			else:
				ptrType = ctypes.POINTER(t)
			return ptrType
		except Exception as e:
			stateStruct.error(str(self) + ": error getting type (" + str(e) + "), falling back to void-ptr")
		return getCType(ctypes.c_void_p, stateStruct)
	def asCCode(self, indent=""): return indent + asCCode(self.pointerOf) + "*"

class CBuiltinType(CType):
	def __init__(self, builtinType):
		assert isinstance(builtinType, tuple)
		self.builtinType = builtinType
	def getCType(self, stateStruct):
		t = stateStruct.CBuiltinTypes[self.builtinType]
		return getCType(t, stateStruct)
	def asCCode(self, indent=""): return indent + " ".join(self.builtinType)
	
class CStdIntType(CType):
	def __init__(self, name): self.name = name
	def getCType(self, stateStruct):
		t = stateStruct.StdIntTypes[self.name]
		return getCType(t, stateStruct)
	def asCCode(self, indent=""): return indent + self.name

class CArrayType(CType):
	def __init__(self, arrayOf, arrayLen):
		self.arrayOf = arrayOf
		self.arrayLen = arrayLen
	def getCType(self, stateStruct):
		l = getConstValue(stateStruct, self.arrayLen)
		if l is None:
			stateStruct.error("%s: error getting array len, falling back to 1" % self)
			l = 1
		try:
			t = getCType(self.arrayOf, stateStruct)
			return t * l
		except Exception as e:
			stateStruct.error(str(self) + ": error getting type (" + str(e) + "), falling back to int")
		return ctypes.c_int * l
	def asCCode(self, indent=""): return "%s%s[%s]" % (indent, asCCode(self.arrayOf), asCCode(self.arrayLen))


def getCType(t, stateStruct):
	assert not isinstance(t, CUnknownType)
	try:
		if issubclass(t, (_ctypes._SimpleCData,ctypes._Pointer)):
			if stateStruct.IndirectSimpleCTypes:
				return wrapCTypeClassIfNeeded(t)
			return t
	except Exception: pass # e.g. typeerror or so
	if isinstance(t, (CStruct,CUnion,CEnum)):
		if t.body is None:
			# it probably is the pre-declaration. but we might find the real-one
			if isinstance(t, CStruct): D = "structs"
			elif isinstance(t, CUnion): D = "unions"
			elif isinstance(t, CEnum): D = "enums"
			t = getattr(stateStruct, D).get(t.name, t)
		return t.getCType(stateStruct)
	if isinstance(t, _CBaseWithOptBody):
		return t.getCType(stateStruct)
	if isinstance(t, CType):
		return t.getCType(stateStruct)
	raise Exception(str(t) + " cannot be converted to a C type")

def isSameType(stateStruct, type1, type2):
	ctype1 = getCType(type1, stateStruct)
	ctype2 = getCType(type2, stateStruct)
	return ctype1 == ctype2

def getSizeOf(t, stateStruct):
	t = getCType(t, stateStruct)
	return ctypes.sizeof(t)

class State(object):
	# See _getCTypeStruct for details.
	IndirectSimpleCTypes = False
	
	EmptyMacro = Macro(None, None, (), "")
	CBuiltinTypes = {
		("void",): CVoidType(),
		("void", "*"): ctypes.c_void_p,
		("char",): ctypes.c_byte,
		("unsigned", "char"): ctypes.c_ubyte,
		("short",): ctypes.c_short,
		("unsigned", "short"): ctypes.c_ushort,
		("int",): ctypes.c_int,
		("signed",): ctypes.c_int,
		("unsigned", "int"): ctypes.c_uint,
		("unsigned",): ctypes.c_uint,
		("long",): ctypes.c_long,
		("unsigned", "long"): ctypes.c_ulong,
		("long", "long"): ctypes.c_longlong,
		("unsigned", "long", "long"): ctypes.c_ulonglong,
		("float",): ctypes.c_float,
		("double",): ctypes.c_double,
		("long", "double"): ctypes.c_longdouble,
	}
	StdIntTypes = {
		"uint8_t": ctypes.c_uint8,
		"uint16_t": ctypes.c_uint16,
		"uint32_t": ctypes.c_uint32,
		"uint64_t": ctypes.c_uint64,
		"int8_t": ctypes.c_int8,
		"int16_t": ctypes.c_int16,
		"int32_t": ctypes.c_int32,
		"int64_t": ctypes.c_int64,
		"byte": ctypes.c_byte,
		"wchar_t": ctypes.c_wchar,
		"size_t": ctypes.c_size_t,
		"ptrdiff_t": ctypes.c_long,
		"intptr_t": ctypes.c_long,
		"FILE": ctypes.c_int, # NOTE: not really correct but shouldn't matter unless we directly access it
	}
	Attribs = [
		"const",
		"extern",
		"static",
		"register",
		"volatile",
		"__inline__",
		"inline",
	]
	
	def __init__(self):
		self.parent = None
		self.macros = {} # name -> Macro
		self.typedefs = {} # name -> type
		self.structs = {} # name -> CStruct
		self.unions = {} # name -> CUnion
		self.enums = {} # name -> CEnum
		self.funcs = {} # name -> CFunc
		self.vars = {} # name -> CVarDecl
		self.enumconsts = {} # name -> CEnumConst
		self.contentlist = []
		self._preprocessIfLevels = []
		self._preprocessIgnoreCurrent = False
		# 0->didnt got true yet, 1->in true part, 2->after true part. and that as a stack
		self._preprocessIncludeLevel = []
		self._errors = []
		self._global_include_wrapper = None
	
	def autoSetupSystemMacros(self, system_specific=False):
		import sys
		self.macros["__attribute__"] = Macro(args=("x",), rightside="")
		self.macros["__GNUC__"] = Macro(rightside="4") # most headers just behave more sane with this :)
		self.macros["__GNUC_MINOR__"] = Macro(rightside="2")
		#self.macros["UINT64_C"] = Macro(args=("C"), rightside= "C##ui64") # or move to stdint.h handler?
		if system_specific and sys.platform == "darwin":
			self.macros["__APPLE__"] = self.EmptyMacro
			self.macros["__MACH__"] = self.EmptyMacro
			self.macros["__MACOSX__"] = self.EmptyMacro
			self.macros["i386"] = self.EmptyMacro
			self.macros["MAC_OS_X_VERSION_MIN_REQUIRED"] = Macro(rightside="1030")
	
	def autoSetupGlobalIncludeWrappers(self):
		if self._global_include_wrapper: return
		from globalincludewrappers import Wrapper
		self._global_include_wrapper = Wrapper(self)
		self._global_include_wrapper.install()

	def incIncludeLineChar(self, fullfilename=None, inc=None, line=None, char=None, charMod=None):
		CharStartIndex = 0
		LineStartIndex = 1
		if inc is not None:
			self._preprocessIncludeLevel += [[fullfilename, inc, LineStartIndex, CharStartIndex]]
		if len(self._preprocessIncludeLevel) == 0:
			self._preprocessIncludeLevel += [[None, "<input>", LineStartIndex, CharStartIndex]]
		if line is not None:
			self._preprocessIncludeLevel[-1][2] += line
			self._preprocessIncludeLevel[-1][3] = CharStartIndex
		if char is not None:
			c = self._preprocessIncludeLevel[-1][3]
			c += char
			if charMod is not None:
				c = c - (c - CharStartIndex) % charMod + CharStartIndex
			self._preprocessIncludeLevel[-1][3] = c
	
	def curPosAsStr(self):
		if len(self._preprocessIncludeLevel) == 0: return "<out-of-scope>"
		l = self._preprocessIncludeLevel[-1]
		return ":".join([l[1], str(l[2]), str(l[3])])

	def curFile(self):
		if not self._preprocessIncludeLevel: return "<out-of-scope>"
		return self._preprocessIncludeLevel[-1][1]

	def curLine(self):
		if not self._preprocessIncludeLevel: return -1
		return self._preprocessIncludeLevel[-1][2]

	def error(self, s):
		self._errors.append(self.curPosAsStr() + ": " + s)

	def log(self, *args):
		print(self.curPosAsStr() + ": " + " ".join(map(str, args)))

	def findIncludeFullFilename(self, filename, local):
		if local:
			dir = ""
			if filename[0] != "/":
				if self._preprocessIncludeLevel and self._preprocessIncludeLevel[-1][0]:
					import os.path
					dir = os.path.dirname(self._preprocessIncludeLevel[-1][0])
				if not dir: dir = "."
				dir += "/"
		else:
			dir = ""

		fullfilename = dir + filename
		return fullfilename
	
	def readLocalInclude(self, filename):
		fullfilename = self.findIncludeFullFilename(filename, True)
		
		try:
			import codecs
			f = codecs.open(fullfilename, "r", "utf-8")
		except Exception as e:
			self.error("cannot open local include-file '" + filename + "': " + str(e))
			return "", None
		
		def reader():
			while True:
				c = f.read(1)
				if len(c) == 0: break
				yield c
		reader = reader()
		
		return reader, fullfilename

	def readGlobalInclude(self, filename):
		if filename == "inttypes.h": return "", None # we define those types as builtin-types
		elif filename == "stdint.h": return "", None
		else:
			self.error("no handler for global include-file '" + filename + "'")
			return "", None

	def preprocess_file(self, filename, local):
		if local:
			reader, fullfilename = self.readLocalInclude(filename)
		else:
			reader, fullfilename = self.readGlobalInclude(filename)

		for c in self.preprocess(reader, fullfilename, filename):
			yield c

	def preprocess_source_code(self, source_code, dummy_filename="<input>"):
		for c in self.preprocess(source_code, dummy_filename, dummy_filename):
			yield c

	def preprocess(self, reader, fullfilename, filename):
		self.incIncludeLineChar(fullfilename=fullfilename, inc=filename)
		for c in cpreprocess_parse(self, reader):
			yield c		
		self._preprocessIncludeLevel = self._preprocessIncludeLevel[:-1]		

	def depth(self): return 0


def is_valid_defname(defname):
	if not defname: return False
	gotValidPrefix = False
	for c in defname:
		if c in LetterChars + "_":
			gotValidPrefix = True
		elif c in NumberChars:
			if not gotValidPrefix: return False
		else:
			return False
	return True

def cpreprocess_evaluate_ifdef(state, arg):
	arg = arg.strip()
	if not is_valid_defname(arg):
		state.error("preprocessor: '" + arg + "' is not a valid macro name")
		return False
	if arg in ("__FILE__", "__LINE__"): return True
	return arg in state.macros

def cpreprocess_evaluate_single(state, arg):
	if arg == "": return None
	try: return int(arg) # is integer?
	except ValueError: pass
	try: return long(arg) # is long?
	except ValueError: pass
	try: return int(arg, 16) # is hex?
	except ValueError: pass
	if len(arg) >= 2 and arg[0] == '"' and arg[-1] == '"': return arg[1:-1] # is string?
	
	if not is_valid_defname(arg):
		state.error("preprocessor eval single: '" + arg + "' is not a valid macro name")
		return 0
	if arg not in state.macros:
		# This is not an error.
		return 0
	try:
		resolved = state.macros[arg]()
	except Exception as e:
		state.error("preprocessor eval single error on '" + arg + "': " + str(e))
		return 0
	return cpreprocess_evaluate_cond(state, resolved)

def cpreprocess_evaluate_cond(stateStruct, condstr):
	state = 0
	bracketLevel = 0
	substr = ""
	laststr = ""
	lasteval = None
	op = None
	prefixOp = None
	opstr = ""
	args = []
	i = 0
	while i < len(condstr):
		c = condstr[i]
		i += 1
		breakLoop = False
		while not breakLoop:
			breakLoop = True
			
			if state == 0:
				if c == "(":
					if laststr == "":
						state = 1
						bracketLevel = 1
					else:
						state = 10
						breakLoop = False
				elif c == ")":
					stateStruct.error("preprocessor: runaway ')' in " + repr(condstr))
					return
				elif c in SpaceChars:
					if laststr == "defined": state = 5 
					elif laststr != "": state = 10
					else: pass
				elif c in OpChars:
					state = 10
					breakLoop = False
				elif c == '"':
					if laststr == "":
						state = 20
					else:
						stateStruct.error("preprocessor: '\"' not expected")
						return
				elif c == "'":
					if laststr == "":
						state = 22
					else:
						stateStruct.error("preprocessor: \"'\" not expected")
						return
				else:
					laststr += c
			elif state == 1: # in bracket
				if c == "(":
					bracketLevel += 1
				if c == ")":
					bracketLevel -= 1
					if bracketLevel == 0:
						neweval = cpreprocess_evaluate_cond(stateStruct, substr)
						state = 18
						if prefixOp is not None:
							neweval = prefixOp(neweval)
							prefixOp = None
						if op is not None: lasteval = op(lasteval, neweval)
						else: lasteval = neweval
						substr = ""
					else: # bracketLevel > 0
						substr += c
				elif c == '"':
					state = 2
					substr += c
				else:
					substr += c
			elif state == 2: # in str in bracket
				substr += c
				if c == "\\": state = 3
				elif c == '"': state = 1
				else: pass
			elif state == 3: # in escape in str in bracket
				substr += c
				state = 2
			elif state == 5: # after "defined" without brackets (yet)
				if c in SpaceChars: pass
				elif c == "(":
					state = 10
					breakLoop = False
				elif c == ")":
					stateStruct.error("preprocessor eval: 'defined' invalid in '" + condstr + "'")
					return
				else:
					laststr = c
					state = 6
			elif state == 6: # chars after "defined"
				if c in LetterChars + "_" + NumberChars:
					laststr += c
				else:
					macroname = laststr
					if not is_valid_defname(macroname):
						stateStruct.error("preprocessor eval defined-check: '" + macroname + "' is not a valid macro name")
						return
					neweval = macroname in stateStruct.macros
					if prefixOp is not None:
						neweval = prefixOp(neweval)
						prefixOp = None
					oldlast = lasteval
					if op is not None: lasteval = op(lasteval, neweval)
					else: lasteval = neweval
					opstr = ""
					laststr = ""
					state = 18
					breakLoop = False
			elif state == 10: # after identifier
				if c in SpaceChars: pass
				elif c in OpChars:
					if laststr != "":
						neweval = cpreprocess_evaluate_single(stateStruct, laststr)
						if prefixOp is not None:
							neweval = prefixOp(neweval)
							prefixOp = None
						if op is not None: lasteval = op(lasteval, neweval)
						else: lasteval = neweval
						laststr = ""
					opstr = ""
					state = 18
					breakLoop = False
				elif c == "(":
					state = 11
					bracketLevel = 1
					args = []
				else:
					stateStruct.error("preprocessor eval: '" + c + "' not expected after '" + laststr + "' in state 10 with '" + condstr + "'")
					return
			elif state == 11: # after "(" after identifier
				if c == "(":
					if len(args) == 0: args = [""]
					args[-1] += c
					bracketLevel += 1
					state = 12
				elif c == ")":
					macroname = laststr
					if macroname == "defined":
						if len(args) != 1:
							stateStruct.error("preprocessor eval defined-check args invalid: " + str(args))
							return
						else:
							macroname = args[0]
							if not is_valid_defname(macroname):
								stateStruct.error("preprocessor eval defined-check: '" + macroname + "' is not a valid macro name")
								return
							neweval = macroname in stateStruct.macros
					else:
						if not is_valid_defname(macroname):
							stateStruct.error("preprocessor eval call: '" + macroname + "' is not a valid macro name in " + repr(condstr))
							return
						if macroname not in stateStruct.macros:
							stateStruct.error("preprocessor eval call: '" + macroname + "' is unknown")
							return
						macro = stateStruct.macros[macroname]
						try:
							resolved = macro.eval(stateStruct, args)
						except Exception as e:
							stateStruct.error("preprocessor eval call on '" + macroname + "': error " + str(e))
							return
						neweval = cpreprocess_evaluate_cond(stateStruct, resolved)
					
					if prefixOp is not None:
						neweval = prefixOp(neweval)
						prefixOp = None
					oldlast = lasteval
					if op is not None: lasteval = op(lasteval, neweval)
					else: lasteval = neweval
					#print "after ):", laststr, args, neweval, op.func_code.co_firstlineno if op else "no-op", oldlast, "->", lasteval
					laststr = ""
					opstr = ""
					state = 18
				elif c == '"':
					if len(args) == 0: args = [""]
					args[-1] += c
					state = 13
				elif c == ",": args += [""]
				else:
					if len(args) == 0: args = [""]
					args[-1] += c
			elif state == 12: # in additional "(" after "(" after identifier
				args[-1] += c
				if c == "(": bracketLevel += 1
				elif c == ")":
					bracketLevel -= 1
					if bracketLevel == 1: state = 11
				elif c == '"': state = 13
				else: pass
			elif state == 13: # in str after "(" after identifier
				args[-1] += c
				if c == "\\": state = 14
				elif c == '"':
					if bracketLevel > 1: state = 12
					else: state = 11
				else: pass
			elif state == 14: # in escape in str after "(" after identifier
				args[-1] += c
				state = 13
			elif state == 18: # op after identifier/expression
				if c in OpChars: opstr += c
				else:
					if opstr == "":
						if c in SpaceChars: pass
						else:
							stateStruct.error("preprocessor eval: expected op but got '" + c + "' in '" + condstr + "' in state 18")
							return
					else:
						if opstr == "&&":
							op = lambda x,y: x and y
							# short path check
							if not lasteval: return lasteval
						elif opstr == "||":
							op = lambda x,y: x or y
							# short path check
							if lasteval: return lasteval
						elif opstr in OpBinFuncs:
							op = OpBinFuncs[opstr]
							# HACK: add "()" in some way...
							j = i
							while j < len(condstr):
								if condstr[j] == "'":
									j += 1
									while j < len(condstr):
										if condstr[j] == "'": break
										if condstr[j] == "\\": j += 1
										j += 1
									continue
								if condstr[j] == '"':
									j += 1
									while j < len(condstr):
										if condstr[j] == '"': break
										if condstr[j] == "\\": j += 1
										j += 1
									continue
								if condstr[j] in OpChars:
									nextopstr = ""
									while j < len(condstr) and condstr[j] in OpChars:
										nextopstr += condstr[j]
										j += 1
									if nextopstr in OpBinFuncs:
										if OpPrecedences[opstr] > OpPrecedences[nextopstr]:
											condstr = condstr[:i] + "(" + condstr[i:] + ")"
									#if j < len(condstr):
									#	condstr = condstr[:j] + "(" + condstr[j:] + ")"
									break
								j += 1
						elif opstr in OpPrefixFuncs:
							newprefixop = OpPrefixFuncs[opstr]
							if prefixOp: prefixOp = lambda x: prefixOp(newprefixop(x))
							else: prefixOp = newprefixop
						else:
							stateStruct.error("invalid op '" + opstr + "' with '" + c + "' following in '" + condstr + "'")
							return
						opstr = ""
						laststr = ""
						state = 0
						breakLoop = False
			elif state == 20: # in str
				if c == "\\": state = 21
				elif c == '"':
					state = 0
					neweval = laststr
					laststr = ""
					if prefixOp is not None:
						neweval = prefixOp(neweval)
						prefixOp = None
					if op is not None: lasteval = op(lasteval, neweval)
					else: lasteval = neweval
				else: laststr += c
			elif state == 21: # in escape in str
				laststr += simple_escape_char(c)
				state = 20
			elif state == 22: # in char
				if c == "\\": state = 23
				elif c == "'":
					state = 0
					neweval = laststr
					laststr = ""
					if prefixOp is not None:
						neweval = prefixOp(neweval)
						prefixOp = None
					if op is not None: lasteval = op(lasteval, neweval)
					else: lasteval = neweval
				else: laststr += c
			elif state == 23: # in escape in char
				laststr += simple_escape_char(c)
				state = 22
			else:
				stateStruct.error("internal error in preprocessor evaluation: state " + str(state))
				return
	
	if state in (0,10):
		if laststr != "":
			neweval = cpreprocess_evaluate_single(stateStruct, laststr)
			if prefixOp is not None:
				neweval = prefixOp(neweval)
				prefixOp = None
			if op is not None: lasteval = op(lasteval, neweval)
			else: lasteval = neweval
	elif state == 6:
		macroname = laststr
		if not is_valid_defname(macroname):
			stateStruct.error("preprocessor eval defined-check: '" + macroname + "' is not a valid macro name")
			return
		neweval = macroname in stateStruct.macros
		if prefixOp is not None:
			neweval = prefixOp(neweval)
			prefixOp = None
		oldlast = lasteval
		if op is not None: lasteval = op(lasteval, neweval)
		else: lasteval = neweval
	elif state == 18: # expected op
		if opstr != "":
			stateStruct.error("preprocessor eval: unfinished op: '" + opstr + "'")
		else: pass
	else:
		stateStruct.error("preprocessor eval: invalid argument: '" + condstr + "'. unfinished state " + str(state))
	
	#print "eval:", condstr, "->", lasteval
	return lasteval

def cpreprocess_handle_include(state, arg):
	arg = arg.strip()
	if len(arg) < 2:
		state.error("invalid include argument: '" + arg + "'")
		return
	if arg[0] == '"' and arg[-1] == '"':
		local = True
		filename = arg[1:-1]
	elif arg[0] == "<" and arg[-1] == ">":
		local = False
		filename = arg[1:-1]
	else:
		state.error("invalid include argument: '" + arg + "'")
		return
	for c in state.preprocess_file(filename=filename, local=local): yield c

def cpreprocess_handle_def(stateStruct, arg):
	state = 0
	macroname = ""
	args = None
	rightside = ""
	for c in arg:
		if state == 0:
			if c in SpaceChars:
				if macroname != "": state = 3
			elif c == "(":
				state = 2
				args = []
			else: macroname += c
		elif state == 2: # after "("
			if c in SpaceChars: pass
			elif c == ",": args += [""]
			elif c == ")": state = 3
			else:
				if not args: args = [""]
				args[-1] += c
		elif state == 3: # rightside
			rightside += c
	
	if not is_valid_defname(macroname):
		stateStruct.error("preprocessor define: '" + macroname + "' is not a valid macro name")
		return

	if macroname in stateStruct.macros:
		stateStruct.error("preprocessor define: '" + macroname + "' already defined." +
						  " previously defined at " + stateStruct.macros[macroname].defPos)
		# pass through to use new definition
	
	macro = Macro(stateStruct, macroname, args, rightside)
	stateStruct.macros[macroname] = macro
	return macro

def cpreprocess_handle_undef(state, arg):
	arg = arg.strip()
	if not is_valid_defname(arg):
		state.error("preprocessor: '" + arg + "' is not a valid macro name")
		return
	if not arg in state.macros:
		# This is not an error. Just ignore.
		return
	state.macros.pop(arg)
	
def handle_cpreprocess_cmd(state, cmd, arg):
	#if not state._preprocessIgnoreCurrent:
	#	print "cmd", cmd, arg

	if cmd == "ifdef":
		state._preprocessIfLevels += [0]
		if any(map(lambda x: x != 1, state._preprocessIfLevels[:-1])): return # we don't really care
		check = cpreprocess_evaluate_ifdef(state, arg)
		if check: state._preprocessIfLevels[-1] = 1
		
	elif cmd == "ifndef":
		state._preprocessIfLevels += [0]
		if any(map(lambda x: x != 1, state._preprocessIfLevels[:-1])): return # we don't really care
		check = not cpreprocess_evaluate_ifdef(state, arg)
		if check: state._preprocessIfLevels[-1] = 1

	elif cmd == "if":
		state._preprocessIfLevels += [0]
		if any(map(lambda x: x != 1, state._preprocessIfLevels[:-1])): return # we don't really care
		check = cpreprocess_evaluate_cond(state, arg)
		if check: state._preprocessIfLevels[-1] = 1
		
	elif cmd == "elif":
		if any(map(lambda x: x != 1, state._preprocessIfLevels[:-1])): return # we don't really care
		if len(state._preprocessIfLevels) == 0:
			state.error("preprocessor: elif without if")
			return
		if state._preprocessIfLevels[-1] >= 1:
			state._preprocessIfLevels[-1] = 2 # we already had True
		else:
			check = cpreprocess_evaluate_cond(state, arg)
			if check: state._preprocessIfLevels[-1] = 1

	elif cmd == "else":
		if any(map(lambda x: x != 1, state._preprocessIfLevels[:-1])): return # we don't really care
		if len(state._preprocessIfLevels) == 0:
			state.error("preprocessor: else without if")
			return
		if state._preprocessIfLevels[-1] >= 1:
			state._preprocessIfLevels[-1] = 2 # we already had True
		else:
			state._preprocessIfLevels[-1] = 1
	
	elif cmd == "endif":
		if len(state._preprocessIfLevels) == 0:
			state.error("preprocessor: endif without if")
			return
		state._preprocessIfLevels = state._preprocessIfLevels[0:-1]
	
	elif cmd == "include":
		if state._preprocessIgnoreCurrent: return
		for c in cpreprocess_handle_include(state, arg): yield c

	elif cmd == "define":
		if state._preprocessIgnoreCurrent: return
		cpreprocess_handle_def(state, arg)
	
	elif cmd == "undef":
		if state._preprocessIgnoreCurrent: return
		cpreprocess_handle_undef(state, arg)
				
	elif cmd == "pragma":
		pass # ignore at all right now
	
	elif cmd == "error":
		if state._preprocessIgnoreCurrent: return # we don't really care
		state.error("preprocessor error command: " + arg)

	elif cmd == "warning":
		if state._preprocessIgnoreCurrent: return # we don't really care
		state.error("preprocessor warning command: " + arg)

	else:
		if state._preprocessIgnoreCurrent: return # we don't really care
		state.error("preprocessor command " + cmd + " unknown")
		
	state._preprocessIgnoreCurrent = any(map(lambda x: x != 1, state._preprocessIfLevels))

def cpreprocess_parse(stateStruct, input):
	"""
	:type stateStruct: State
	:param str | iterable[char] input: not-yet preprocessed C code
	:returns preprocessed C code, iterator of chars
	This removes comments and can skip over parts, which is controlled by
	the C preprocessor commands (`#if 0` parts or so).
	We will not do C preprocessor macro substitutions here.
	The next func which gets this output is cpre2_parse().
	"""
	cmd = ""
	arg = ""
	state = 0
	statebeforecomment = None
	for c in input:		
		breakLoop = False
		while not breakLoop:
			breakLoop = True

			if state == 0:
				if c == "#":
					cmd = ""
					arg = None
					state = 1
				elif c == "/":
					statebeforecomment = 0
					state = 20
				elif c == '"':
					if not stateStruct._preprocessIgnoreCurrent: yield c
					state = 10
				elif c == "'":
					if not stateStruct._preprocessIgnoreCurrent: yield c
					state = 12
				else:
					if not stateStruct._preprocessIgnoreCurrent: yield c
			elif state == 1: # start of preprocessor command
				if c in SpaceChars: pass
				elif c == "\n": state = 0
				else:
					cmd = c
					state = 2
			elif state == 2: # in the middle of the preprocessor command
				if c in SpaceChars:
					if arg is None: arg = ""
					else: arg += c
				elif c == "(":
					if arg is None: arg = c
					else: arg += c
				elif c == "/":
					state = 20
					statebeforecomment = 2
				elif c == '"':
					state = 3
					if arg is None: arg = ""
					arg += c
				elif c == "'":
					state = 4
					if arg is None: arg = ""
					arg += c
				elif c == "\\": state = 5 # escape next
				elif c == "\n":
					for c in handle_cpreprocess_cmd(stateStruct, cmd, arg): yield c
					state = 0
				else:
					if arg is None: cmd += c
					else: arg += c
			elif state == 3: # in '"' in arg in command
				arg += c
				if c == "\n":
					stateStruct.error("preproc parse: unfinished str")
					state = 0
				elif c == "\\": state = 35
				elif c == '"': state = 2
			elif state == 35: # in esp in '"' in arg in command
				arg += c
				state = 3
			elif state == 4: # in "'" in arg in command
				arg += c
				if c == "\n":
					stateStruct.error("preproc parse: unfinished char str")
					state = 0
				elif c == "\\": state = 45
				elif c == "'": state = 2
			elif state == 45: # in esp in "'" in arg in command
				arg += c
				state = 4
			elif state == 5: # after escape in arg in command
				if c == "\n": state = 2
				else: pass # ignore everything, wait for newline
			elif state == 10: # after '"'
				if not stateStruct._preprocessIgnoreCurrent: yield c
				if c == "\\": state = 11
				elif c == '"': state = 0
				else: pass
			elif state == 11: # escape in "str
				if not stateStruct._preprocessIgnoreCurrent: yield c
				state = 10
			elif state == 12: # after "'"
				if not stateStruct._preprocessIgnoreCurrent: yield c
				if c == "\\": state = 13
				elif c == "'": state = 0
				else: pass
			elif state == 13: # escape in 'str
				if not stateStruct._preprocessIgnoreCurrent: yield c
				state = 12
			elif state == 20: # after "/", possible start of comment
				if c == "*": state = 21 # C-style comment
				elif c == "/": state = 25 # C++-style comment
				else:
					state = statebeforecomment
					statebeforecomment = None
					if state == 0:
						if not stateStruct._preprocessIgnoreCurrent:
							yield "/"
							yield c
					elif state == 2:
						if arg is None: arg = ""
						arg += "/" + c
						breakLoop = False
					else:
						stateStruct.error("preproc parse: internal error after possible comment. didn't expect state " + str(state))
						state = 0 # best we can do
			elif state == 21: # C-style comment
				if c == "*": state = 22
				else: pass
			elif state == 22: # C-style comment after "*"
				if c == "/":
					state = statebeforecomment
					statebeforecomment = None
				elif c == "*": pass
				else: state = 21
			elif state == 25: # C++-style comment
				if c == "\n":
					state = statebeforecomment
					statebeforecomment = None
					breakLoop = False # rehandle return
				else: pass
			else:
				stateStruct.error("internal error: invalid state " + str(state))
				state = 0 # reset. it's the best we can do

		if c == "\n": stateStruct.incIncludeLineChar(line=1)
		elif c == "\t": stateStruct.incIncludeLineChar(char=4, charMod=4)
		else: stateStruct.incIncludeLineChar(char=1)

	# yield dummy additional new-line at end
	yield "\n"

class _CBase(object):
	def __init__(self, content=None, rawstr=None, **kwargs):
		self.content = content
		self.rawstr = rawstr
		for k,v in kwargs.items():
			setattr(self, k, v)
	def __repr__(self):
		if self.content is None: return "<" + self.__class__.__name__ + ">"
		return "<" + self.__class__.__name__ + " " + repr(self.content) + ">"
	def __eq__(self, other):
		return self.__class__ is other.__class__ and self.content == other.content
	def __ne__(self, other):
		return not self == other
	def __hash__(self): return hash(self.__class__) + 31 * hash(self.content)
	def asCCode(self, indent=""): return indent + self.content

class CStr(_CBase):
	def __repr__(self): return "<" + self.__class__.__name__ + " " + repr(self.content) + ">"
	def asCCode(self, indent=""): return indent + '"' + escape_cstr(self.content) + '"'
class CChar(_CBase):
	def __init__(self, content=None, rawstr=None, **kwargs):
		if isinstance(content, (unicode,str)): content = ord(content)
		assert isinstance(content, int), "CChar expects int, got " + repr(content)
		assert 0 <= content <= 255, "CChar expects number in range 0-255, got " + str(content)
		_CBase.__init__(self, content, rawstr, **kwargs)
	def __repr__(self): return "<" + self.__class__.__name__ + " " + repr(self.content) + ">"
	def asCCode(self, indent=""):
		if isinstance(self.content, str):
			return indent + "'" + escape_cstr(self.content) + "'"
		else:
			assert isinstance(self.content, int)
			return indent + "'" + escape_cstr(chr(self.content)) + "'"
class CNumber(_CBase):
	typeSpec = None  # prefix like "f", "i" or so, or None
	def asCCode(self, indent=""): return indent + self.rawstr
class CIdentifier(_CBase): pass
class COp(_CBase): pass
class CSemicolon(_CBase):
	def asCCode(self, indent=""): return indent + ";"	
class COpeningBracket(_CBase): pass
class CClosingBracket(_CBase): pass

def cpre2_parse_number(stateStruct, s):
	if len(s) > 1 and s[0] == "0" and s[1] in NumberChars:
		try:
			s = s.rstrip("ULul")
			return long(s, 8)
		except Exception as e:
			stateStruct.error("cpre2_parse_number: " + s + " looks like octal but got error " + str(e))
			return 0
	if len(s) > 1 and s[0] == "0" and s[1] in "xX":
		try:
			s = s.rstrip("ULul")
			return long(s, 16)
		except Exception as e:
			stateStruct.error("cpre2_parse_number: " + s + " looks like hex but got error " + str(e))
			return 0
	try:
		s = s.rstrip("ULul")
		return long(s)
	except Exception as e:
		stateStruct.error("cpre2_parse_number: " + s + " cannot be parsed: " + str(e))
		return 0

def _cpre2_parse_args(stateStruct, input, brackets, separator=COp(",")):
	"""
	:type stateStruct: State
	:param iterable[char] input: like cpre2_parse
	:param list[str] brackets: opening brackets stack
	:param sep_type: the separator type, e.g. CSemicolon or COp
	:returns list of args, where each arg is a list of tokens from cpre2_parse.
	:rtype: list[list[token]]
	"""
	initial_bracket_len = len(brackets)
	args = []
	for s in cpre2_parse(stateStruct, input, brackets=brackets):
		if len(brackets) < initial_bracket_len:
			# We got the final closing bracket. We have finished parsing the args.
			assert isinstance(s, CClosingBracket)
			assert len(brackets) == initial_bracket_len - 1
			return args
		if len(brackets) == initial_bracket_len and s == separator:
			args.append("")
		else:
			if not args: args.append("")
			args[-1] += " " + s.asCCode()
	stateStruct.error("cpre2 parse args: runaway")
	return args

class _Pre2ParseStream:
	def __init__(self, input):
		self.input = input
		self.macro_blacklist = set()
		self.buffer_stack = [[None, ""]]  # list[(macroname,buffer)]

	def next_char(self):
		for i in reversed(range(len(self.buffer_stack))):
			if not self.buffer_stack[i][1]: continue
			c = self.buffer_stack[i][1][0]
			self.buffer_stack[i][1] = self.buffer_stack[i][1][1:]
			# finalize handling will be in finalize_char()
			return c
		try:
			return next(self.input)
		except StopIteration:
			return None

	def add_macro(self, macroname, resolved, c):
		self.buffer_stack += [[macroname, resolved]]
		self.macro_blacklist.add(macroname)
		self.buffer_stack[-2][1] = c + self.buffer_stack[-2][1]

	def finalize_char(self, laststr):
		# Finalize buffer_stack here. Here because the macro_blacklist needs to be active
		# in the code above.
		if not laststr and len(self.buffer_stack) > 1 and not self.buffer_stack[-1][1]:
			self.macro_blacklist.remove(self.buffer_stack[-1][0])
			self.buffer_stack = self.buffer_stack[:-1]

def cpre2_parse(stateStruct, input, brackets=None):
	"""
	:type stateStruct: State
	:param str | iterable[char] | _Pre2ParseStream input: chars of preprocessed C code.
		except of macro substitution. usually via cpreprocess_parse().
	:param list[str] | None brackets: opening brackets stack
	:returns token iterator. this will also substitute macros
	The input comes more or less from cpreprocess_parse().
	This output will be handled by cpre3_parse().
	"""
	state = 0
	if brackets is None: brackets = []
	if not isinstance(input, _Pre2ParseStream):
		input = _Pre2ParseStream(input)
	laststr = ""
	macroname = ""
	macroargs = []
	while True:
		c = input.next_char()
		if c is None:
			break
		breakLoop = False
		while not breakLoop:
			breakLoop = True
			if state == 0:
				if c in SpaceChars + "\n": pass
				elif c in NumberChars:
					laststr = c
					state = 10
				elif c == '"':
					laststr = ""
					state = 20
				elif c == "'":
					laststr = ""
					state = 25
				elif c in LetterChars + "_":
					laststr = c
					state = 30
				elif c in OpeningBrackets:
					yield COpeningBracket(c, brackets=list(brackets))
					brackets.append(c)
				elif c in ClosingBrackets:
					if len(brackets) == 0 or ClosingBrackets[len(OpeningBrackets) - OpeningBrackets.index(brackets[-1]) - 1] != c:
						stateStruct.error("cpre2 parse: got '" + c + "' but bracket level was " + str(brackets))
					else:
						brackets[:] = brackets[:-1]
						yield CClosingBracket(c, brackets=list(brackets))
				elif c in OpChars:
					laststr = ""
					state = 40
					breakLoop = False
				elif c == ";": yield CSemicolon()
				elif c == "\\": state = 1
				else:
					stateStruct.error("cpre2 parse: didn't expected char %r in state %i" % (c, state))
			elif state == 1: # escape without context
				if c != "\n":
					stateStruct.error("cpre2 parse: didn't expected char %r in state %i" % (c, state))
				# Just ignore it in any case.
				state = 0
			elif state == 10: # number (no correct float handling, will be [number, op("."), number])
				if c in NumberChars: laststr += c
				elif c in LetterChars + "_": laststr += c # error handling will be in number parsing, not here
				else:
					yield CNumber(cpre2_parse_number(stateStruct, laststr), laststr)
					laststr = ""
					state = 0
					breakLoop = False
			elif state == 20: # "str
				if c == '"':
					yield CStr(laststr)
					laststr = ""
					state = 0
				elif c == "\\": state = 21
				else: laststr += c
			elif state == 21: # escape in "str
				laststr += simple_escape_char(c)
				state = 20
			elif state == 25: # 'str
				if c == "'":
					if len(laststr) > 1 and laststr[0] == '\0':  # hacky check for '\0abc'-like strings.
						yield CChar(int(laststr[1:], 8))
					else:
						yield CChar(laststr)
					laststr = ""
					state = 0
				elif c == "\\": state = 26
				else: laststr += c
			elif state == 26: # escape in 'str
				laststr += simple_escape_char(c)
				state = 25
			elif state == 30: # identifier
				if c in NumberChars + LetterChars + "_": laststr += c
				else:
					if laststr in stateStruct.macros and laststr not in input.macro_blacklist:
						macroname = laststr
						macroargs = []
						state = 31
						if stateStruct.macros[macroname].args is None:
							state = 32 # finalize macro directly. there can't be any args
						breakLoop = False
						laststr = ""
					else:
						if laststr == "__FILE__":
							yield CStr(stateStruct.curFile())
						elif laststr == "__LINE__":
							yield CNumber(stateStruct.curLine())
						else:
							yield CIdentifier(laststr)
						laststr = ""
						state = 0
						breakLoop = False
			elif state == 31: # after macro identifier
				if c in SpaceChars + "\n": pass
				elif c in OpeningBrackets:
					if c != "(":
						state = 32
						breakLoop = False
					else:
						macroargs = _cpre2_parse_args(stateStruct, input, brackets=brackets + [c])
						state = 32
						# break loop, we consumed this char
				else:
					state = 32
					breakLoop = False
			elif state == 32: # finalize macro
				try:
					resolved = stateStruct.macros[macroname].eval(stateStruct, macroargs)
				except Exception as e:
					stateStruct.error("cpre2 parse unfold macro " + macroname + " error: " + repr(e))
					resolved = ""
				input.add_macro(macroname, resolved, c)
				state = 0
			elif state == 40: # op
				if c in OpChars:
					if laststr != "" and laststr + c not in LongOps:
						yield COp(laststr)
						laststr = ""
					laststr += c
				else:
					yield COp(laststr)
					laststr = ""
					state = 0
					breakLoop = False
			else:
				stateStruct.error("cpre2 parse: internal error. didn't expected state " + str(state))
		input.finalize_char(laststr)

def cpre2_tokenstream_asCCode(input):
	needspace = False
	wantnewline = False
	indentLevel = ""
	needindent = False
	
	for token in input:
		if wantnewline:
			if isinstance(token, CSemicolon): pass
			else:
				yield "\n"
				needindent = True
			wantnewline = False
			needspace = False
		elif needspace:
			if isinstance(token, CSemicolon): pass
			elif token == COpeningBracket("("): pass
			elif token == CClosingBracket(")"): pass
			elif token == COpeningBracket("["): pass
			elif token == CClosingBracket("]"): pass
			elif token in [COp("++"), COp("--"), COp(",")]: pass
			else:
				yield " "
			needspace = False
		
		if token == CClosingBracket("}"): indentLevel = indentLevel[:-1]
		if needindent:
			yield indentLevel
			needindent = False
			
		yield token.asCCode()
		
		if token == COpeningBracket("{"): indentLevel += "\t"
		
		if token == CSemicolon(): wantnewline = True
		elif token == COpeningBracket("{"): wantnewline = True
		elif token == CClosingBracket("}"): wantnewline = True
		elif isinstance(token, COpeningBracket): pass
		elif isinstance(token, CClosingBracket): pass
		else: needspace = True

	
class CBody(object):
	def __init__(self, parent):
		self.parent = parent
		self._bracketlevel = []
		self.typedefs = {}
		self.structs = {}
		self.unions = {}
		self.enums = {}
		self.funcs = {}
		self.vars = {}
		self.enumconsts = {}
		self.contentlist = []
	def __str__(self): return "CBody %s" % self.contentlist
	def __repr__(self): return "<%s>" % self
	def asCCode(self, indent=""):
		s = indent + "{\n"
		for c in self.contentlist:
			s += asCCode(c, indent + "\t", fullDecl=True) + ";\n"
		s += indent + "}"
		return s
	
class CEnumBody(CBody):
	def asCCode(self, indent=""):
		s = indent + "{\n"
		for c in self.contentlist:
			s += asCCode(c, indent + "\t") + ",\n"
		s += indent + "}"
		return s
		
def findIdentifierInBody(body, name):
	if name in body.enumconsts:
		return body.enumconsts[name]
	if body.parent is not None:
		return findIdentifierInBody(body.parent, name)
	return None

def make_type_from_typetokens(stateStruct, type_tokens):
	if not type_tokens:
		return None
	if len(type_tokens) == 1 and isinstance(type_tokens[0], _CBaseWithOptBody):
		t = type_tokens[0]
	elif tuple(type_tokens) in stateStruct.CBuiltinTypes:
		t = CBuiltinType(tuple(type_tokens))
	elif len(type_tokens) > 1 and type_tokens[-1] == "*":
		t = CPointerType(make_type_from_typetokens(stateStruct, type_tokens[:-1]))
	elif len(type_tokens) == 1 and type_tokens[0] in stateStruct.StdIntTypes:
		t = CStdIntType(type_tokens[0])
	elif len(type_tokens) == 1 and type_tokens[0] in stateStruct.typedefs:
		t = stateStruct.typedefs[type_tokens[0]]
	elif type_tokens == [".", ".", "."]:
		t = CVariadicArgsType()
	else:
		stateStruct.error("type tokens not handled: %s" % type_tokens)
		t = None
	return t

def asCCode(stmnt, indent="", fullDecl=False):
	if not fullDecl:
		if isinstance(stmnt, CFunc): return indent + stmnt.name
		if isinstance(stmnt, CStruct): return indent + "struct " + stmnt.name
		if isinstance(stmnt, CUnion): return indent + "union " + stmnt.name
		if isinstance(stmnt, CEnum): return indent + "enum " + stmnt.name
	if hasattr(stmnt, "asCCode"):
		return stmnt.asCCode(indent)
	assert False, "don't know how to handle " + str(stmnt)
	
class _CBaseWithOptBody(object):
	NameIsRelevant = True
	AutoAddToContent = True
	AlwaysNonZero = False
	StrOutAttribList = [
		("args", bool, None, str),
		("arrayargs", bool, None, str),
		("body", None, None, lambda x: "<...>"),
		("value", None, None, str),
		("defPos", None, "@", str),
	]
	
	def __init__(self, **kwargs):
		self._type_tokens = []
		self._bracketlevel = None
		self._finalized = False
		self.defPos = None
		self.type = None
		self.attribs = []
		self.name = None
		self.args = []
		self.arrayargs = []
		self.body = None
		self.value = None
		self.parent = None
		for k,v in kwargs.items():
			setattr(self, k, v)
			
	@classmethod
	def overtake(cls, obj):
		obj.__class__ = cls
		# no cls.__init__ because it would overwrite all our attribs!
		
	def isDerived(self):
		return self.__class__ != _CBaseWithOptBody

	def __str__(self):
		if self.NameIsRelevant:
			name = ("'" + self.name + "' ") if self.name else "<noname> "
		else:
			name = ("name: '" + self.name + "' ") if self.name else ""
		t = self.type or self._type_tokens
		l = []
		if self.attribs: l += [("attribs", self.attribs)]
		if t: l += [("type", t)]
		for attrName,addCheck,displayName,displayFunc in self.StrOutAttribList:
			a = getattr(self, attrName)
			if addCheck is None: addCheck = lambda x: x is not None
			if addCheck(a):
				if displayName is None: displayName = attrName
				l += [(displayName, displayFunc(a))]
		return \
			self.__class__.__name__ + " " + \
			name + \
			", ".join(map((lambda a: a[0] + ": " + str(a[1])), l))

	def __repr__(self): return "<" + str(self) + ">"

	def __nonzero__(self):
		return \
			self.AlwaysNonZero or \
			bool(self._type_tokens) or \
			bool(self.type) or \
			bool(self.name) or \
			bool(self.args) or \
			bool(self.arrayargs) or \
			bool(self.body)
	
	def finalize(self, stateStruct, addToContent = None):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return
		self._finalized = True
		if self.defPos is None:
			self.defPos = stateStruct.curPosAsStr()
		if not self: return
		
		if addToContent is None: addToContent = self.AutoAddToContent
		
		#print "finalize", self, "at", stateStruct.curPosAsStr()
		if addToContent and self.parent is not None and self.parent.body and hasattr(self.parent.body, "contentlist"):
			self.parent.body.contentlist.append(self)

	def addToBody(self, obj):
		if self.body is None:
			self.body = obj
		else:
			assert isinstance(self.body, CBody)
			self.body.contentlist.append(obj)

	def _copy(self, value, parent=None, name=None, leave_out_attribs=()):
		if isinstance(value, (int, long, float, str, unicode)) or value is None:
			return value
		elif isinstance(value, list):
			return [self._copy(v, parent=parent) for v in value]
		elif isinstance(value, tuple):
			return tuple([self._copy(v, parent=parent) for v in value])
		elif isinstance(value, dict):
			return {k: self._copy(v, parent=parent) for (k, v) in value.items()}
		elif isinstance(value, (_CBase, _CBaseWithOptBody, CType, CBody)):
			new = value.__class__.__new__(value.__class__)
			for k, v in vars(value).items():
				if k in leave_out_attribs:
					continue
				if k == "parent":
					new.parent = parent
				else:
					setattr(new, k, self._copy(v, parent=new, name=k))
			return new
		else:
			assert False, "dont know how to handle %r %r (%s)" % (name, value, value.__class__)

	def copy(self, leave_out_attribs=("body",)):
		return self._copy(self, parent=self.parent, leave_out_attribs=leave_out_attribs)

	def depth(self):
		if self.parent is None: return 1
		return self.parent.depth() + 1

	def getCType(self, stateStruct):
		raise Exception(str(self) + " cannot be converted to a C type")

	def findAttrib(self, stateStruct, attrib):
		if self.body is None:
			# it probably is the pre-declaration. but we might find the real-one
			if isinstance(self, CStruct): D = "structs"
			elif isinstance(self, CUnion): D = "unions"
			elif isinstance(self, CEnum): D = "enums"
			self = getattr(stateStruct, D).get(self.name, self)
		if self.body is None: return None
		for c in self.body.contentlist:
			if not isinstance(c, CVarDecl): continue
			if c.name == attrib: return c
		return None
	
	def asCCode(self, indent=""):
		raise NotImplementedError(str(self) + " asCCode not implemented")
	
class CTypedef(_CBaseWithOptBody):
	def finalize(self, stateStruct):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return
		
		self.type = make_type_from_typetokens(stateStruct, self._type_tokens)
		_CBaseWithOptBody.finalize(self, stateStruct)
		
		if self.type is None:
			stateStruct.error("finalize typedef " + str(self) + ": type is unknown")
			return
		if self.name is None:
			stateStruct.error("finalize typedef " + str(self) + ": name is unset")
			return

		self.parent.body.typedefs[self.name] = self
	def getCType(self, stateStruct): return getCType(self.type, stateStruct)
	def asCCode(self, indent=""):
		return indent + "typedef\n" + asCCode(self.type, indent, fullDecl=True) + " " + self.name
	
class CFuncPointerDecl(_CBaseWithOptBody):
	def finalize(self, stateStruct, addToContent=None):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return

		if not self.type:
			self.type = make_type_from_typetokens(stateStruct, self._type_tokens)
		_CBaseWithOptBody.finalize(self, stateStruct, addToContent)
		
		if self.type is None:
			stateStruct.error("finalize " + str(self) + ": type is unknown")
		# Name can be unset. It depends where this is declared.
	def getCType(self, stateStruct, workaroundPtrReturn=True, wrap=True):
		if workaroundPtrReturn and isinstance(self.type, CPointerType):
			# https://bugs.python.org/issue5710
			restype = ctypes.c_void_p
		else:
			restype = getCType(self.type, stateStruct)
		if wrap: restype = wrapCTypeClassIfNeeded(restype)
		argtypes = map(lambda a: getCType(a, stateStruct), self.args)
		#if wrap: argtypes = map(wrapCTypeClassIfNeeded, argtypes)
		return ctypes.CFUNCTYPE(restype, *argtypes)
	def asCCode(self, indent=""):
		return indent + asCCode(self.type) + "(*" + self.name + ") (" + ", ".join(map(asCCode, self.args)) + ")"


def _addToParent(obj, stateStruct, dictName=None, listName=None):
	assert dictName or listName
	assert hasattr(obj.parent, "body")
	d = getattr(obj.parent.body, dictName or listName)
	if dictName:
		if obj.name is None:
			# might be part of a typedef, so don't error
			return

		# If the body is empty, it was a pre-declaration and it is ok to overwrite it now.
		# Otherwise however, it is an error.
		if obj.name in d and d[obj.name].body is not None:
			stateStruct.error("finalize " + str(obj) + ": a previous equally named declaration exists: " + str(d[obj.name]))
		else:
			d[obj.name] = obj
	else:
		assert listName is not None
		d.append(obj)


def _finalizeBasicType(obj, stateStruct, dictName=None, listName=None, addToContent=None):
	if obj._finalized:
		stateStruct.error("internal error: " + str(obj) + " finalized twice")
		return
	
	if addToContent is None:
		addToContent = obj.name is not None

	if obj.type is None:
		obj.type = make_type_from_typetokens(stateStruct, obj._type_tokens)
	_CBaseWithOptBody.finalize(obj, stateStruct, addToContent=addToContent)
	
	if addToContent and hasattr(obj.parent, "body") and not getattr(obj, "_already_added", False):
		_addToParent(obj=obj, stateStruct=stateStruct, dictName=dictName, listName=listName)


class CFunc(_CBaseWithOptBody):
	finalize = lambda *args, **kwargs: _finalizeBasicType(*args, dictName="funcs", **kwargs)
	def getCType(self, stateStruct):
		restype = getCType(self.type, stateStruct)
		argtypes = map(lambda a: getCType(a, stateStruct), self.args)
		return ctypes.CFUNCTYPE(restype, *argtypes)
	def asCCode(self, indent=""):
		s = indent + asCCode(self.type) + " " + self.name + "(" + ", ".join(map(asCCode, self.args)) + ")"
		if self.body is None: return s
		s += "\n"
		s += asCCode(self.body, indent)
		return s

class CVarDecl(_CBaseWithOptBody):
	finalize = lambda *args, **kwargs: _finalizeBasicType(*args, dictName="vars", **kwargs)
	def clearDeclForNextVar(self):
		if hasattr(self, "bitsize"): delattr(self, "bitsize")
		while self._type_tokens and self._type_tokens[-1] in ("*",):
			self._type_tokens.pop()
	def asCCode(self, indent=""):
		s = indent + asCCode(self.type) + " " + self.name
		if self.body is None: return s
		s += " = "
		s += asCCode(self.body)
		return s

def needWrapCTypeClass(t):
	if t is None: return False
	return t.__base__ is _ctypes._SimpleCData

def wrapCTypeClassIfNeeded(t):
	if needWrapCTypeClass(t): return wrapCTypeClass(t)
	else: return t

_wrapCTypeClassCache = {}

def wrapCTypeClass(t):
	if id(t) in _wrapCTypeClassCache: return _wrapCTypeClassCache[id(t)]
	class WrappedType(t): pass
	WrappedType.__name__ = "wrapCTypeClass_%s" % t.__name__
	_wrapCTypeClassCache[id(t)] = WrappedType
	return WrappedType

def _getCTypeStruct(baseClass, obj, stateStruct):
	if hasattr(obj, "_ctype"): return obj._ctype
	assert hasattr(obj, "body"), str(obj) + " must have the body attrib"
	assert obj.body is not None, str(obj) + ".body must not be None. maybe it was only forward-declarated?"
	class ctype(baseClass): pass
	ctype.__name__ = str(obj.name or "<anonymous-struct>")
	obj._ctype = ctype
	fields = []
	for c in obj.body.contentlist:
		if not isinstance(c, CVarDecl): continue
		t = getCType(c.type, stateStruct)
		if c.arrayargs:
			if len(c.arrayargs) != 1: raise Exception(str(c) + " has too many array args")
			n = c.arrayargs[0].value
			t = t * n
		elif stateStruct.IndirectSimpleCTypes:
			# See http://stackoverflow.com/questions/6800827/python-ctypes-structure-how-to-access-attributes-as-if-they-were-ctypes-and-not/6801253#6801253
			t = wrapCTypeClassIfNeeded(t)
		if hasattr(c, "bitsize"):
			fields += [(str(c.name), t, c.bitsize)]
		else:
			fields += [(str(c.name), t)]	
	ctype._fields_ = fields
	return ctype
	
class CStruct(_CBaseWithOptBody):
	finalize = lambda *args, **kwargs: _finalizeBasicType(*args, dictName="structs", **kwargs)
	def getCType(self, stateStruct):
		return _getCTypeStruct(ctypes.Structure, self, stateStruct)
	def asCCode(self, indent=""):
		s = indent + "struct " + self.name
		if self.body is None: return s
		return s + "\n" + asCCode(self.body, indent)
		
class CUnion(_CBaseWithOptBody):
	finalize = lambda *args, **kwargs: _finalizeBasicType(*args, dictName="unions", **kwargs)
	def getCType(self, stateStruct):
		return _getCTypeStruct(ctypes.Union, self, stateStruct)
	def asCCode(self, indent=""):
		s = indent + "union " + self.name
		if self.body is None: return s
		return s + "\n" + asCCode(self.body, indent)

def minCIntTypeForNums(a, b=None, minBits=32, maxBits=64, useUnsignedTypes=True):
	if b is None: b = a
	bits = minBits
	while bits <= maxBits:
		if useUnsignedTypes and a >= 0 and b < (1<<bits): return "uint" + str(bits) + "_t"
		elif a >= -(1<<(bits-1)) and b < (1<<(bits-1)): return "int" + str(bits) + "_t"
		bits *= 2
	return None

class CEnum(_CBaseWithOptBody):
	finalize = lambda *args, **kwargs: _finalizeBasicType(*args, dictName="enums", **kwargs)
	def getNumRange(self):
		a,b = 0,0
		for c in self.body.contentlist:
			assert isinstance(c, CEnumConst)
			if c.value < a: a = c.value
			if c.value > b: b = c.value
		return a,b
	def getEnumConst(self, value):
		for c in self.body.contentlist:
			if not isinstance(c, CEnumConst): continue
			if c.value == value: return c
		return None
	def getCType(self, stateStruct):
		a,b = self.getNumRange()
		t = minCIntTypeForNums(a, b)
		if t is None:
			raise Exception(str(self) + " has a too high number range " + str((a,b)))
		t = stateStruct.StdIntTypes[t]
		class EnumType(t):
			_typeStruct = self
			def __repr__(self):
				v = self._typeStruct.getEnumConst(self.value)
				if v is None: v = self.value
				return "<EnumType " + str(v) + ">"
			def __cmp__(self, other):
				return cmp(self.value, other)
		for c in self.body.contentlist:
			if not c.name: continue
			if hasattr(EnumType, c.name): continue
			setattr(EnumType, c.name, c.value)
		return EnumType
	def asCCode(self, indent=""):
		s = indent + "enum " + self.name
		if self.body is None: return s
		return s + "\n" + asCCode(self.body, indent)
	
class CEnumConst(_CBaseWithOptBody):
	def finalize(self, stateStruct, addToContent=None):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return

		if self.value is None:
			if self.parent.body.contentlist:
				last = self.parent.body.contentlist[-1]
				if isinstance(last.value, (str,unicode)):
					self.value = unichr(ord(last.value) + 1)
				else:
					self.value = last.value + 1
			else:
				self.value = 0

		_CBaseWithOptBody.finalize(self, stateStruct, addToContent)

		if self.name:
			# self.parent.parent is the parent of the enum
			self.parent.parent.body.enumconsts[self.name] = self
	def getConstValue(self, stateStruct):
		return self.value
	def asCCode(self, indent=""):
		return indent + self.name + " = " + str(self.value)
	
class CFuncArgDecl(_CBaseWithOptBody):
	AutoAddToContent = False	
	def finalize(self, stateStruct, addToContent=False):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return

		if not self.type:
			self.type = make_type_from_typetokens(stateStruct, self._type_tokens)
		_CBaseWithOptBody.finalize(self, stateStruct, addToContent=False)
		
		if self.type != CBuiltinType(("void",)):
			self.parent.args += [self]
	def getCType(self, stateStruct):
		return getCType(self.type, stateStruct)
	def asCCode(self, indent=""):
		s = indent + asCCode(self.type)
		if self.name: s += " " + self.name
		return s
	
def _isBracketLevelOk(parentLevel, curLevel):
	if parentLevel is None: parentLevel = []
	if len(parentLevel) > len(curLevel): return False
	return curLevel[:len(parentLevel)] == parentLevel

def _body_parent_chain(stateStruct, parentCObj):
	yieldedStateStruct = False

	for cobj in _obj_parent_chain(stateStruct, parentCObj):
		body = cobj.body
		if isinstance(body, CBody):
			yieldedStateStruct |= body is stateStruct
			yield body

	if not yieldedStateStruct: yield stateStruct

def _obj_parent_chain(stateStruct, parentCObj):
	while parentCObj is not None:
		yield parentCObj
		parentCObj = parentCObj.parent
		
def getObjInBody(body, name):
	"""
	:type body: CBody | State
	:type name: str
	:return: object, statement or type
	"""
	if name in body.funcs:
		return body.funcs[name]
	elif name in body.typedefs:
		return body.typedefs[name]
	elif name in body.vars:
		return body.vars[name]
	elif name in body.enumconsts:
		return body.enumconsts[name]
	elif (name,) in getattr(body, "CBuiltinTypes", {}):
		return CBuiltinType((name,))
	elif name in getattr(body, "StdIntTypes", {}):
		return CStdIntType(name)
	return None

def findObjInNamespace(stateStruct, curCObj, name):
	for cobj in _obj_parent_chain(stateStruct, curCObj):
		if isinstance(cobj.body, (CBody,State)):
			obj = getObjInBody(cobj.body, name)
			if obj is not None: return obj
		if isinstance(cobj, CFunc):
			for arg in cobj.args:
				assert isinstance(arg, CFuncArgDecl)
				if arg.name is not None and arg.name == name:
					return arg
			if cobj.name == name:
				return cobj
	return None

def findCObjTypeInNamespace(stateStruct, curCObj, DictName, name):
	for body in _body_parent_chain(stateStruct, curCObj):
		d = getattr(body, DictName)
		if name in d: return d[name]
	return None

class _CStatementCall(_CBaseWithOptBody):
	AutoAddToContent = False
	base = None
	def __nonzero__(self): return self.base is not None
	def __str__(self):
		s = self.__class__.__name__ + " " + repr(self.base)
		if self.name:
			s += " name: " + self.name
		else:
			s += " args: " + str(self.args)
		return s
	
class CFuncCall(_CStatementCall): # base(args) or (base)args; i.e. can also be a simple cast
	def asCCode(self, indent=""):
		return indent + asCCode(self.base) + "(" + ", ".join(map(asCCode, self.args)) + ")"
class CArrayIndexRef(_CStatementCall): # base[args]
	def asCCode(self, indent=""):
		return indent + asCCode(self.base) + "[" + ", ".join(map(asCCode, self.args)) + "]"
class CAttribAccessRef(_CStatementCall): # base.name
	def asCCode(self, indent=""):
		return indent + asCCode(self.base) + "." + self.name
class CPtrAccessRef(_CStatementCall): # base->name
	def asCCode(self, indent=""):
		return indent + asCCode(self.base) + "->" + self.name

def _create_cast_call(stateStruct, parent, base, token):
	funcCall = CFuncCall(parent=parent)
	funcCall.base = base
	arg = CStatement(parent=funcCall)
	funcCall.args = [arg]
	arg._cpre3_handle_token(stateStruct, token)
	funcCall.finalize(stateStruct)
	return funcCall

def opsDoLeftToRight(stateStruct, op1, op2):
	try: opprec1 = OpPrecedences[op1]
	except KeyError:
		stateStruct.error("internal error: statement parsing: op1 " + repr(op1) + " unknown")
		opprec1 = 100
	try: opprec2 = OpPrecedences[op2]
	except KeyError:
		stateStruct.error("internal error: statement parsing: op2 " + repr(op2) + " unknown")
		opprec2 = 100
	
	if opprec1 < opprec2:
		return True
	elif opprec1 > opprec2:
		return False
	if op1 in OpsRightToLeft:
		return False
	return True

def getConstValue(stateStruct, obj):
	"""
	Evaluates the obj, in case it is a expression which can be evaluated at compile time.
	"""
	if hasattr(obj, "getConstValue"): return obj.getConstValue(stateStruct)
	if isinstance(obj, (CNumber,CStr,CChar)):
		return obj.content
	return None

def getValueType(stateStruct, obj):
	if hasattr(obj, "getValueType"): return obj.getValueType(stateStruct)
	if isinstance(obj, CVarDecl):
		return obj.type
	if isinstance(obj, CFuncArgDecl):
		return obj.type
	if isinstance(obj, CAttribAccessRef):
		base_type = getValueType(stateStruct, obj.base)
		while isinstance(base_type, CTypedef):
			base_type = base_type.type
		assert isinstance(base_type, (CStruct,CUnion))
		return base_type.body.vars[obj.name].type
	if isinstance(obj, CPtrAccessRef):
		pbase_type = getValueType(stateStruct, obj.base)
		while isinstance(pbase_type, CTypedef):
			pbase_type = pbase_type.type
		assert isinstance(pbase_type, CPointerType)
		base_type = pbase_type.pointerOf
		while isinstance(base_type, CTypedef):
			base_type = base_type.type
		assert isinstance(base_type, (CStruct,CUnion))
		if base_type.body is None:
			if isinstance(base_type, CStruct):
				base_type = stateStruct.structs[base_type.name]
			elif isinstance(base_type, CUnion):
				base_type = stateStruct.unions[base_type.name]
			assert base_type.body is not None
		return base_type.body.vars[obj.name].type
	if isinstance(obj, CFuncCall):
		from interpreter import CWrapValue
		if isinstance(obj.base, CWrapValue):
			return obj.base.returnType
		# Check for cast-like calls.
		if isinstance(obj.base, (CTypedef, CType)):
			return obj.base
		base_type = getValueType(stateStruct, obj.base)
		while isinstance(base_type, CTypedef):
			base_type = base_type.type
		assert isinstance(base_type, (CFuncPointerDecl,CFunc))
		return base_type.type  # return-type
	if isinstance(obj, CFunc):
		return obj
	if isinstance(obj, CSizeofSymbol):
		return CFunc(type=CStdIntType("size_t"))
	if isinstance(obj, CStr):
		return CArrayType(arrayOf=CBuiltinType(("char",)), arrayLen=CNumber(len(obj.content) + 1))
	if isinstance(obj, CChar):
		return CBuiltinType(("char",))
	if isinstance(obj, CNumber):
		# TODO handle typeSpec
		if isinstance(obj.content, float):
			return CBuiltinType(("double",))
		t = minCIntTypeForNums(obj.content, minBits=32, maxBits=64, useUnsignedTypes=True)
		assert t, "no int type for %r" % obj
		return CStdIntType(t)
	assert False, "no type for %r" % obj

def getCommonValueType(stateStruct, t1, t2):
	while isinstance(t1, CTypedef):
		t1 = t1.type
	while isinstance(t2, CTypedef):
		t2 = t2.type
	if isclass(t1) and issubclass(t1, ctypes._SimpleCData):
		t1 = getBuiltinTypeForCType(stateStruct, t1)
	if isclass(t2) and issubclass(t2, ctypes._SimpleCData):
		t2 = getBuiltinTypeForCType(stateStruct, t2)
	if t1 == ctypes.c_void_p:
		t1 = CBuiltinType(("void","*"))
	if t2 == ctypes.c_void_p:
		t2 = CBuiltinType(("void","*"))
	if t1 == CPointerType(CVoidType()):
		t1 = CBuiltinType(("void","*"))
	if t2 == CPointerType(CVoidType()):
		t2 = CBuiltinType(("void","*"))
	if t1 == CBuiltinType(("void","*")):
		if t2 == CBuiltinType(("void","*")):
			return t1
		if isinstance(t2, CPointerType):
			return getCommonValueType(stateStruct, t2, t1)
		assert isinstance(t2, (CBuiltinType, CStdIntType))
		return t1
	if t2 == CBuiltinType(("void","*")):
		return getCommonValueType(stateStruct, t2, t1)
	if isinstance(t1, CPointerType):
		if isinstance(t2, CPointerType):
			assert isSameType(stateStruct, t1.pointerOf, t2.pointerOf)
			return t1
		if isinstance(t2, CArrayType):
			assert isSameType(stateStruct, t1.pointerOf, t2.arrayOf)
			return t1
		assert isinstance(t2, (CBuiltinType, CStdIntType))
		return t1
	if isinstance(t2, CPointerType):
		return getCommonValueType(stateStruct, t2, t1)
	if isinstance(t1, CArrayType) or isinstance(t2, CArrayType):
		if isinstance(t1, CArrayType) and isinstance(t2, CArrayType):
			if isSameType(stateStruct, t1, t2): return t1
		if isinstance(t1, CArrayType):
			t1 = CPointerType(t1.arrayOf)
		if isinstance(t2, CArrayType):
			t2 = CPointerType(t2.arrayOf)
		return getCommonValueType(stateStruct, t1, t2)
	# No pointers.
	if isinstance(t1, CBuiltinType) and isinstance(t2, CBuiltinType):
		tup1 = t1.builtinType
		tup2 = t2.builtinType
		if "float" in tup1 or "double" in tup1:
			if "float" in tup2 or "double" in tup2:
				# Select bigger type.
				Ts = [("float",), ("double",), ("long", "double")]
				if Ts.index(tup2) > Ts.index(tup1):
					return t2
				return t1
			return t1  # Cast int to float.
		if "float" in tup2 or "double" in tup2:
			return t2  # Cast int to float.
		# No floats.
		Is = {("char",): 1, ("short",): 2,
			  ("int",): 3, ("signed",): 3, (): 3,
			  ("long",): 4, ("long", "long"): 5}
		invI = {1: ("char",), 2: ("short",), 3: ("int",),
				4: ("long",), 5: ("long", "long")}
		unsigned_t1 = "unsigned" in tup1
		unsigned_t2 = "unsigned" in tup2
		if unsigned_t1: assert tup1[0] == "unsigned"
		if unsigned_t2: assert tup2[0] == "unsigned"
		ti1 = Is[tup1[1 if unsigned_t1 else 0:]]
		ti2 = Is[tup2[1 if unsigned_t2 else 0:]]
		st_max = invI[max(ti1, ti2)]
		t_max = (("unsigned",) if (unsigned_t1 or unsigned_t2) else ()) + st_max
		return CBuiltinType(t_max)
	if isinstance(t1, CStdIntType) and isinstance(t2, CStdIntType):
		def base_wrap(name):
			if name == "byte": return "int8_t"
			if name == "wchar_t": return "int16_t"
			return name
		t1_name = base_wrap(t1.name)
		t2_name = base_wrap(t2.name)
		BuiltinWraps = {"size_t": ("unsigned", "long"),
						"ptrdiff_t": ("long",),
						"intptr_t": ("long",)}
		if t1_name in BuiltinWraps:
			t1 = CBuiltinType(BuiltinWraps[t1_name])
			return getCommonValueType(stateStruct, t1, t2)
		if t2_name in BuiltinWraps:
			t2 = CBuiltinType(BuiltinWraps[t2_name])
			return getCommonValueType(stateStruct, t1, t2)
		unsigned_t1 = t1_name[:1] == "u"
		unsigned_t2 = t2_name[:1] == "u"
		Is = {"int8_t": 8, "int16_t": 16, "int32_t": 32, "int64_t": 64}
		ti1 = Is[t1_name[1 if unsigned_t1 else 0:]]
		ti2 = Is[t2_name[1 if unsigned_t2 else 0:]]
		st_max = "int%s_t" % max(ti1, ti2)
		t_max = ("u" if (unsigned_t1 or unsigned_t2) else "") + st_max
		return CStdIntType(t_max)
	if isinstance(t1, CBuiltinType) and isinstance(t2, CStdIntType):
		t2 = getBuiltinTypeForStdIntType(stateStruct, t2)
		return getCommonValueType(stateStruct, t1, t2)
	if isinstance(t1, CStdIntType) and isinstance(t2, CBuiltinType):
		t1 = getBuiltinTypeForStdIntType(stateStruct, t1)
		return getCommonValueType(stateStruct, t1, t2)
	# Not a basic type.
	assert isSameType(stateStruct, t1, t2)
	return t1

def getStdIntTypeForCType(stateStruct, c_type):
	"""
	Note: This is platform dependent!
	"""
	for prefix in ("", "u"):
		for postfix in ("8", "16", "32", "64"):
			k = prefix + "int" + postfix + "_t"
			stdint_c_type = stateStruct.StdIntTypes[k]
			if stdint_c_type == c_type:
				return CStdIntType(k)
	assert False, "unknown type %r" % c_type

def getStdIntTypeForBuiltinType(stateStruct, t):
	"""
	Note: This is platform dependent!
	"""
	assert isinstance(t, CBuiltinType)
	c_type = stateStruct.CBuiltinTypes[t.builtinType]
	return getStdIntTypeForCType(stateStruct, c_type)

def getBuiltinTypeForCType(stateStruct, c_type):
	"""
	Note: This is platform dependent!
	"""
	if c_type.__name__.startswith("wrapCTypeClass_"):
		c_type = c_type.__base__
	IntTypes = (("char",), ("short",), ("int",),
				("long",), ("long", "long"))
	OtherTypes = (("float",), ("double",), ("long", "double"),
				  ("void", "*"))
	for prefix in ((), ("unsigned",)):
		types = IntTypes
		if not prefix: types = types + OtherTypes
		for postfix in types:
			k = prefix + postfix
			builtin_c_type = stateStruct.CBuiltinTypes[k]
			if builtin_c_type == c_type:
				return CBuiltinType(k)
	assert False, "unknown type %r" % c_type

def getBuiltinTypeForStdIntType(stateStruct, t):
	"""
	Note: This is platform dependent!
	"""
	assert isinstance(t, CStdIntType)
	stdint_c_type = stateStruct.StdIntTypes[t.name]
	return getBuiltinTypeForCType(stateStruct, stdint_c_type)

def isIntType(t):
	while isinstance(t, CTypedef):
		t = t.type
	if isinstance(t, CBuiltinType):
		if "void" in t.builtinType: return False
		if "float" in t.builtinType or "double" in t.builtinType:
			return False
		return True
	if isinstance(t, CStdIntType):
		return True
	return False

class CSizeofSymbol: pass

class CCurlyArrayArgs(_CBaseWithOptBody):
	# args is a list of CStatement
	NameIsRelevant = False
	def asCCode(self, indent=""):
		return indent + "{" + ", ".join(map(asCCode, self.args)) + "}"

class CStatement(_CBaseWithOptBody):
	NameIsRelevant = False
	_leftexpr = None
	_middleexpr = None
	_rightexpr = None
	_op = None
	def __nonzero__(self): return bool(self._leftexpr) or bool(self._rightexpr)
	def __repr__(self):
		s = self.__class__.__name__
		#s += " " + repr(self._tokens) # debug
		if self._leftexpr is not None: s += " " + repr(self._leftexpr)
		if self._op == COp("?:"):
			s += " ? " + repr(self._middleexpr)
			s += " : " + repr(self._rightexpr)
		elif self._op is not None or self._rightexpr is not None:
			s += " "
			s += str(self._op)
			if self._rightexpr is not None:
				s += " "
				s += repr(self._rightexpr)
		if self.defPos is not None: s += " @: " + self.defPos
		return "<" + s + ">"
	__str__ = __repr__
	def _initStatement(self):
		self._state = 0
		self._tokens = []
	def __init__(self, **kwargs):
		self._initStatement()
		_CBaseWithOptBody.__init__(self, **kwargs)
	@classmethod
	def overtake(cls, obj):
		obj.__class__ = cls
		obj._initStatement()
	def _handlePushedErrorForUnknown(self, stateStruct):
		if isinstance(self._leftexpr, CUnknownType):
			s = getattr(self, "_pushedErrorForUnknown", False)
			if not s:
				stateStruct.error("statement parsing: identifier %r unknown in state %i in handle pushed error" % (self._leftexpr.name, self._state))
				self._pushedErrorForUnknown = True
	def finalize(self, stateStruct, addToContent=None):
		self._handlePushedErrorForUnknown(stateStruct)
		_CBaseWithOptBody.finalize(self, stateStruct, addToContent)
	def _cpre3_handle_token(self, stateStruct, token):
		"""
		:type stateStruct: State
		:type token: iterator
		"""
		self._tokens += [token]

		if self._state == 5 and token == COp(":"):
			if isinstance(self._leftexpr, CUnknownType):
				CGotoLabel.overtake(self)
				self.name = self._leftexpr.name
				self._type_tokens[:] = []
			else:
				stateStruct.error("statement parsing: got ':' after " + repr(self._leftexpr) + "; looks like a goto-label but is not")
			self.finalize(stateStruct)
			return

		self._handlePushedErrorForUnknown(stateStruct)
		obj = None
		if self._state == 0:
			if isinstance(token, (CIdentifier,CNumber,CStr,CChar)):
				if isinstance(token, CIdentifier):
					if token.content == "struct":
						self._state = 1
						return
					elif token.content == "union":
						self._state = 2
						return
					elif token.content == "enum":
						self._state = 3
						return
					elif token.content == "sizeof":
						obj = CSizeofSymbol()
					else:
						obj = findObjInNamespace(stateStruct, self.parent, token.content)
						if obj is None:
							obj = CUnknownType(name=token.content)
							self._pushedErrorForUnknown = False
							# we print an error later. it still could be a goto-label.
				else:
					obj = token
				self._leftexpr = obj
				self._state = 5
			elif isinstance(token, COp):
				# prefix op
				self._op = token
				self._rightexpr = CStatement(parent=self)
				self._state = 8
			else:
				stateStruct.error("statement parsing: didn't expected token " + str(token))
		elif self._state in (1,2,3): # struct,union,enum
			TName = {1:"struct", 2:"union", 3:"enum"}[self._state]
			DictName = TName + "s"
			if isinstance(token, CIdentifier):
				obj = findCObjTypeInNamespace(stateStruct, self.parent, DictName, token.content)
				if obj is None:
					stateStruct.error("statement parsing: " + TName + " '" + token.content + "' unknown")
					obj = CUnknownType(name=token.content)
				self._leftexpr = obj
				self._state = 5
			else:
				stateStruct.error("statement parsing: didn't expected token " + str(token) + " after " + TName)
		elif self._state == 5: # after expr
			if token == COp("."):
				if isinstance(self._leftexpr, CNumber):
					self._state = 10
				else:
					self._state = 20
					self._leftexpr = CAttribAccessRef(parent=self, base=self._leftexpr)
			elif token == COp("->"):
				self._state = 20
				self._leftexpr = CPtrAccessRef(parent=self, base=self._leftexpr)
			elif isinstance(token, COp):
				if token.content in OpPostfixFuncs:
					subStatement = CStatement(parent=self)
					subStatement._leftexpr = self._leftexpr
					subStatement._op = token
					self._leftexpr = subStatement
				else:
					self._op = token
					self._state = 6
			elif isinstance(self._leftexpr, CStr) and isinstance(token, CStr):
				self._leftexpr = CStr(self._leftexpr.content + token.content)
			else:
				if isinstance(self._leftexpr, CBuiltinType) and self._leftexpr.builtinType + (token.content,) in stateStruct.CBuiltinTypes:
					self._leftexpr = CBuiltinType(self._leftexpr.builtinType + (token.content,))
					# stay in same state
				else:
					self._leftexpr = _create_cast_call(stateStruct, self, self._leftexpr, token)
					self._state = 40
		elif self._state == 6: # after expr + op
			if isinstance(token, CIdentifier):
				if token.content == "sizeof":
					obj = CSizeofSymbol()
				else:
					obj = findObjInNamespace(stateStruct, self.parent, token.content)
					if obj is None:
						stateStruct.error("statement parsing: identifier %r unknown in state %i" % (token.content, self._state))
						obj = CUnknownType(name=token.content)
				self._state = 7
			elif isinstance(token, (CNumber,CStr,CChar)):
				obj = token
				self._state = 7
			else:
				obj = CStatement(parent=self)
				obj._cpre3_handle_token(stateStruct, token) # maybe a postfix op or whatever
				self._state = 8
			self._rightexpr = obj
		elif self._state == 7: # after expr + op + expr
			if token == COp("."):
				if isinstance(self._rightexpr, CNumber):
					self._state = 11
				else:
					self._state = 22
					self._rightexpr = CAttribAccessRef(parent=self, base=self._rightexpr)
			elif token == COp("->"):
				self._state = 22
				self._rightexpr = CPtrAccessRef(parent=self, base=self._rightexpr)
			elif isinstance(token, COp):
				if token == COp(":"):
					if self._op != COp("?"):
						stateStruct.error("internal error: got ':' after " + repr(self) + " with " + repr(self._op))
						# TODO: any better way to fix/recover? right now, we just assume '?' anyway
					self._middleexpr = self._rightexpr
					self._rightexpr = None
					self._op = COp("?:")
					self._state = 6
				elif opsDoLeftToRight(stateStruct, self._op.content, token.content):
					import copy
					subStatement = copy.copy(self)
					self._leftexpr = subStatement
					self._rightexpr = None
					self._op = token
					self._state = 6
				else:
					self._rightexpr = CStatement(parent=self, _leftexpr=self._rightexpr, _state=6)
					self._rightexpr._op = token
					self._state = 8
			elif isinstance(self._rightexpr, CStr) and isinstance(token, CStr):
				self._rightexpr = CStr(self._rightexpr.content + token.content)
			else:
				self._rightexpr = _create_cast_call(stateStruct, self, self._rightexpr, token)
				self._state = 45
		elif self._state == 8: # right-to-left chain, pull down
			assert isinstance(self._rightexpr, CStatement)
			self._rightexpr._cpre3_handle_token(stateStruct, token)
			if self._rightexpr._state in (5,7,9):
				self._state = 9
		elif self._state == 9: # right-to-left chain after op + expr
			assert isinstance(self._rightexpr, CStatement)
			if token in (COp("."),COp("->")):
				self._rightexpr._cpre3_handle_token(stateStruct, token)
				self._state = 8
			elif not isinstance(token, COp):
				self._rightexpr._cpre3_handle_token(stateStruct, token)
			else: # is COp
				if token.content == ":":
					if self._op == COp("?"):
						self._middleexpr = self._rightexpr
						self._rightexpr = None
						self._op = COp("?:")
						self._state = 6
					else:
						self._rightexpr._cpre3_handle_token(stateStruct, token)
						self._state = 8
				elif opsDoLeftToRight(stateStruct, self._op.content, token.content):
					import copy
					subStatement = copy.copy(self)
					self._leftexpr = subStatement
					self._rightexpr = None
					self._op = token
					self._state = 6
				else:
					self._rightexpr._cpre3_handle_token(stateStruct, token)
					self._state = 8
		elif self._state == 10: # after number + "."
			if isinstance(token, CNumber):
				self._leftexpr = CNumber(float("%s.%s" % (self._leftexpr.content, token.content)))
			else:
				stateStruct.error("statement parsing: did not expect %s in state %i" % (token, self._state))
			self._state = 5
		elif self._state == 11: # after expr + op + number + "."
			if isinstance(token, CNumber):
				self._rightexpr = CNumber(float("%s.%s" % (self._rightexpr.content, token.content)))
			else:
				stateStruct.error("statement parsing: did not expect %s in state %i" % (token, self._state))
			self._state = 7
		elif self._state == 20: # after attrib/ptr access
			if isinstance(token, CIdentifier):
				assert isinstance(self._leftexpr, (CAttribAccessRef,CPtrAccessRef))
				self._leftexpr.name = token.content
				self._state = 5
			else:
				stateStruct.error("statement parsing: didn't expected token " + str(token) + " after " + str(self._leftexpr) + " in state " + str(self._state))
		elif self._state == 22: # after expr + op + expr with attrib/ptr access
			if isinstance(token, CIdentifier):
				assert isinstance(self._rightexpr, (CAttribAccessRef,CPtrAccessRef))
				self._rightexpr.name = token.content
				self._state = 7
			else:
				stateStruct.error("statement parsing: didn't expected token " + str(token) + " after " + str(self._leftexpr) + " in state " + str(self._state))
		elif self._state == 40: # after cast_call((expr) x)
			if self._leftexpr.args[0]._state != 5:  # something is unfinished, like a previous "->"
				self._leftexpr.args[0]._cpre3_handle_token(stateStruct, token)
			elif token in (COp("."),COp("->")):
				self._leftexpr.args[0]._cpre3_handle_token(stateStruct, token)
			else:
				self._leftexpr.args[0].finalize(stateStruct)
				self._state = 5
				self._cpre3_handle_token(stateStruct, token) # redo handling
		elif self._state == 45: # after expr + op + cast_call((expr) x)
			if self._rightexpr.args[0]._state != 5:  # something is unfinished, like a previous "->"
				self._rightexpr.args[0]._cpre3_handle_token(stateStruct, token)
			elif token in (COp("."),COp("->")):
				self._rightexpr.args[0]._cpre3_handle_token(stateStruct, token)
			else:
				self._rightexpr.args[0].finalize(stateStruct)
				self._state = 7
				self._cpre3_handle_token(stateStruct, token) # redo handling
		elif self._state in (50,51): # [expr + op + ] (expr)-cast
			if self._state == 50: funcCall = self._leftexpr
			else: funcCall = self._rightexpr
			assert isinstance(funcCall, CFuncCall)
			if not funcCall.args:
				funcCall.args = [CStatement(parent=funcCall)]
			assert len(funcCall.args) == 1
			subStatement = funcCall.args[0]
			if subStatement._state != 0 and isinstance(token, COp) and token not in (COp("."),COp("->")):
				subStatement.finalize(stateStruct, addToContent=False)
				if self._state == 50: self._state = 5
				else: self._state = 7
				self._cpre3_handle_token(stateStruct, token)
			else:
				subStatement._cpre3_handle_token(stateStruct, token)
		else:
			stateStruct.error("internal error: statement parsing: token " + str(token) + " in invalid state " + str(self._state))

	def _cpre3_parse_brackets(self, stateStruct, openingBracketToken, input_iter):
		self._handlePushedErrorForUnknown(stateStruct)

		if self._state == 0 and openingBracketToken.content == "{": # array args or struct args
			arrayArgs = CCurlyArrayArgs(parent=self)
			self._leftexpr = arrayArgs
			arrayArgs._bracketlevel = list(openingBracketToken.brackets)
			cpre3_parse_statements_in_brackets(stateStruct, arrayArgs, COp(","), arrayArgs.args, input_iter)
			arrayArgs.finalize(stateStruct)
			self._state = 5
			return

		if self._state in (50,51):  # after [expr + op +] (expr)-cast
			if self._state == 50:
				funcCall = self._leftexpr
			else:
				funcCall = self._rightexpr
			assert isinstance(funcCall, CFuncCall)
			if funcCall.args:
				assert len(funcCall.args) == 1
				assert isinstance(funcCall.args[0], CStatement)
				funcCall.args[0]._cpre3_parse_brackets(stateStruct, openingBracketToken, input_iter)
			else:
				funcCall._bracketlevel = list(openingBracketToken.brackets)
				subStatement = CStatement(parent=funcCall)
				funcCall.args += [subStatement]
				subStatement._cpre3_parse_brackets(stateStruct, openingBracketToken, input_iter)
				if subStatement._state == 50: return  # another cast follows
				funcCall.finalize(stateStruct)
				if self._state == 50:
					self._state = 5
				else:
					self._state = 7
			return

		if self._state in (5,7): # after expr or expr + op + expr
			if self._state == 5:
				ref = self._leftexpr
			else:
				ref = self._rightexpr
			if openingBracketToken.content == "(":
				funcCall = CFuncCall(parent=self)
			elif openingBracketToken.content == "[":
				funcCall = CArrayIndexRef(parent=self)
			else:
				stateStruct.error("cpre3 statement parse brackets after expr: didn't expected opening bracket '" + openingBracketToken.content + "'")
				# fallback. handle just like '('
				funcCall = CStatement(parent=self.parent)
			if self._state == 5:
				self._leftexpr = funcCall
			else:
				self._rightexpr = funcCall
			funcCall.base = ref
			funcCall._bracketlevel = list(openingBracketToken.brackets)
			cpre3_parse_statements_in_brackets(stateStruct, funcCall, COp(","), funcCall.args, input_iter)
			funcCall.finalize(stateStruct)
			return

		if self._state in (8,9): # right-to-left chain
			self._rightexpr._cpre3_parse_brackets(stateStruct, openingBracketToken, input_iter)
			if self._rightexpr._state == 5:
				self._state = 9
			return

		if self._state in (40,45): # after .. cast_call + expr
			if self._state == 40:
				ref = self._leftexpr
			else:
				ref = self._rightexpr
			assert isinstance(ref, CFuncCall)
			assert len(ref.args) == 1
			ref.args[0]._cpre3_parse_brackets(stateStruct, openingBracketToken, input_iter)
			return

		if openingBracketToken.content == "(":
			subStatement = CStatement(parent=self.parent)
		elif openingBracketToken.content == "[":
			subStatement = CArrayStatement(parent=self.parent)
		else:
			# fallback. handle just like '('. we error this below
			subStatement = CStatement(parent=self.parent)

		if self._state == 0:
			self._leftexpr = subStatement
			self._state = 5
		elif self._state == 6: # expr + op
			self._rightexpr = subStatement
			self._state = 7
		else:
			stateStruct.error("cpre3 statement parse brackets: didn't expected opening bracket '" + openingBracketToken.content + "' in state " + str(self._state))

		finalized = False
		for token in input_iter:
			if isinstance(token, COpeningBracket):
				subStatement._cpre3_parse_brackets(stateStruct, token, input_iter)
			elif isinstance(token, CClosingBracket):
				if token.brackets == openingBracketToken.brackets:
					subStatement.finalize(stateStruct, addToContent=False)
					self._tokens += [subStatement]
					finalized = True
					break
				else:
					stateStruct.error("cpre3 statement parse brackets: internal error, closing brackets " + str(token.brackets) + " not expected")
			else:
				subStatement._cpre3_handle_token(stateStruct, token)
		if not finalized:
			stateStruct.error("cpre3 statement parse brackets: incomplete, missing closing bracket '" + openingBracketToken.content + "' at level " + str(openingBracketToken.brackets))
			return
		if openingBracketToken.content == "(" and subStatement.isCType():
			# This is a C-style-cast.
			funcCall = CFuncCall(parent=self)
			funcCall.base = subStatement.asType()
			if self._state == 5:
				self._leftexpr = funcCall
				self._state = 50
			elif self._state == 7:
				self._rightexpr = funcCall
				self._state = 51
			else:
				assert False, self._state

	def getConstValue(self, stateStruct):
		if self._leftexpr is None: # prefixed only
			func = OpPrefixFuncs[self._op.content]
			v = getConstValue(stateStruct, self._rightexpr)
			if v is None: return None
			return func(v)
		v1 = getConstValue(stateStruct, self._leftexpr)
		if v1 is None: return None
		if self._op is None or self._rightexpr is None:
			return v1
		v2 = getConstValue(stateStruct, self._rightexpr)
		if v2 is None: return None
		if self._op == COp("?:"):
			assert self._middleexpr is not None
			v15 = getConstValue(stateStruct, self._middleexpr)
			if v15 is None: return None
			return v15 if v1 else v2
		assert self._middleexpr is None
		func = OpBinFuncs[self._op.content]
		return func(v1, v2)

	def getValueType(self, stateStruct):
		if self._leftexpr is None: # prefixed only
			v = getValueType(stateStruct, self._rightexpr)
			if self._op.content == "&":
				return CPointerType(v)
			elif self._op.content == "!":  # not-op
				return CBuiltinType(("char",))  # 0 or 1, not sure
			elif self._op.content == "*":
				assert isinstance(v, CPointerType)
				return v.pointerOf
			elif self._op.content in ("+","-","++","--","~"):  # OpPrefixFuncs
				return v
			else:
				assert False, "invalid prefix op %r" % self._op
		v1 = getValueType(stateStruct, self._leftexpr)
		if self._op is None or self._rightexpr is None:
			return v1
		v2 = getValueType(stateStruct, self._rightexpr)
		if self._op == COp("?:"):
			assert self._middleexpr is not None
			v15 = getValueType(stateStruct, self._middleexpr)
			if v15 is None: return None
			return getCommonValueType(stateStruct, v15, v2)
		assert self._middleexpr is None
		# see OpBinFuncs
		if self._op.content == ",":
			return v2
		elif self._op.content in ("==","!=","<","<=",">",">="):
			return CBuiltinType(("char",))  # 0 or 1, not sure
		elif self._op.content in ("&&","||"):
			return CBuiltinType(("char",))  # 0 or 1, not sure
		elif self._op.content in ("<<",">>","<<=",">>="):  # compare
			return v1
		elif self._op.content in ("=","*=","-=","+=","/=","%=","&=","^=","|="):  # assign
			return v1
		elif self._op.content in ("+","-","*","/","&","^","|"):
			return getCommonValueType(stateStruct, v1, v2)
		else:
			assert False, "invalid bin op %r" % self._op

	def isCType(self):
		if self._leftexpr is None: return False # all prefixed stuff is not a type
		if self._rightexpr is not None: return False # same thing, prefixed stuff is not a type
		t = self._leftexpr
		try:
			if issubclass(t, _ctypes._SimpleCData): return True
		except Exception: pass # e.g. typeerror or so
		if isinstance(t, (CType,CStruct,CUnion,CEnum,CTypedef)): return True
		if isinstance(t, CStatement): return t.isCType()
		return False
	
	def asType(self):
		assert self._leftexpr is not None
		assert self._rightexpr is None
		if isinstance(self._leftexpr, CStatement):
			t = self._leftexpr.asType()
		else:
			t = self._leftexpr
		if self._op is not None:
			if self._op.content in ("*","&"):
				t = CPointerType(t)
			else:
				raise Exception("postfix op " + str(self._op) + " unknown for pointer type " + str(self._leftexpr))
		return t
		
	def getCType(self, stateStruct):
		return getCType(self.asType(), stateStruct)

	def asCCode(self, indent=""):
		if self._leftexpr is None: # prefixed only
			return indent + "(" + self._op.content + asCCode(self._rightexpr) + ")"
		if self._op is None or self._rightexpr is None:
			return indent + asCCode(self._leftexpr) # no brackets. we do them outside
		if self._op == COp("?:"):
			return indent + "(" + asCCode(self._leftexpr) + " ? " + asCCode(self._middleexpr) + " : " + asCCode(self._rightexpr) + ")"
		return indent + "(" + asCCode(self._leftexpr) + " " + self._op.content + " " + asCCode(self._rightexpr) + ")"

# only real difference is that this is inside of '[]'
class CArrayStatement(CStatement):
	def asCCode(self, indent=""):
		return indent + "[" + CStatement.asCCode(self) + "]"
	
def cpre3_parse_struct(stateStruct, curCObj, input_iter):
	curCObj.body = CBody(parent=curCObj.parent.body)
	cpre3_parse_body(stateStruct, curCObj, input_iter)
	curCObj.finalize(stateStruct)

def cpre3_parse_union(stateStruct, curCObj, input_iter):
	curCObj.body = CBody(parent=curCObj.parent.body)
	cpre3_parse_body(stateStruct, curCObj, input_iter)
	curCObj.finalize(stateStruct)

def cpre3_parse_funcbody(stateStruct, curCObj, input_iter):
	curCObj.body = CBody(parent=curCObj.parent.body)
	cpre3_parse_body(stateStruct, curCObj, input_iter)
	curCObj.finalize(stateStruct)

def cpre3_parse_funcpointername(stateStruct, curCObj, input_iter):
	bracketLevel = list(curCObj._bracketlevel)
	state = 0
	for token in input_iter:
		if isinstance(token, CClosingBracket):
			if token.brackets == bracketLevel:
				return
			if not _isBracketLevelOk(bracketLevel, token.brackets):
				stateStruct.error("cpre3 parse func pointer name: internal error: bracket level messed up with closing bracket: " + str(token.brackets))

		if state == 0:
			if token == COp("*"):
				state = 1
				CFuncPointerDecl.overtake(curCObj)
				curCObj.ptrLevel = 1
			elif isinstance(token, CIdentifier):
				CFunc.overtake(curCObj)
				curCObj.name = token.content
				state = 4
			else:
				stateStruct.error("cpre3 parse func pointer name: token " + str(token) + " not expected; expected '*'")
		elif state == 1:
			if token == COp("*"):
				curCObj.ptrLevel += 1
			elif isinstance(token, CIdentifier):
				curCObj.name = token.content
				state = 2
			else:
				stateStruct.error("cpre3 parse func pointer name: token " + str(token) + " not expected; expected identifier")
		elif state == 2: # after identifier in func ptr
			if token == COpeningBracket("["):
				curCObj._bracketlevel = list(token.brackets)
				cpre3_parse_arrayargs(stateStruct, curCObj, input_iter)
				curCObj._bracketlevel = bracketLevel
			else:
				state = 3
		elif state == 4: # after identifier in func
			# we don't expect anything anymore
			state = 3
			
		if state == 3:
			stateStruct.error("cpre3 parse func pointer name: token " + str(token) + " not expected; expected ')'")

	stateStruct.error("cpre3 parse func pointer name: incomplete, missing ')' on level " + str(curCObj._bracketlevel))	

def cpre3_parse_enum(stateStruct, parentCObj, input_iter):
	parentCObj.body = CEnumBody(parent=parentCObj.parent.body)
	curCObj = CEnumConst(parent=parentCObj)
	valueStmnt = None
	state = 0
	
	for token in input_iter:
		if isinstance(token, CIdentifier):
			if state == 0:
				curCObj.name = token.content
				state = 1
			else:
				stateStruct.error("cpre3 parse enum: unexpected identifier " + token.content + " after " + str(curCObj) + " in state " + str(state))
		elif token == COp("="):
			if state == 1:
				valueStmnt = CStatement(parent=parentCObj)
				state = 2
			else:
				stateStruct.error("cpre3 parse enum: unexpected op '=' after " + str(curCObj) + " in state " + str(state))
		elif token == COp(","):
			if state in (1,2):
				if state == 2:
					valueStmnt.finalize(stateStruct, addToContent=False)
					curCObj.value = valueStmnt.getConstValue(stateStruct)
				curCObj.finalize(stateStruct)
				curCObj = CEnumConst(parent=parentCObj)
				valueStmnt = None
				state = 0
			else:
				stateStruct.error("cpre3 parse enum: unexpected op ',' after " + str(curCObj) + " in state " + str(state))
		elif isinstance(token, CClosingBracket):
			if token.brackets == parentCObj._bracketlevel:
				if curCObj:
					if state == 2:
						valueStmnt.finalize(stateStruct, addToContent=False)
						curCObj.value = valueStmnt.getConstValue(stateStruct)
					curCObj.finalize(stateStruct)
				parentCObj.finalize(stateStruct)
				return
			if not _isBracketLevelOk(parentCObj._bracketlevel, token.brackets):
				stateStruct.error("cpre3 parse enum: internal error: bracket level messed up with closing bracket: " + str(token.brackets))
		elif state == 2:
			if isinstance(token, COpeningBracket):
				valueStmnt._cpre3_parse_brackets(stateStruct, token, input_iter)
			else:
				valueStmnt._cpre3_handle_token(stateStruct, token)
		else:
			stateStruct.error("cpre3 parse enum: unexpected token " + str(token) + " in state " + str(state))
	stateStruct.error("cpre3 parse enum: incomplete, missing '}' on level " + str(parentCObj._bracketlevel))

def _cpre3_parse_skipbracketcontent(stateStruct, bracketlevel, input_iter):
	for token in input_iter:
		if isinstance(token, CClosingBracket):
			if token.brackets == bracketlevel:
				return
			if not _isBracketLevelOk(bracketlevel, token.brackets):
				stateStruct.error("cpre3 parse skip brackets: internal error: bracket level messed up with closing bracket: " + str(token.brackets))
	stateStruct.error("cpre3 parse: incomplete, missing closing bracket on level " + str(bracketlevel))
	
def cpre3_parse_funcargs(stateStruct, parentCObj, input_iter):
	curCObj = CFuncArgDecl(parent=parentCObj)
	typeObj = None
	for token in input_iter:
		if isinstance(token, CIdentifier):
			if token.content == "typedef":
				stateStruct.error("cpre3 parse func args: typedef not expected")
			elif token.content in stateStruct.Attribs:
				curCObj.attribs += [token.content]
			elif token.content == "struct":
				typeObj = CStruct()
				curCObj._type_tokens += [typeObj]
			elif token.content == "union":
				typeObj = CUnion()
				curCObj._type_tokens += [typeObj]
			elif token.content == "enum":
				typeObj = CEnum()
				curCObj._type_tokens += [typeObj]
			elif typeObj is not None:
				if typeObj.name is None:
					typeObj.name = token.content
					typeObj = None
			elif (token.content,) in stateStruct.CBuiltinTypes:
				curCObj._type_tokens += [token.content]
			elif token.content in stateStruct.StdIntTypes:
				curCObj._type_tokens += [token.content]
			elif len(curCObj._type_tokens) == 0:
				curCObj._type_tokens += [token.content]
			else:
				if curCObj.name is None:
					curCObj.name = token.content
				else:
					stateStruct.error("cpre3 parse func args: second identifier name " + token.content + " for " + str(curCObj))
		elif isinstance(token, COp):
			if token.content == ",":
				curCObj.finalize(stateStruct)
				curCObj = CFuncArgDecl(parent=parentCObj)
				typeObj = None
			else:
				curCObj._type_tokens += [token.content]
		elif isinstance(token, COpeningBracket):
			curCObj._bracketlevel = list(token.brackets)
			if token.content == "(":
				if len(curCObj._type_tokens) == 1 and isinstance(curCObj._type_tokens[0], CFuncPointerDecl):
					typeObj = curCObj._type_tokens[0]
					cpre3_parse_funcargs(stateStruct, typeObj, input_iter)
					typeObj.finalize(stateStruct)
				elif curCObj.name is None:
					typeObj = CFuncPointerDecl(parent=curCObj.parent)
					typeObj._bracketlevel = curCObj._bracketlevel
					typeObj._type_tokens[:] = curCObj._type_tokens
					curCObj._type_tokens[:] = [typeObj]
					cpre3_parse_funcpointername(stateStruct, typeObj, input_iter)
					curCObj.name = typeObj.name
				else:
					stateStruct.error("cpre3 parse func args: got unexpected '(' in " + str(curCObj))
					_cpre3_parse_skipbracketcontent(stateStruct, curCObj._bracketlevel, input_iter)
			elif token.content == "[":
				cpre3_parse_arrayargs(stateStruct, curCObj, input_iter)
			else:
				stateStruct.error("cpre3 parse func args: unexpected opening bracket '" + token.content + "'")
				_cpre3_parse_skipbracketcontent(stateStruct, curCObj._bracketlevel, input_iter)
		elif isinstance(token, CClosingBracket):
			if token.brackets == parentCObj._bracketlevel:
				if curCObj:
					curCObj.finalize(stateStruct)
				return
			if not _isBracketLevelOk(parentCObj._bracketlevel, token.brackets):
				stateStruct.error("cpre3 parse func args: internal error: bracket level messed up with closing bracket: " + str(token.brackets))
			# no error. we already errored on the opening bracket. and the cpre2 parsing ensures the rest
		else:
			stateStruct.error("cpre3 parse func args: unexpected token " + str(token))

	stateStruct.error("cpre3 parse func args: incomplete, missing ')' on level " + str(parentCObj._bracketlevel))

def cpre3_parse_arrayargs(stateStruct, curCObj, input_iter):
	valueStmnt = CStatement()
	valueStmnt._bracketlevel = curCObj._bracketlevel
	valueStmnt._cpre3_parse_brackets(stateStruct, COpeningBracket("[", brackets=curCObj._bracketlevel), input_iter)
	assert isinstance(valueStmnt._leftexpr, CArrayStatement)
	if isinstance(curCObj, (CVarDecl, CFuncArgDecl, CFuncPointerDecl)):
		arrayType = make_type_from_typetokens(stateStruct, curCObj._type_tokens)
		arrayLen = valueStmnt._leftexpr
		curCObj.type = CArrayType(arrayOf=arrayType, arrayLen=arrayLen)
	else:
		stateStruct.error("cpre3_parse_arrayargs: unexpected: %r" % curCObj)

def cpre3_parse_typedef(stateStruct, curCObj, input_iter):
	state = 0
	typeObj = None
	
	for token in input_iter:
		if state == 0:
			if isinstance(token, CIdentifier):
				if token.content == "typedef":
					stateStruct.error("cpre3 parse typedef: typedef not expected twice")
				elif token.content in stateStruct.Attribs:
					curCObj.attribs += [token.content]
				elif token.content == "struct":
					typeObj = CStruct(parent=curCObj.parent)
					curCObj._type_tokens += [typeObj]
				elif token.content == "union":
					typeObj = CUnion(parent=curCObj.parent)
					curCObj._type_tokens += [typeObj]
				elif token.content == "enum":
					typeObj = CEnum(parent=curCObj.parent)
					curCObj._type_tokens += [typeObj]
				elif (token.content,) in stateStruct.CBuiltinTypes:
					curCObj._type_tokens += [token.content]
				elif token.content in stateStruct.StdIntTypes:
					curCObj._type_tokens += [token.content]
				elif token.content in stateStruct.typedefs:
					curCObj._type_tokens += [token.content]
				else:
					if typeObj is not None and not typeObj._finalized and typeObj.name is None:
						typeObj.name = token.content
					elif curCObj._type_tokens:
						if curCObj.name is None:
							curCObj.name = token.content
						else:
							stateStruct.error("cpre3 parse in typedef: got second identifier " + token.content + " after name " + curCObj.name)
					else:
						stateStruct.error("cpre3 parse in typedef: got unexpected identifier " + token.content)
			elif token == COp("*"):
				curCObj._type_tokens += ["*"]
			elif isinstance(token, COpeningBracket):
				curCObj._bracketlevel = list(token.brackets)
				if token.content == "(":
					if len(curCObj._type_tokens) == 0 or not isinstance(curCObj._type_tokens[0], CFuncPointerDecl):
						typeObj = CFuncPointerDecl(parent=curCObj.parent)
						typeObj._bracketlevel = curCObj._bracketlevel
						typeObj._type_tokens[:] = curCObj._type_tokens
						curCObj._type_tokens[:] = [typeObj]
						if curCObj.name is None: # eg.: typedef int (*Function)();
							cpre3_parse_funcpointername(stateStruct, typeObj, input_iter)
							curCObj.name = typeObj.name
						else: # eg.: typedef int Function();
							typeObj.name = curCObj.name
							cpre3_parse_funcargs(stateStruct, typeObj, input_iter)							
					else:
						cpre3_parse_funcargs(stateStruct, typeObj, input_iter)
				elif token.content == "[":
					cpre3_parse_arrayargs(stateStruct, curCObj, input_iter)
				elif token.content == "{":
					if typeObj is not None: # it must not be None. but error handling already below
						typeObj._bracketlevel = curCObj._bracketlevel
					if isinstance(typeObj, CStruct):
						cpre3_parse_struct(stateStruct, typeObj, input_iter)
					elif isinstance(typeObj, CUnion):
						cpre3_parse_union(stateStruct, typeObj, input_iter)
					elif isinstance(typeObj, CEnum):
						cpre3_parse_enum(stateStruct, typeObj, input_iter)
					else:
						stateStruct.error("cpre3 parse in typedef: got unexpected '{' after type " + str(typeObj))
						state = 11
				else:
					stateStruct.error("cpre3 parse in typedef: got unexpected opening bracket '" + token.content + "' after type " + str(typeObj))
					state = 11
			elif isinstance(token, CSemicolon):
				if typeObj is not None and not typeObj._finalized:
					typeObj.finalize(stateStruct, addToContent = typeObj.body is not None)
				curCObj.finalize(stateStruct)
				return
			else:
				stateStruct.error("cpre3 parse typedef: got unexpected token " + str(token))
		elif state == 11: # unexpected bracket
			# just ignore everything until we get the closing bracket
			if isinstance(token, CClosingBracket):
				if token.brackets == curCObj._bracketlevel:
					state = 0
				if not _isBracketLevelOk(curCObj._bracketlevel, token.brackets):
					stateStruct.error("cpre3 parse typedef: internal error: bracket level messed up with closing bracket: " + str(token.brackets))
		else:
			stateStruct.error("cpre3 parse typedef: internal error. unexpected state " + str(state))
	stateStruct.error("cpre3 parse typedef: incomplete, missing ';'")


class CCodeBlock(_CBaseWithOptBody):
	NameIsRelevant = False
	def asCCode(self, indent=""):
		return asCCode(self.body, indent)
class CGotoLabel(_CBaseWithOptBody):
	def asCCode(self, indent=""):
		return indent + self.name + ":"

def _getLastCBody(base):
	last = None
	while True:
		if isinstance(base.body, CBody):
			if not base.body.contentlist: break
			last = base.body.contentlist[-1]
		elif isinstance(base.body, _CControlStructure):
			last = base.body
		else:
			break
		if not isinstance(last, _CControlStructure): break
		if isinstance(last, CIfStatement):
			if last.elsePart is not None:
				base = last.elsePart
			else:
				base = last
		elif isinstance(last, (CForStatement,CWhileStatement)):
			base = last
		else:
			break
	return last

class _CControlStructure(_CBaseWithOptBody):
	NameIsRelevant = False
	StrOutAttribList = [
		("args", bool, None, str),
		("body", None, None, lambda x: "<...>"),
		("defPos", None, "@", str),
	]
	def asCCode(self, indent=""):
		s = indent + self.Keyword
		if self.args: s += "(" + "; ".join(map(asCCode, self.args)) + ")"
		if self.body: s += "\n" + asCCode(self.body, indent)
		if hasattr(self, "whilePart"): s += "\n" + asCCode(self.whilePart, indent)
		if hasattr(self, "elsePart"): s += "\n" + asCCode(self.elsePart, indent)
		return s
class CForStatement(_CControlStructure):
	Keyword = "for"
class CDoStatement(_CControlStructure):
	Keyword = "do"
	StrOutAttribList = [
		("body", None, None, lambda x: "<...>"),
		("whilePart", None, None, repr),
		("defPos", None, "@", str),
	]
	whilePart = None
class CWhileStatement(_CControlStructure):
	Keyword = "while"
	def finalize(self, stateStruct, addToContent = None):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return
		assert self.parent is not None

		if isinstance(self.parent.body, CBody) and self.parent.body.contentlist:
			last = _getLastCBody(self.parent)
			if isinstance(last, CDoStatement) and not last.whilePart:
				if self.body is not None:
					stateStruct.error("'while' " + str(self) + " as part of 'do' " + str(last) + " has another body")
				last.whilePart = self
				addToContent = False

		_CControlStructure.finalize(self, stateStruct, addToContent)			
class CContinueStatement(_CControlStructure):
	Keyword = "continue"
	AlwaysNonZero = True
class CBreakStatement(_CControlStructure):
	Keyword = "break"
	AlwaysNonZero = True
class CIfStatement(_CControlStructure):
	Keyword = "if"
	StrOutAttribList = [
		("args", bool, None, str),
		("body", None, None, lambda x: "<...>"),
		("elsePart", None, None, repr),
		("defPos", None, "@", str),
	]
	elsePart = None
class CElseStatement(_CControlStructure):
	Keyword = "else"
	def finalize(self, stateStruct, addToContent = False):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return
		assert self.parent is not None

		base = self.parent
		lastIf = None
		last = None
		while True:
			if isinstance(base.body, CBody):
				if not base.body.contentlist: break
				last = base.body.contentlist[-1]
			elif isinstance(base.body, CIfStatement):
				last = base.body
			else:
				break
			if not isinstance(last, CIfStatement): break
			if last.elsePart is not None:
				base = last.elsePart
			else:
				lastIf = last
				base = lastIf
	
		if lastIf is not None:
			lastIf.elsePart = self
		else:
			stateStruct.error("'else' " + str(self) + " without 'if', last was " + str(last))
		_CControlStructure.finalize(self, stateStruct, addToContent)
class CSwitchStatement(_CControlStructure):
	Keyword = "switch"
class CCaseStatement(_CControlStructure):
	Keyword = "case"
class CCaseDefaultStatement(_CControlStructure):
	Keyword = "default"
	AlwaysNonZero = True
class CGotoStatement(_CControlStructure):
	Keyword = "goto"
class CReturnStatement(_CControlStructure):
	Keyword = "return"
	AlwaysNonZero = True

CControlStructures = dict(map(lambda c: (c.Keyword, c), [
	CForStatement,
	CDoStatement,
	CWhileStatement,
	CContinueStatement,
	CBreakStatement,
	CIfStatement,
	CElseStatement,
	CSwitchStatement,
	CCaseStatement,
	CCaseDefaultStatement,
	CGotoStatement,
	CReturnStatement,
	]))

def cpre3_parse_statements_in_brackets(stateStruct, parentCObj, sepToken, addToList, input_iter):
	brackets = list(parentCObj._bracketlevel)
	curCObj = _CBaseWithOptBody(parent=parentCObj)
	def _make_statement(o):
		assert not o.isDerived()
		CStatement.overtake(o)
		for t in o._type_tokens:
			o._cpre3_handle_token(stateStruct, CIdentifier(t))
		o._type_tokens = []
	def _finalizeCObj(o):
		if not o.isDerived():
			_make_statement(o)
		o.finalize(stateStruct, addToContent=False)
	for token in input_iter:
		if isinstance(token, CIdentifier):
			if isinstance(curCObj, CStatement):
				curCObj._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj.body, CStatement):
				curCObj.body._cpre3_handle_token(stateStruct, token)
			elif token.content in stateStruct.Attribs:
				curCObj.attribs += [token.content]
			elif token.content == "struct":
				CStruct.overtake(curCObj)
			elif token.content == "union":
				CUnion.overtake(curCObj)
			elif token.content == "enum":
				CEnum.overtake(curCObj)
			elif (token.content,) in stateStruct.CBuiltinTypes:
				curCObj._type_tokens += [token.content]
			elif token.content in stateStruct.StdIntTypes:
				curCObj._type_tokens += [token.content]
			elif token.content in stateStruct.typedefs:
				curCObj._type_tokens += [token.content]
			else:
				if curCObj._finalized:
					# e.g. like "struct {...} X" and we parse "X"
					oldObj = curCObj
					curCObj = CVarDecl(parent=parentCObj)
					curCObj._type_tokens[:] = [oldObj]

				if curCObj.name is None:
					curCObj.name = token.content
				else:
					stateStruct.error("cpre3 parse statements in brackets: second identifier name " + token.content + ", first was " + curCObj.name + ", first might be an unknwon type")
					# fallback recovery, guess vardecl with the first identifier being an unknown type
					curCObj._type_tokens += [CUnknownType(name=curCObj.name)]
					curCObj.name = token.content

				if not curCObj.isDerived():
					if len(curCObj._type_tokens) == 0:
						curCObj.name = None
						CStatement.overtake(curCObj)
						curCObj._cpre3_handle_token(stateStruct, token)
					else:
						CVarDecl.overtake(curCObj)
		elif isinstance(token, COpeningBracket):
			if isinstance(curCObj, CStatement):
				curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)
			elif isinstance(curCObj.body, CStatement):
				curCObj.body._cpre3_parse_brackets(stateStruct, token, input_iter)
			elif not curCObj.isDerived():
				_make_statement(curCObj)
				curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)
			else:
				stateStruct.error("cpre3 parse statements in brackets: " + str(token) + " not expected after " + str(curCObj))
				# fallback
				CStatement.overtake(curCObj)
				curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)				
		elif isinstance(token, CClosingBracket):
			if token.brackets == brackets:
				break
			stateStruct.error("cpre3 parse statements in brackets: unexpected closing bracket '" + token.content + "' after " + str(curCObj) + " at bracket level " + str(brackets))
		elif token == sepToken:
			_finalizeCObj(curCObj)
			addToList.append(curCObj)
			curCObj = _CBaseWithOptBody(parent=parentCObj)
		elif isinstance(token, CSemicolon): # if the sepToken is not the semicolon, we don't expect it at all
			stateStruct.error("cpre3 parse statements in brackets: ';' not expected, separator should be " + str(sepToken))
		elif isinstance(curCObj, CVarDecl) and token == COp("="):
			curCObj.body = CStatement(parent=curCObj)
		else:
			if not curCObj.isDerived():
				_make_statement(curCObj)
			if isinstance(curCObj, CStatement):
				curCObj._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj.body, CStatement):
				curCObj.body._cpre3_handle_token(stateStruct, token)
			else:
				stateStruct.error("cpre3 parse statements in brackets: " + str(token) + " not expected after " + str(curCObj))

	# add also the last object
	if isinstance(sepToken, CSemicolon) or curCObj:
		_finalizeCObj(curCObj)
		addToList.append(curCObj)

def cpre3_parse_single_next_statement(stateStruct, parentCObj, input_iter):
	curCObj = None
	for token in input_iter:
		if isinstance(token, COpeningBracket):
			if token.content == "{":
				parentCObj._bracketlevel = list(token.brackets)
				cpre3_parse_body(stateStruct, parentCObj, input_iter)
				return
			if curCObj is None:
				curCObj = CStatement(parent=parentCObj)
			if isinstance(curCObj, CStatement):
				curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)
			elif curCObj is not None and isinstance(curCObj.body, CStatement):
				curCObj.body._cpre3_parse_brackets(stateStruct, token, input_iter)
			elif isinstance(curCObj, _CControlStructure):
				curCObj._bracketlevel = list(token.brackets)
				if token.content == "(":
					cpre3_parse_statements_in_brackets(stateStruct, curCObj, sepToken=CSemicolon(), addToList=curCObj.args, input_iter=input_iter)
					curCObj._bracketlevel = list(parentCObj._bracketlevel)
					lasttoken = cpre3_parse_single_next_statement(stateStruct, curCObj, input_iter)
					curCObj.finalize(stateStruct)
					parentCObj.addToBody(curCObj)
					return lasttoken
				elif token.content == "[":
					stateStruct.error("cpre3 parse single after " + str(curCObj) + ": got unexpected '['")
					_cpre3_parse_skipbracketcontent(stateStruct, list(token.brackets), input_iter)
					return
				elif token.content == "{":
					if curCObj.body is not None:
						stateStruct.error("cpre3 parse single after " + str(curCObj) + ": got multiple bodies")
					cpre3_parse_body(stateStruct, curCObj, input_iter)
					curCObj.finalize(stateStruct)
					parentCObj.addToBody(curCObj)
					return
				else:
					stateStruct.error("cpre3 parse single after " + str(curCObj) + ": got unexpected/unknown opening bracket '" + token.content + "'")
					_cpre3_parse_skipbracketcontent(stateStruct, list(token.brackets), input_iter)
					return
			else:
				stateStruct.error("cpre3 parse single: unexpected opening bracket '" + token.content + "' after " + str(curCObj))
		elif isinstance(token, CClosingBracket):
			if token.brackets == parentCObj._bracketlevel:
				stateStruct.error("cpre3 parse single: closed brackets without expected statement")
				return token
			stateStruct.error("cpre3 parse single: unexpected closing bracket '" + token.content + "' after " + str(curCObj) + " at bracket level " + str(parentCObj._bracketlevel))
		elif isinstance(token, CSemicolon):
			if curCObj and not curCObj.isDerived():
				CVarDecl.overtake(curCObj)
			if curCObj is not None:
				curCObj.finalize(stateStruct)
				parentCObj.addToBody(curCObj)
			return token
		elif curCObj is None and isinstance(token, CIdentifier) and token.content in CControlStructures:
			curCObj = CControlStructures[token.content](parent=parentCObj)
			curCObj.defPos = stateStruct.curPosAsStr()
			if isinstance(curCObj, (CElseStatement,CDoStatement)):
				curCObj._bracketlevel = list(parentCObj._bracketlevel)
				lasttoken = cpre3_parse_single_next_statement(stateStruct, curCObj, input_iter)
				# We finalize in any way, also for 'do'. We don't do any semantic checks here
				# if there is a correct 'while' following or neither if the 'else' has a previous 'if'.
				curCObj.finalize(stateStruct)
				parentCObj.addToBody(curCObj)
				return lasttoken
			elif isinstance(curCObj, CReturnStatement):
				curCObj.body = CStatement(parent=curCObj)
		elif isinstance(curCObj, CGotoStatement):
			if curCObj.name is None:
				curCObj.name = token.content
			else:
				stateStruct.error("cpre3 parse single after %s: got second identifier %s" % (curCObj, token))
		elif isinstance(curCObj, CStatement):
			curCObj._cpre3_handle_token(stateStruct, token)
			if isinstance(curCObj, CGotoLabel):
				if parentCObj.body is None:
					parentCObj.body = CBody(parent=parentCObj.parent.body)
				parentCObj.addToBody(curCObj)
				curCObj = None
		elif curCObj is not None and isinstance(curCObj.body, CStatement):
			curCObj.body._cpre3_handle_token(stateStruct, token)
		elif isinstance(curCObj, _CControlStructure):
			stateStruct.error("cpre3 parse after %s: didn't expected identifier %s" % (curCObj, token))
		elif curCObj is None:
			curCObj = CStatement(parent=parentCObj)
			curCObj._cpre3_handle_token(stateStruct, token)
		else:
			stateStruct.error("cpre3 parse single: got unexpected token %s after %s" % (token, curCObj))
	stateStruct.error("cpre3 parse single: runaway")
	return

def cpre3_parse_body(stateStruct, parentCObj, input_iter):
	if parentCObj.body is None: parentCObj.body = CBody(parent=parentCObj.parent.body)

	curCObj = _CBaseWithOptBody(parent=parentCObj)

	while True:
		stateStruct._cpre3_atBaseLevel = False
		if parentCObj._bracketlevel is None:
			if not curCObj:
				stateStruct._cpre3_atBaseLevel = True

		try: token = next(input_iter)
		except StopIteration: break
		
		if isinstance(token, CIdentifier):
			if isinstance(curCObj, CStatement):
				curCObj._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj.body, CStatement):
				curCObj.body._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj, CGotoStatement):
				if curCObj.name is None:
					curCObj.name = token.content
				else:
					stateStruct.error("cpre3 parse after " + str(curCObj) + ": got second identifier '" + token.content + "'")
			elif isinstance(curCObj, CCaseStatement):
				if not curCObj.args or not isinstance(curCObj.args[-1], CStatement):
					curCObj.args.append(CStatement(parent=parentCObj))
				curCObj.args[-1]._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj, _CControlStructure):
				stateStruct.error("cpre3 parse after " + str(curCObj) + ": didn't expected identifier '" + token.content + "'")
			elif token.content == "typedef":
				CTypedef.overtake(curCObj)
				curCObj.defPos = stateStruct.curPosAsStr()
				cpre3_parse_typedef(stateStruct, curCObj, input_iter)
				curCObj = _CBaseWithOptBody(parent=parentCObj)							
			elif token.content in stateStruct.Attribs:
				curCObj.attribs += [token.content]
			elif token.content == "struct":
				CStruct.overtake(curCObj)
				curCObj.defPos = stateStruct.curPosAsStr()
			elif token.content == "union":
				CUnion.overtake(curCObj)
				curCObj.defPos = stateStruct.curPosAsStr()
			elif token.content == "enum":
				CEnum.overtake(curCObj)
				curCObj.defPos = stateStruct.curPosAsStr()
			elif token.content in CControlStructures:
				if curCObj.isDerived() or curCObj:
					stateStruct.error("cpre3 parse: got '" + token.content + "' after " + str(curCObj))
					# try to finalize and reset
					curCObj.finalize(stateStruct)
					curCObj = _CBaseWithOptBody(parent=parentCObj)
				CControlStructures[token.content].overtake(curCObj)
				curCObj.defPos = stateStruct.curPosAsStr()
				if isinstance(curCObj, (CElseStatement,CDoStatement)):
					curCObj._bracketlevel = list(parentCObj._bracketlevel)
					lasttoken = cpre3_parse_single_next_statement(stateStruct, curCObj, input_iter)
					# We finalize in any way, also for 'do'. We don't do any semantic checks here
					# if there is a correct 'while' following or neither if the 'else' has a previous 'if'.
					curCObj.finalize(stateStruct)
					if isinstance(lasttoken, CClosingBracket) and lasttoken.brackets == parentCObj._bracketlevel:
						return
					curCObj = _CBaseWithOptBody(parent=parentCObj)
				elif isinstance(curCObj, CReturnStatement):
					curCObj.body = CStatement(parent=curCObj)
			elif (token.content,) in stateStruct.CBuiltinTypes:
				curCObj._type_tokens += [token.content]
			elif not curCObj._type_tokens and token.content in stateStruct.StdIntTypes:
				curCObj._type_tokens += [token.content]
			elif not curCObj._type_tokens and not curCObj.isDerived() \
					and (token.content in stateStruct.vars
						 or token.content in parentCObj.body.vars
						 or (isinstance(parentCObj, CFunc)
							 and token.content in [a.name for a in parentCObj.args])):
				assert curCObj.name is None
				CStatement.overtake(curCObj)
				curCObj._cpre3_handle_token(stateStruct, token)
			elif not curCObj._type_tokens and token.content in stateStruct.typedefs:
				curCObj._type_tokens += [token.content]
			else:
				if curCObj._finalized:
					# e.g. like "struct {...} X" and we parse "X"
					oldObj = curCObj
					curCObj = CVarDecl(parent=parentCObj)
					curCObj._type_tokens[:] = [oldObj]

				if curCObj.name is None:
					curCObj.name = token.content
					DictName = None
					if isinstance(curCObj, CStruct): DictName = "structs"
					elif isinstance(curCObj, CUnion): DictName = "unions"
					elif isinstance(curCObj, CEnum): DictName = "enums"
					if DictName is not None:
						typeObj = findCObjTypeInNamespace(stateStruct, parentCObj, DictName, curCObj.name)
						if typeObj is not None and typeObj.body is not None: # if body is None, we still wait for another decl
							curCObj = CVarDecl(parent=parentCObj)
							curCObj._type_tokens += [typeObj]
				else:
					stateStruct.error("cpre3 parse: second identifier name " + token.content + ", first was " + curCObj.name + ", first might be an unknwon type")
					typeObj = CUnknownType(name=curCObj.name)
					# fallback recovery, guess vardecl with the first identifier being an unknown type
					curCObj = CVarDecl(parent=parentCObj)
					curCObj._type_tokens += [typeObj]
					curCObj.name = token.content
				
				if not curCObj.isDerived():
					if len(curCObj._type_tokens) == 0:
						curCObj.name = None
						CStatement.overtake(curCObj)
						curCObj._cpre3_handle_token(stateStruct, token)
					else:
						CVarDecl.overtake(curCObj)					
		elif isinstance(token, COp):
			if (not curCObj.isDerived() or isinstance(curCObj, CVarDecl)) and len(curCObj._type_tokens) == 0:
				CStatement.overtake(curCObj)
			if isinstance(curCObj, CStatement):
				curCObj._cpre3_handle_token(stateStruct, token)
				if curCObj._finalized: # might have been finalized internally. e.g. in case it was a goto-loop
					curCObj = _CBaseWithOptBody(parent=parentCObj)					
			elif isinstance(curCObj.body, CStatement) and token.content != ",": # op(,) gets some extra handling. eg for CVarDecl
				curCObj.body._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj, CCaseStatement):
				if token.content == ":":
					curCObj.finalize(stateStruct)
					curCObj = _CBaseWithOptBody(parent=parentCObj)
				else:
					if not curCObj.args or not isinstance(curCObj.args[-1], CStatement):
						curCObj.args.append(CStatement(parent=parentCObj))
					curCObj.args[-1]._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj, CCaseDefaultStatement) and token.content == ":":
				curCObj.finalize(stateStruct)
				curCObj = _CBaseWithOptBody(parent=parentCObj)
			elif isinstance(curCObj, _CControlStructure):
				if isinstance(curCObj.body, CStatement): # for example, because of op(,), we might have missed that above
					curCObj.body._cpre3_handle_token(stateStruct, token)
				else:	
					stateStruct.error("cpre3 parse after " + str(curCObj) + ": didn't expected op '" + token.content + "'")
			else:
				if token.content == "*":
					if isinstance(curCObj, (CStruct,CUnion,CEnum)):
						curCObj.finalize(stateStruct)
						oldObj = curCObj
						curCObj = CVarDecl(parent=parentCObj)
						curCObj._type_tokens[:] = [oldObj, "*"]
					else:
						CVarDecl.overtake(curCObj)
						curCObj._type_tokens += [token.content]
				elif token.content == ",":
					CVarDecl.overtake(curCObj)
					oldObj = curCObj
					curCObj = curCObj.copy()
					curCObj._already_added = False
					oldObj.finalize(stateStruct)
					curCObj.clearDeclForNextVar()
					curCObj.name = None
					curCObj.body = None
				elif token.content == ":" and curCObj and curCObj._type_tokens and curCObj.name:
					CVarDecl.overtake(curCObj)
					curCObj.bitsize = None
				elif token.content == "=" and curCObj and (isinstance(curCObj, CVarDecl) or not curCObj.isDerived()):
					if not curCObj.isDerived():
						CVarDecl.overtake(curCObj)
					curCObj.body = CStatement(parent=curCObj)
					if isinstance(curCObj, CVarDecl):
						# Early add, so that the var init body can reference it's own instance,
						# e.g. its pointer.
						_addToParent(curCObj, stateStruct, dictName="vars")
						curCObj._already_added = True
				else:
					stateStruct.error("cpre3 parse: op '" + token.content + "' not expected in " + str(parentCObj) + " after " + str(curCObj))
		elif isinstance(token, CNumber):
			if isinstance(curCObj, CVarDecl) and hasattr(curCObj, "bitsize"):
				curCObj.bitsize = token.content
			elif isinstance(curCObj, CStatement):
				curCObj._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj.body, CStatement):
				curCObj.body._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj, CCaseStatement):
				if not curCObj.args or not isinstance(curCObj.args[-1], CStatement):
					curCObj.args.append(CStatement(parent=parentCObj))
				curCObj.args[-1]._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj, _CControlStructure):
				stateStruct.error("cpre3 parse after " + str(curCObj) + ": didn't expected number '" + str(token.content) + "'")
			else:
				CStatement.overtake(curCObj)
				curCObj._cpre3_handle_token(stateStruct, token)
		elif isinstance(token, COpeningBracket):
			curCObj._bracketlevel = list(token.brackets)
			if not _isBracketLevelOk(parentCObj._bracketlevel, token.brackets):
				stateStruct.error("cpre3 parse body: internal error: bracket level messed up with opening bracket: " + str(token.brackets) + " on level " + str(parentCObj._bracketlevel) + " in " + str(parentCObj))
			if isinstance(curCObj, CStatement):
				if token.content == "{":
					cpre3_parse_body(stateStruct, curCObj, input_iter)
					curCObj.finalize(stateStruct)
					curCObj = _CBaseWithOptBody(parent=parentCObj)
				else:
					curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)
			elif isinstance(curCObj.body, CStatement):
				curCObj.body._cpre3_parse_brackets(stateStruct, token, input_iter)
			elif isinstance(curCObj, CCaseStatement):
				if not curCObj.args or not isinstance(curCObj.args[-1], CStatement):
					curCObj.args.append(CStatement(parent=parentCObj))
				curCObj.args[-1]._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj, _CControlStructure):
				if token.content == "(":
					cpre3_parse_statements_in_brackets(stateStruct, curCObj, sepToken=CSemicolon(), addToList=curCObj.args, input_iter=input_iter)
					curCObj._bracketlevel = list(parentCObj._bracketlevel or [])
					lasttoken = cpre3_parse_single_next_statement(stateStruct, curCObj, input_iter)
					curCObj.finalize(stateStruct)
					if isinstance(lasttoken, CClosingBracket) and lasttoken.brackets == parentCObj._bracketlevel:
						return
					curCObj = _CBaseWithOptBody(parent=parentCObj)
				elif token.content == "[":
					stateStruct.error("cpre3 parse after " + str(curCObj) + ": got unexpected '['")
					_cpre3_parse_skipbracketcontent(stateStruct, list(token.brackets), input_iter)
				elif token.content == "{":
					if curCObj.body is not None:
						stateStruct.error("cpre3 parse after " + str(curCObj) + ": got multiple bodies")
					cpre3_parse_body(stateStruct, curCObj, input_iter)
					curCObj.finalize(stateStruct)
					curCObj = _CBaseWithOptBody(parent=parentCObj)
				else:
					stateStruct.error("cpre3 parse after " + str(curCObj) + ": got unexpected/unknown opening bracket '" + token.content + "'")
					_cpre3_parse_skipbracketcontent(stateStruct, list(token.brackets), input_iter)
			elif token.content == "(":
				if len(curCObj._type_tokens) == 0:
					CStatement.overtake(curCObj)
					curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)
				elif curCObj.name is None:
					typeObj = CFuncPointerDecl(parent=curCObj.parent)
					typeObj._bracketlevel = curCObj._bracketlevel
					typeObj._type_tokens[:] = curCObj._type_tokens
					CVarDecl.overtake(curCObj)
					curCObj._type_tokens[:] = [typeObj]
					cpre3_parse_funcpointername(stateStruct, typeObj, input_iter)
					curCObj.name = typeObj.name
				elif len(curCObj._type_tokens) == 1 and isinstance(curCObj._type_tokens[0], CFuncPointerDecl):
					typeObj = curCObj._type_tokens[0]
					cpre3_parse_funcargs(stateStruct, typeObj, input_iter)
					typeObj.finalize(stateStruct)
				else:
					CFunc.overtake(curCObj)
					curCObj.defPos = stateStruct.curPosAsStr()
					cpre3_parse_funcargs(stateStruct, curCObj, input_iter)
			elif token.content == "[":
				CVarDecl.overtake(curCObj)
				cpre3_parse_arrayargs(stateStruct, curCObj, input_iter)
			elif token.content == "{":
				if curCObj.isDerived():
					if isinstance(curCObj, CStruct):
						cpre3_parse_struct(stateStruct, curCObj, input_iter)
					elif isinstance(curCObj, CUnion):
						cpre3_parse_union(stateStruct, curCObj, input_iter)
					elif isinstance(curCObj, CEnum):
						cpre3_parse_enum(stateStruct, curCObj, input_iter)
					elif isinstance(curCObj, CFunc):
						cpre3_parse_funcbody(stateStruct, curCObj, input_iter)
						curCObj = _CBaseWithOptBody(parent=parentCObj)
					else:
						stateStruct.error("cpre3 parse: unexpected '{' after " + str(curCObj))
						curCObj = _CBaseWithOptBody(parent=parentCObj)
				else:
					if not parentCObj.body is stateStruct: # not top level
						CCodeBlock.overtake(curCObj)
						curCObj.defPos = stateStruct.curPosAsStr()
						cpre3_parse_body(stateStruct, curCObj, input_iter)
						curCObj.finalize(stateStruct)
					curCObj = _CBaseWithOptBody(parent=parentCObj)
			else:
				stateStruct.error("cpre3 parse: unexpected opening bracket '" + token.content + "'")
		elif isinstance(token, CClosingBracket):
			if token.content == "}":
				curCObj.finalize(stateStruct)
				curCObj = _CBaseWithOptBody(parent=parentCObj)
			else:
				stateStruct.error("cpre3 parse: unexpected closing bracket '" + token.content + "' after " + str(curCObj))
			if token.brackets == parentCObj._bracketlevel:
				return
			if not _isBracketLevelOk(parentCObj._bracketlevel, token.brackets):
				stateStruct.error("cpre3 parse body: internal error: bracket level messed up with closing bracket: " + str(token.brackets) + " on level " + str(parentCObj._bracketlevel) + " in " + str(parentCObj))
		elif isinstance(token, CSemicolon):
			if not curCObj.isDerived() and curCObj:
				CVarDecl.overtake(curCObj)
			if not curCObj._finalized:
				curCObj.finalize(stateStruct)
			curCObj = _CBaseWithOptBody(parent=parentCObj)
		elif isinstance(token, (CStr,CChar)):
			if isinstance(curCObj, CStatement):
				curCObj._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj.body, CStatement):
				curCObj.body._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj, CCaseStatement):
				if not curCObj.args or not isinstance(curCObj.args[-1], CStatement):
					curCObj.args.append(CStatement(parent=parentCObj))
				curCObj.args[-1]._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj, _CControlStructure):
				stateStruct.error("cpre3 parse after " + str(curCObj) + ": didn't expected " + str(token))
			elif not curCObj:
				CStatement.overtake(curCObj)
				curCObj._cpre3_handle_token(stateStruct, token)
			else:
				stateStruct.error("cpre3 parse: unexpected str " + str(token) + " after " + str(curCObj))
		else:
			stateStruct.error("cpre3 parse: unexpected token " + str(token))

	if curCObj and not curCObj._finalized:
		stateStruct.error("cpre3 parse: unfinished " + str(curCObj) + " at end of " + str(parentCObj))

	if parentCObj._bracketlevel is not None:
		stateStruct.error("cpre3 parse: read until end without closing brackets " + str(parentCObj._bracketlevel) + " in " + str(parentCObj))

def cpre3_parse(stateStruct, input):
	input_iter = iter(input)
	parentObj = _CBaseWithOptBody()
	parentObj.body = stateStruct
	cpre3_parse_body(stateStruct, parentObj, input_iter)

def parse(filename, state=None):
	if state is None:
		state = State()
		state.autoSetupSystemMacros()

	preprocessed = state.preprocess_file(filename, local=True)
	tokens = cpre2_parse(state, preprocessed)
	cpre3_parse(state, tokens)
	
	return state

def parse_code(source_code, state=None):
	if state is None:
		state = State()
		state.autoSetupSystemMacros()

	try:
		preprocessed = state.preprocess_source_code(source_code)
		tokens = cpre2_parse(state, preprocessed)
		cpre3_parse(state, tokens)
	except Exception as e:
		state.error("internal exception: %r" % e)
		print "parsing errors:"
		for s in state._errors: print s
		raise

	return state


def demo_parse_file(filename):
	import better_exchook
	better_exchook.install()
	from pprint import pprint

	state = State()
	state.autoSetupSystemMacros()

	preprocessed = state.preprocess_file(filename, local=True)
	tokens = cpre2_parse(state, preprocessed)
	
	token_list = []
	def copy_hook(input, output):
		for x in input:
			output.append(x)
			yield x
	tokens = copy_hook(tokens, token_list)
	
	cpre3_parse(state, tokens)
	if state._errors:
		print "parse errors:"
		pprint(state._errors)

	return state, token_list

if __name__ == '__main__':
	import sys
	demo_parse_file(sys.argv[1])
