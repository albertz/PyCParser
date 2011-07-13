# PyCParser main file
# by Albert Zeyer, 2011
# code under LGPL

import ctypes, _ctypes

SpaceChars = " \t"
LowercaseLetterChars = "abcdefghijklmnopqrstuvwxyz"
LetterChars = LowercaseLetterChars + LowercaseLetterChars.upper()
NumberChars = "0123456789"
OpChars = "&|=!+-*/%<>^~?:,."
LongOps = map(lambda c: c+"=", "&|=+-*/%<>^~!") + ["--","++","->","<<",">>","&&","||","<<=",">>=","::",".*","->*"]
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
	"-": (lambda x: +x),
	"&": (lambda x: ctypes.pointer(x)),
	"*": (lambda x: x.content),
	"++": (lambda x: ++x),
	"--": (lambda x: --x),
	"!": (lambda x: not x),
	"~": (lambda x: ~x),
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
	elif c == "0": return "\0"
	elif c == "\n": return "\n"
	elif c == '"': return '"'
	elif c == "'": return "'"
	else:
		# Just to be sure so that users don't run into trouble.
		assert False, "simple_escape_char: cannot handle " + repr(c) + " yet"
		return c

def escape_cstr(s):
	return s.replace('"', '\\"')

def parse_macro_def_rightside(stateStruct, argnames, input):
	assert argnames is not None
	assert input is not None
	if stateStruct is None:
		class Dummy:
			def error(self, s): pass
		stateStruct = Dummy()

	def f(*args):
		args = dict(map(lambda i: (argnames[i], args[i]), range(len(argnames))))
		
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

		if state == 1:
			if lastidentifier in args:
				ret += args[lastidentifier]
			else:
				ret += lastidentifier

		return ret

	return f

class Macro:
	def __init__(self, state=None, macroname=None, args=None, rightside=None):
		self.name = macroname
		self.args = args if (args is not None) else ()
		self.rightside = rightside if (rightside is not None) else ""
		self.defPos = state.curPosAsStr() if state else "<unknown>"
		self._tokens = None
	def __str__(self):
		return "(" + ", ".join(self.args) + ") -> " + self.rightside
	def __repr__(self):
		return "<Macro: " + str(self) + ">"
	def eval(self, state, args):
		if len(args) != len(self.args): raise TypeError, "invalid number of args (" + str(args) + ") for " + repr(self)
		func = parse_macro_def_rightside(state, self.args, self.rightside)
		return func(*args)
	def __call__(self, *args):
		return self.eval(None, args)
	def __eq__(self, other):
		if not isinstance(other, Macro): return False
		return self.args == other.args and self.rightside == other.rightside
	def __ne__(self, other): return not self == other
	def _parseTokens(self, stateStruct):
		assert len(self.args) == 0
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
class CType:
	def __init__(self, **kwargs):
		for k,v in kwargs.iteritems():
			setattr(self, k, v)
	def __repr__(self):
		return self.__class__.__name__ + " " + str(self.__dict__)
	def __eq__(self, other):
		if not hasattr(other, "__class__"): return False
		return self.__class__ is other.__class__ and self.__dict__ == other.__dict__
	def __ne__(self, other): return not self == other
	def __hash__(self): return hash(self.__class__) + 31 * hash(tuple(sorted(self.__dict__.iteritems())))
	def getCType(self, stateStruct):
		raise NotImplementedError, str(self) + " getCType is not implemented"

class CUnknownType(CType): pass
class CVoidType(CType):
	def __repr__(self): return "void"
	def getCType(self, stateStruct): return None

class CPointerType(CType):
	def __init__(self, ptr): self.pointerOf = ptr
	def getCType(self, stateStruct):
		try:
			t = getCType(self.pointerOf, stateStruct)
			ptrType = ctypes.POINTER(t)
			return ptrType
		except Exception, e:
			stateStruct.error(str(self) + ": error getting type (" + str(e) + "), falling back to void-ptr")
		return ctypes.c_void_p

class CBuiltinType(CType):
	def __init__(self, builtinType): self.builtinType = builtinType
	def getCType(self, stateStruct): return getCType(self.builtinType, stateStruct)

class CStdIntType(CType):
	def __init__(self, name): self.name = name
	def getCType(self, stateStruct): return stateStruct.StdIntTypes[self.name]

class CTypedefType(CType):
	def __init__(self, name): self.name = name
	def getCType(self, stateStruct):
		return getCType(stateStruct.typedefs[self.name], stateStruct)
		
def getCType(t, stateStruct):
	assert not isinstance(t, CUnknownType)
	try:
		if issubclass(t, _ctypes._SimpleCData): return t
	except: pass # e.g. typeerror or so
	if isinstance(t, _CBaseWithOptBody):
		return t.getCType(stateStruct)
	if isinstance(t, CType):
		return t.getCType(stateStruct)
	raise Exception, str(t) + " cannot be converted to a C type"

def getSizeOf(t, stateStruct):
	t = getCType(t, stateStruct)
	return ctypes.sizeof(t)

class State:
	EmptyMacro = Macro(None, None, (), "")
	CBuiltinTypes = {
		("void",): CVoidType(),
		("void", "*"): ctypes.c_void_p,
		("char",): ctypes.c_char,
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
		"FILE": ctypes.c_int, # NOTE: not really correct but shouldn't matter unless we directly access it
	}
	Attribs = [
		"const",
		"extern",
		"static",
		"register",
		"volatile",
		"__inline__",
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
	
	def autoSetupSystemMacros(self):
		import sys
		self.macros["__GNUC__"] = self.EmptyMacro # most headers just behave more sane with this :)
		if sys.platform == "darwin":
			self.macros["__APPLE__"] = self.EmptyMacro
			self.macros["__MACH__"] = self.EmptyMacro
			self.macros["__MACOSX__"] = self.EmptyMacro
			self.macros["i386"] = self.EmptyMacro
			self.macros["MAC_OS_X_VERSION_MIN_REQUIRED"] = Macro(rightside="1030")
	
	def autoSetupGlobalIncludeWrappers(self):
		from globalincludewrappers import Wrapper
		Wrapper().install(self)
	
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
	
	def error(self, s):
		self._errors.append(self.curPosAsStr() + ": " + s)

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
		except Exception, e:
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

	def preprocess(self, reader, fullfilename, filename):
		self.incIncludeLineChar(fullfilename=fullfilename, inc=filename)
		for c in cpreprocess_parse(self, reader):
			yield c		
		self._preprocessIncludeLevel = self._preprocessIncludeLevel[:-1]		

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
	return arg in state.macros

def cpreprocess_evaluate_single(state, arg):
	if arg == "": return None	
	try: return int(arg) # is integer?
	except: pass
	if len(arg) >= 2 and arg[0] == '"' and arg[-1] == '"': return arg[1:-1] # is string?
	
	if not is_valid_defname(arg):
		state.error("preprocessor eval single: '" + arg + "' is not a valid macro name")
		return 0
	if arg not in state.macros:
		state.error("preprocessor eval single: '" + arg + "' is unknown")
		return 0
	try:
		resolved = state.macros[arg]()
	except Exception, e:
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
					stateStruct.error("preprocessor: runaway ')'")
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
							stateStruct.error("preprocessor eval call: '" + macroname + "' is not a valid macro name")
							return
						if arg not in stateStruct.macros:
							stateStruct.error("preprocessor eval call: '" + macroname + "' is unknown")
							return
						macro = stateStruct.macros[macroname]
						try:
							resolved = macro.eval(stateStruct, args)
						except Exception, e:
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
							if OpPrecedences[opstr] >= 6: # +,-,==, etc
								# WARNING/HACK: guess that the following has lower or equal precedence :)
								# HACK: add "()"
								condstr = condstr[:i] + "(" + condstr[i:] + ")"
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
	args = []
	rightside = ""
	for c in arg:
		if state == 0:
			if c in SpaceChars:
				if macroname != "": state = 3
			elif c == "(": state = 2
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
			elif state == 2: # in the middle of the command
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
						if not stateStruct._preprocessIgnoreCurrent: yield "/"
					elif state == 2:
						if arg is None: arg = ""
						arg += "/"
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
				else: pass
			else:
				stateStruct.error("internal error: invalid state " + str(state))
				state = 0 # reset. it's the best we can do

		if c == "\n": stateStruct.incIncludeLineChar(line=1)
		elif c == "\t": stateStruct.incIncludeLineChar(char=4, charMod=4)
		else: stateStruct.incIncludeLineChar(char=1)

class _CBase:
	def __init__(self, content=None, rawstr=None, **kwargs):
		self.content = content
		self.rawstr = rawstr
		for k,v in kwargs.iteritems():
			setattr(self, k, v)
	def __repr__(self):
		if self.content is None: return "<" + self.__class__.__name__ + ">"
		return "<" + self.__class__.__name__ + " " + str(self.content) + ">"
	def __eq__(self, other):
		return self.__class__ is other.__class__ and self.content == other.content
	def __hash__(self): return hash(self.__class__) + 31 * hash(self.content)
	def asCCode(self): return self.content

class CStr(_CBase):
	def __repr__(self): return "<" + self.__class__.__name__ + " " + repr(self.content) + ">"
	def asCCode(self): return '"' + escape_cstr(self.content) + '"'
class CChar(_CBase):
	def __repr__(self): return "<" + self.__class__.__name__ + " " + repr(self.content) + ">"
	def asCCode(self): return "'" + escape_cstr(self.content) + '"'
class CNumber(_CBase):
	def asCCode(self): return self.rawstr
class CIdentifier(_CBase): pass
class COp(_CBase): pass
class CSemicolon(_CBase):
	def asCCode(self): return ";"	
class COpeningBracket(_CBase): pass
class CClosingBracket(_CBase): pass

def cpre2_parse_number(stateStruct, s):
	if len(s) > 1 and s[0] == "0" and s[1] in NumberChars:
		try:
			return long(s, 8)
		except Exception, e:
			stateStruct.error("cpre2_parse_number: " + s + " looks like octal but got error " + str(e))
			return 0
	if len(s) > 1 and s[0] == "0" and s[1] in "xX":
		try:
			return long(s, 16)
		except Exception, e:
			stateStruct.error("cpre2_parse_number: " + s + " looks like hex but got error " + str(e))
			return 0
	try:
		s = s.rstrip("ULul")
		return long(s)
	except Exception, e:
		stateStruct.error("cpre2_parse_number: " + s + " cannot be parsed: " + str(e))
		return 0

def cpre2_parse(stateStruct, input, brackets = None):
	state = 0
	if brackets is None: brackets = []
	laststr = ""
	macroname = ""
	macroargs = []
	macrobrackets = []
	import itertools
	for c in itertools.chain(input, "\n"):
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
					brackets += [c]
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
				else:
					stateStruct.error("cpre2 parse: didn't expected char '" + c + "'")
			elif state == 10: # number
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
					if laststr in stateStruct.macros:
						macroname = laststr
						macroargs = []
						macrobrackets = []
						state = 31
						if len(stateStruct.macros[macroname].args) == 0:
							state = 32 # finalize macro directly. there can't be any args
						breakLoop = False
					else:
						yield CIdentifier(laststr)
						laststr = ""
						state = 0
						breakLoop = False
			elif state == 31: # after macro identifier
				if not macrobrackets and c in SpaceChars + "\n": pass
				elif c in OpeningBrackets:
					if len(macrobrackets) == 0 and c != "(":
						state = 32
						breakLoop = False
					else:
						if macrobrackets:
							if len(macroargs) == 0: macroargs = [""]
							macroargs[-1] += c
						macrobrackets += [c]
				elif c in ClosingBrackets:
					if len(macrobrackets) == 0:
						state = 32
						breakLoop = False
					elif ClosingBrackets[len(OpeningBrackets) - OpeningBrackets.index(macrobrackets[-1]) - 1] != c:
						stateStruct.error("cpre2 parse: got '" + c + "' but macro-bracket level was " + str(macrobrackets))
						# ignore
					else:
						macrobrackets[:] = macrobrackets[:-1]
						if macrobrackets:
							if len(macroargs) == 0: macroargs = [""]
							macroargs[-1] += c
						else:
							state = 32
							# break loop, we consumed this char
				elif c == ",":
					if macrobrackets:
						if len(macrobrackets) == 1:
							if len(macroargs) == 0: macroargs = ["",""]
							else: macroargs += [""]
						else:
							if len(macroargs) == 0: macroargs = [""]
							macroargs[-1] += c
					else:
						state = 32
						breakLoop = False
				else:
					if macrobrackets:
						if len(macroargs) == 0: macroargs = [""]
						macroargs[-1] += c
					else:
						state = 32
						breakLoop = False
			elif state == 32: # finalize macro
				try:
					resolved = stateStruct.macros[macroname].eval(stateStruct, macroargs)
					for t in cpre2_parse(stateStruct, resolved, brackets):
						yield t
				except Exception, e:
					stateStruct.error("cpre2 parse unfold macro " + macroname + " error: " + str(e))
				state = 0
				breakLoop = False
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

	
class CBody:
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
	def __str__(self): return str(self.contentlist)
	def __repr__(self): return "<CBody " + str(self) + ">"

def findIdentifierInBody(body, name):
	if name in body.enumconsts:
		return body.enumconsts[name]
	if body.parent is not None:
		return findIdentifierInBody(body.parent, name)
	return None

def make_type_from_typetokens(stateStruct, type_tokens):
	if len(type_tokens) == 1 and isinstance(type_tokens[0], _CBaseWithOptBody):
		t = type_tokens[0]
	elif tuple(type_tokens) in stateStruct.CBuiltinTypes:
		t = CBuiltinType(stateStruct.CBuiltinTypes[tuple(type_tokens)])
	elif len(type_tokens) > 1 and type_tokens[-1] == "*":
		t = CPointerType(make_type_from_typetokens(stateStruct, type_tokens[:-1]))
	elif len(type_tokens) == 1 and type_tokens[0] in stateStruct.StdIntTypes:
		t = CStdIntType(type_tokens[0])
	elif len(type_tokens) == 1 and type_tokens[0] in stateStruct.typedefs:
		t = CTypedefType(type_tokens[0])
	else:
		t = None
	return t

class _CBaseWithOptBody:
	NameIsRelevant = True
	AutoAddToContent = True
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
		for k,v in kwargs.iteritems():
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
			", ".join(map(lambda (a,b): a + ": " + str(b), l))

	def __repr__(self): return "<" + str(self) + ">"

	def __nonzero__(self):
		return \
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
	
	def copy(self):
		import copy
		return copy.deepcopy(self, memo={id(self.parent): self.parent})

	def getCType(self, stateStruct):
		raise Exception, str(self) + " cannot be converted to a C type"
	
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

		self.parent.body.typedefs[self.name] = self.type
	def getCType(self, stateStruct): return getCType(self.type, stateStruct)
	
class CFuncPointerDecl(_CBaseWithOptBody):
	def finalize(self, stateStruct, addToContent=None):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return
		
		self.type = make_type_from_typetokens(stateStruct, self._type_tokens)
		_CBaseWithOptBody.finalize(self, stateStruct, addToContent)
		
		if self.type is None:
			stateStruct.error("finalize " + str(self) + ": type is unknown")
		# Name can be unset. It depends where this is declared.
	def getCType(self, stateStruct):
		restype = getCType(self.type, stateStruct)
		argtypes = map(lambda a: getCType(a, stateStruct), self.args)
		return ctypes.CFUNCTYPE(restype, *argtypes)
		
def _finalizeBasicType(obj, stateStruct, dictName=None, listName=None, addToContent=None):
	if obj._finalized:
		stateStruct.error("internal error: " + str(obj) + " finalized twice")
		return
	
	if addToContent is None:
		addToContent = obj.name is not None

	obj.type = make_type_from_typetokens(stateStruct, obj._type_tokens)
	_CBaseWithOptBody.finalize(obj, stateStruct, addToContent=addToContent)
	
	if addToContent and hasattr(obj.parent, "body"):
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

class CFunc(_CBaseWithOptBody):
	finalize = lambda *args: _finalizeBasicType(*args, dictName="funcs")
	def getCType(self, stateStruct):
		restype = getCType(self.type, stateStruct)
		argtypes = map(lambda a: getCType(a, stateStruct), self.args)
		return ctypes.CFUNCTYPE(restype, *argtypes)
		
class CVarDecl(_CBaseWithOptBody):
	finalize = lambda *args: _finalizeBasicType(*args, dictName="vars")	

def _getCTypeStruct(baseClass, obj, stateStruct):
	if hasattr(obj, "_ctype"): return obj._ctype
	assert hasattr(obj, "body"), str(obj) + " must have the body attrib"
	assert obj.body is not None, str(obj) + ".body must not be None. maybe it was only forward-declarated?"
	fields = []
	for c in obj.body.contentlist:
		if not isinstance(c, CVarDecl): continue
		t = getCType(c.type, stateStruct)
		if c.arrayargs:
			if len(c.arrayargs) != 1: raise Exception, str(c) + " has too many array args"
			n = c.arrayargs[0].value
			t = t * n
		if hasattr(c, "bitsize"):
			fields += [(c.name, t, c.bitsize)]
		else:
			fields += [(c.name, t)]
	class ctype(baseClass):
		_fields_ = fields
	obj._ctype = ctype
	return ctype
	
class CStruct(_CBaseWithOptBody):
	finalize = lambda *args, **kwargs: _finalizeBasicType(*args, dictName="structs", **kwargs)
	def getCType(self, stateStruct):
		return _getCTypeStruct(ctypes.Structure, self, stateStruct)

class CUnion(_CBaseWithOptBody):
	finalize = lambda *args, **kwargs: _finalizeBasicType(*args, dictName="unions", **kwargs)
	def getCType(self, stateStruct):
		return _getCTypeStruct(ctypes.Union, self, stateStruct)

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
		if a >= 0 and b < (1<<32): t = ctypes.c_uint32
		elif a >= -(1<<31) and b < (1<<31): t = ctypes.c_int32
		elif a >= 0 and b < (1<<64): t = ctypes.c_uint64
		elif a >= -(1<<63) and b < (1<<63): t = ctypes.c_int64
		else: raise Exception, str(self) + " has a too high number range " + str((a,b))
		class EnumType(t):
			_typeStruct = self
			def __repr__(self):
				v = self._typeStruct.getEnumConst(self.value)
				if v is None: v = self.value
				return "<" + str(v) + ">"
			def __cmp__(self, other):
				return cmp(self.value, other)
		for c in self.body.contentlist:
			if not c.name: continue
			if hasattr(EnumType, c.name): continue
			setattr(EnumType, c.name, c.value)
		return EnumType
	
class CEnumConst(_CBaseWithOptBody):
	def finalize(self, stateStruct, addToContent=None):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return

		if self.value is None:
			if self.parent.body.contentlist:
				last = self.parent.body.contentlist[-1]
				self.value = last.value + 1
			else:
				self.value = 0

		_CBaseWithOptBody.finalize(self, stateStruct, addToContent)

		if self.name:
			# self.parent.parent is the parent of the enum
			self.parent.parent.body.enumconsts[self.name] = self
	def getConstValue(self, stateStruct):
		return self.value
	
class CFuncArgDecl(_CBaseWithOptBody):
	AutoAddToContent = False	
	def finalize(self, stateStruct, addToContent=False):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return
			
		self.type = make_type_from_typetokens(stateStruct, self._type_tokens)
		_CBaseWithOptBody.finalize(self, stateStruct, addToContent=False)
		
		if self.type != CBuiltinType(CVoidType()):
			self.parent.args += [self]
	def getCType(self, stateStruct):
		return getCType(self.type, stateStruct)

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
	if name in body.funcs:
		return body.funcs[name]
	elif name in body.typedefs:
		return body.typedefs[name]
	elif name in body.vars:
		return body.vars[name]
	elif name in body.enumconsts:
		return body.enumconsts[name]
	elif (name,) in getattr(body, "CBuiltinTypes", {}):
		return body.CBuiltinTypes[(name,)]
	elif name in getattr(body, "StdIntTypes", {}):
		return body.StdIntTypes[name]
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
	
class CFuncCall(_CStatementCall): pass # base(args) or (base)args; i.e. can also be a simple cast
class CArrayIndexRef(_CStatementCall): pass # base[args]
class CAttribAccessRef(_CStatementCall): pass # base.name
class CPtrAccessRef(_CStatementCall): pass # base->name

def _create_cast_call(stateStruct, parent, base, token):
	funcCall = CFuncCall(parent=parent)
	funcCall.base = base
	arg = CStatement(parent=funcCall)
	funcCall.args = [arg]
	arg._cpre3_handle_token(stateStruct, token)
	arg.finalize(stateStruct)
	funcCall.finalize(stateStruct)
	return funcCall

def opsDoLeftToRight(stateStruct, op1, op2):
	if op1 == "?": return False
	
	try: opprec1 = OpPrecedences[op1]
	except:
		stateStruct.error("internal error: statement parsing: op " + op1 + " unknown")
		opprec1 = 100
	try: opprec2 = OpPrecedences[op2]
	except:
		stateStruct.error("internal error: statement parsing: op " + op2 + " unknown")
		opprec2 = 100
	
	if opprec1 < opprec2:
		return True
	elif opprec1 > opprec2:
		return False
	if op1 in OpsRightToLeft:
		return False
	return True

def getConstValue(stateStruct, obj):
	if hasattr(obj, "getConstValue"): return obj.getConstValue(stateStruct)
	if isinstance(obj, (CNumber,CStr,CChar)):
		return obj.content
	stateStruct.error("don't know how to get const value from " + str(obj))
	return None

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
		elif self._rightexpr is not None:
			s += " "
			s += str(self._op) if self._op is not None else "<None>"
			s += " "
			s += repr(self._rightexpr)
		if self.defPos is not None: s += " @: " + self.defPos
		return "<" + s + ">"
	__str__ = __repr__
	def _initStatement(self):
		self._state = 0
		self._tokens = []
		self._prefixOps = []
	def __init__(self, **kwargs):
		self._initStatement()
		_CBaseWithOptBody.__init__(self, **kwargs)
	@classmethod
	def overtake(cls, obj):
		obj.__class__ = cls
		obj._initStatement()
	def _cpre3_handle_token(self, stateStruct, token):
		self._tokens += [token]
		
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
					else:
						obj = findObjInNamespace(stateStruct, self.parent, token.content)
						if obj is None:
							stateStruct.error("statement parsing: identifier '" + token.content + "' unknown")
							obj = CUnknownType(name=token.content)
				else:
					obj = token
				self._leftexpr = obj
				self._state = 5
			elif isinstance(token, COp):
				self._prefixOps += [token]
			else:
				stateStruct.error("statement parsing: didn't expected token " + str(token))
		elif self._state in (1,2,3): # struct,union,enum
			if self._prefixOps:
				stateStruct.error("statement parsing: prefixes " + str(self._prefixOps) + " not valid for type")
				self._prefixOps = []
			TName = {1:"struct", 2:"union", 3:"enum"}[self._state]
			DictName = TName + "s"
			if isinstance(token, CIdentifier):
				obj = findCObjTypeInNamespace(stateStruct, self.parent, DictName, token.content)
				if obj is None:
					stateStruct.error("statement parsing: " + TName + " '" + token.content + "' unknown")
					obj = CUnknownType(name=token.content)
				self._leftexpr = obj
				self._state = 10
			else:
				stateStruct.error("statement parsing: didn't expected token " + str(token) + " after " + TName)
		elif self._state == 5: # after expr
			while self._prefixOps:
				self._leftexpr = CStatement(parent=self, _op=self._prefixOps[-1], _rightexpr=self._leftexpr)
				self._prefixOps.pop()
			if token == COp("."):
				self._state = 20
				self._leftexpr = CAttribAccessRef(parent=self, base=self._leftexpr)
			elif token == COp("->"):
				self._state = 20
				self._leftexpr = CPtrAccessRef(parent=self, base=self._leftexpr)
			elif isinstance(token, COp):
				self._op = token
				self._state = 6
			elif isinstance(self._leftexpr, CStr) and isinstance(token, CStr):
				self._leftexpr = CStr(self._leftexpr.content + token.content)
			else:
				self._leftexpr = _create_cast_call(stateStruct, self, self._leftexpr, token)
		elif self._state == 6: # after expr + op
			if isinstance(token, CIdentifier):
				obj = findObjInNamespace(stateStruct, self.parent, token.content)
				if obj is None:
					stateStruct.error("statement parsing: identifier '" + token.content + "' unknown")
					obj = CUnknownType(name=token.content)
			elif isinstance(token, (CNumber,CStr,CChar)):
				obj = token
			else:
				obj = CStatement(parent=self)
				obj._cpre3_handle_token(stateStruct, token) # maybe a postfix op or whatever
			self._rightexpr = obj
			self._state = 7
		elif self._state == 7: # after expr + op + expr
			if token == COp("."):
				self._state = 22
				self._rightexpr = CAttribAccessRef(parent=self, base=self._rightexpr)
			elif token == COp("->"):
				self._state = 22
				self._rightexpr = CPtrAccessRef(parent=self, base=self._rightexpr)
			elif isinstance(token, COp):
				if self._op == COp("?") and token == COp(":"):
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
					self._rightexpr = CStatement(parent=self, _leftexpr=self._rightexpr)
					self._rightexpr._op = token
					self._state = 8
			elif isinstance(self._rightexpr, CStr) and isinstance(token, CStr):
				self._rightexpr = CStr(self._rightexpr.content + token.content)
			else:
				self._rightexpr = _create_cast_call(stateStruct, self, self._rightexpr, token)
		elif self._state == 8: # right-to-left chain, pull down
			assert isinstance(self._rightexpr, CStatement)
			self._rightexpr._cpre3_handle_token(stateStruct, token)
			if self._rightexpr._state == 5:
				self._state = 9
		elif self._state == 9: # right-to-left chain after op + expr
			assert isinstance(self._rightexpr, CStatement)
			if token in (COp("."),COp("->")):
				self._rightexpr._cpre3_handle_token(stateStruct, token)
				self._state = 8
			elif not isinstance(token, COp):
				self._rightexpr._cpre3_handle_token(stateStruct, token)
			else: # is COp
				if opsDoLeftToRight(stateStruct, self._op.content, token.content):
					import copy
					subStatement = copy.copy(self)
					self._leftexpr = subStatement
					self._rightexpr = None
					self._op = token
					self._state = 6
				else:
					self._rightexpr._cpre3_handle_token(stateStruct, token)
					self._state = 8
		elif self._state == 20: # after attrib/ptr access
			if isinstance(token, CIdentifier):
				assert isinstance(self._leftexpr, (CAttribAccessRef,CPtrAccessRef))
				self._leftexpr.name = token.content
				self._state = 5
			else:
				stateStruct.error("statement parsing: didn't expected token " + str(token) + " after " + str(self._leftexpr))
		else:
			stateStruct.error("internal error: statement parsing: token " + str(token) + " in invalid state " + str(self._state))
	def _cpre3_parse_brackets(self, stateStruct, openingBracketToken, input_iter):
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
			funcCall.base = ref
			funcCall._bracketlevel = list(openingBracketToken.brackets)
			self._leftexpr = funcCall
			cpre3_parse_statements_in_brackets(stateStruct, funcCall, COp(","), funcCall.args, input_iter)
			funcCall.finalize(stateStruct)
			return

		if self._state in (8,9): # right-to-left chain
			self._rightexpr._cpre3_parse_brackets(stateStruct, openingBracketToken, input_iter)
			if self._rightexpr._state == 5:
				self._state = 9
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
			if openingBracketToken.content != "(":
				stateStruct.error("cpre3 statement parse brackets: didn't expected opening bracket '" + openingBracketToken.content + "' in state 0")
			self._state = 5
		elif self._state == 6: # expr + op
			self._rightexpr = subStatement
			if openingBracketToken.content != "(":
				stateStruct.error("cpre3 statement parse brackets: didn't expected opening bracket '" + openingBracketToken.content + "' in state 6")
			self._state = 7
		else:
			stateStruct.error("cpre3 statement parse brackets: didn't expected opening bracket '" + openingBracketToken.content + "' in state " + str(self._state))
			
		for token in input_iter:
			if isinstance(token, COpeningBracket):
				subStatement._cpre3_parse_brackets(stateStruct, token, input_iter)
			elif isinstance(token, CClosingBracket):
				if token.brackets == openingBracketToken.brackets:
					subStatement.finalize(stateStruct, addToContent=False)
					self._tokens += [subStatement]
					return
				else:
					stateStruct.error("cpre3 statement parse brackets: internal error, closing brackets " + str(token.brackets) + " not expected")
			else:
				subStatement._cpre3_handle_token(stateStruct, token)
		stateStruct.error("cpre3 statement parse brackets: incomplete, missing closing bracket '" + openingBracketToken.content + "' at level " + str(openingBracketToken.brackets))
		
	def getConstValue(self, stateStruct):
		if self._leftexpr is None: # prefixed only
			func = OpPrefixFuncs[self._op.content]
			v = getConstValue(stateStruct, self._rightexpr)
			if v is None: return None
			return func(v)
		if self._op is None or self._rightexpr is None:
			return getConstValue(stateStruct, self._leftexpr)
		v1 = getConstValue(stateStruct, self._leftexpr)
		if v1 is None: return None
		v2 = getConstValue(stateStruct, self._rightexpr)
		if v2 is None: return None
		func = OpBinFuncs[self._op.content]
		if self._op == COp("?:"):
			v15 = getConstValue(stateStruct, self._middleexpr)
			if v15 is None: return None
			return func(v1, v15, v2)
		return func(v1, v2)
			
# only real difference is that this is inside of '[]'
class CArrayStatement(CStatement): pass
	
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
	CFuncPointerDecl.overtake(curCObj)
	bracketLevel = list(curCObj._bracketlevel)
	state = 0
	for token in input_iter:
		if isinstance(token, CClosingBracket):
			if token.brackets == bracketLevel:
				return
			if not _isBracketLevelOk(bracketlevel, token.brackets):
				stateStruct.error("cpre3 parse func pointer name: internal error: bracket level messed up with closing bracket: " + str(token.brackets))

		if state == 0:
			if token == COp("*"):
				state = 1
			else:
				stateStruct.error("cpre3 parse func pointer name: token " + str(token) + " not expected; expected '*'")
		elif state == 1:
			if isinstance(token, CIdentifier):
				curCObj.name = token.content
				state = 2
			else:
				stateStruct.error("cpre3 parse func pointer name: token " + str(token) + " not expected; expected identifier")
		elif state == 2:
			if token == COpeningBracket("["):
				curCObj._bracketlevel = list(token.brackets)
				cpre3_parse_arrayargs(stateStruct, curCObj, input_iter)
				curCObj._bracketlevel = bracketLevel
			else:
				state = 3

		if state == 3:
			stateStruct.error("cpre3 parse func pointer name: token " + str(token) + " not expected; expected ')'")

	stateStruct.error("cpre3 parse func pointer name: incomplete, missing ')' on level " + str(curCObj._bracketlevel))	

def cpre3_parse_enum(stateStruct, parentCObj, input_iter):
	parentCObj.body = CBody(parent=parentCObj.parent.body)
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
	stateStruct.error("cpre3 parse: incomplete, missing closing bracket on level " + str(curCObj._bracketlevel))
	
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
	# TODO
	for token in input_iter:
		if isinstance(token, CClosingBracket):
			if token.brackets == curCObj._bracketlevel:
				return
			if not _isBracketLevelOk(curCObj._bracketlevel, token.brackets):
				stateStruct.error("cpre3 parse array args: internal error: bracket level messed up with closing bracket: " + str(token.brackets))
	stateStruct.error("cpre3 parse array args: incomplete, missing ']' on level " + str(curCObj._bracketlevel))

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
class CGotoLabel(_CBaseWithOptBody): pass

class _CControlStructure(_CBaseWithOptBody):
	NameIsRelevant = False
	StrOutAttribList = [
		("args", bool, None, str),
		("body", None, None, lambda x: "<...>"),
		("defPos", None, "@", str),
	]
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
			last = self.parent.body.contentlist[-1]
			if isinstance(last, CDoStatement):
				if self.body is not None:
					stateStruct.error("'while' " + str(self) + " as part of 'do' " + str(last) + " has another body")
				last.whilePart = self
				addToContent = False

		_CControlStructure.finalize(self, stateStruct, addToContent)			
class CContinueStatement(_CControlStructure):
	Keyword = "continue"
class CBreakStatement(_CControlStructure):
	Keyword = "break"
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
class CGotoStatement(_CControlStructure):
	Keyword = "goto"
class CReturnStatement(_CControlStructure):
	Keyword = "return"

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
			elif token.content == "{":
				CCodeBlock.overtake(curCObj)
				cpre3_parse_body(stateStruct, curCObj, input_iter)
			elif not curCObj.isDerived():
				CStatement.overtake(curCObj)
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
			curCObj.finalize(stateStruct, addToContent=False)
			addToList.append(curCObj)
			curCObj = _CBaseWithOptBody(parent=parentCObj)
		elif isinstance(token, CSemicolon): # if the sepToken is not the semicolon, we don't expect it at all
			stateStruct.error("cpre3 parse statements in brackets: ';' not expected, separator should be " + str(sepToken))
		elif isinstance(curCObj, CVarDecl) and token == COp("="):
			curCObj.body = CStatement(parent=curCObj)
		else:
			if not curCObj.isDerived():
				CStatement.overtake(curCObj)
			if isinstance(curCObj, CStatement):
				curCObj._cpre3_handle_token(stateStruct, token)
			elif isinstance(curCObj.body, CStatement):
				curCObj.body._cpre3_handle_token(stateStruct, token)
			else:
				stateStruct.error("cpre3 parse statements in brackets: " + str(token) + " not expected after " + str(curCObj))
			
	# add also the last object
	if curCObj:
		curCObj.finalize(stateStruct, addToContent=False)
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
					parentCObj.body = curCObj
					return lasttoken
				elif token.content == "[":
					stateStruct.error("cpre3 parse single after " + str(curCObj) + ": got unexpected '['")
					cpre3_parse_skipbracketcontent(stateStruct, list(token.brackets), input_iter)
					return
				elif token.content == "{":
					if curCObj.body is not None:
						stateStruct.error("cpre3 parse single after " + str(curCObj) + ": got multiple bodies")
					cpre3_parse_body(stateStruct, curCObj, input_iter)
					curCObj.finalize(stateStruct)
					parentCObj.body = curCObj
					return
				else:
					stateStruct.error("cpre3 parse single after " + str(curCObj) + ": got unexpected/unknown opening bracket '" + token.content + "'")
					cpre3_parse_skipbracketcontent(stateStruct, list(token.brackets), input_iter)
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
				parentCObj.body = curCObj
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
				parentCObj.body = curCObj
				return lasttoken
			elif isinstance(curCObj, CReturnStatement):
				curCObj.body = CStatement(parent=curCObj)
		elif isinstance(curCObj, CGotoStatement):
			if curCObj.name is None:
				curCObj.name = token.content
			else:
				stateStruct.error("cpre3 parse single after " + str(curCObj) + ": got second identifier '" + token.content + "'")
		elif isinstance(curCObj, CStatement):
			curCObj._cpre3_handle_token(stateStruct, token)
		elif curCObj is not None and isinstance(curCObj.body, CStatement):
			curCObj.body._cpre3_handle_token(stateStruct, token)
		elif isinstance(curCObj, _CControlStructure):
			stateStruct.error("cpre3 parse after " + str(curCObj) + ": didn't expected identifier '" + token.content + "'")
		else:
			if curCObj is None:
				curCObj = CStatement(parent=parentCObj)
				curCObj._cpre3_handle_token(stateStruct, token)
			else:
				stateStruct.error("cpre3 parse single: got unexpected token " + str(token))
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

		try: token = input_iter.next()
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
					DictName = None
					if isinstance(curCObj, CStruct): DictName = "structs"
					elif isinstance(curCObj, CUnion): DictName = "unions"
					elif isinstance(curCObj, CEnum): DictName = "enums"
					if DictName is not None:
						typeObj = findCObjTypeInNamespace(stateStruct, parentCObj, DictName, curCObj.name)
						if typeObj is not None:
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
			elif isinstance(curCObj.body, CStatement) and token.content != ",":
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
					oldObj.finalize(stateStruct)
					if hasattr(curCObj, "bitsize"): delattr(curCObj, "bitsize")
					curCObj.name = None
					curCObj.body = None
				elif token.content == ":" and curCObj and curCObj._type_tokens and curCObj.name:
					CVarDecl.overtake(curCObj)
					curCObj.bitsize = None
				elif token.content == ":" and len(curCObj._type_tokens) == 1 and isinstance(curCObj._type_tokens[0], (str,unicode)) and not curCObj.isDerived():
					CGotoLabel.overtake(curCObj)
					curCObj.name = curCObj._type_tokens[0]
					curCObj._type_tokens[:] = []
					curCObj.finalize(stateStruct)
					curCObj = _CBaseWithOptBody(parent=parentCObj)					
				elif token.content == "=" and curCObj and (isinstance(curCObj, CVarDecl) or not curCObj.isDerived()):
					if not curCObj.isDerived():
						CVarDecl.overtake(curCObj)
					curCObj.body = CStatement(parent=curCObj)
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
					curCObj._bracketlevel = list(parentCObj._bracketlevel)
					lasttoken = cpre3_parse_single_next_statement(stateStruct, curCObj, input_iter)
					curCObj.finalize(stateStruct)
					if isinstance(lasttoken, CClosingBracket) and lasttoken.brackets == parentCObj._bracketlevel:
						return
					curCObj = _CBaseWithOptBody(parent=parentCObj)
				elif token.content == "[":
					stateStruct.error("cpre3 parse after " + str(curCObj) + ": got unexpected '['")
					cpre3_parse_skipbracketcontent(stateStruct, list(token.brackets), input_iter)
				elif token.content == "{":
					if curCObj.body is not None:
						stateStruct.error("cpre3 parse after " + str(curCObj) + ": got multiple bodies")
					cpre3_parse_body(stateStruct, curCObj, input_iter)
					curCObj.finalize(stateStruct)
					curCObj = _CBaseWithOptBody(parent=parentCObj)
				else:
					stateStruct.error("cpre3 parse after " + str(curCObj) + ": got unexpected/unknown opening bracket '" + token.content + "'")
					cpre3_parse_skipbracketcontent(stateStruct, list(token.brackets), input_iter)					
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

def parse(filename, state = None):
	if state is None:
		state = State()
		state.autoSetupSystemMacros()

	preprocessed = state.preprocess_file(filename, local=True)
	tokens = cpre2_parse(state, preprocessed)
	cpre3_parse(state, tokens)
	
	return state
	
def test(*args):
	import better_exchook
	better_exchook.install()
	
	state = State()
	state.autoSetupSystemMacros()

	filename = args[0] if args else "/Library/Frameworks/SDL.framework/Headers/SDL.h"
	preprocessed = state.preprocess_file(filename, local=True)
	tokens = cpre2_parse(state, preprocessed)
	
	token_list = []
	def copy_hook(input, output):
		for x in input:
			output.append(x)
			yield x
	tokens = copy_hook(tokens, token_list)
	
	cpre3_parse(state, tokens)
	
	return state, token_list

if __name__ == '__main__':
	import sys
	test(*sys.argv[1:])
