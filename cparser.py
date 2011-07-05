
import ctypes, _ctypes

SpaceChars = " \t"
LowercaseLetterChars = "abcdefghijklmnopqrstuvwxyz"
LetterChars = LowercaseLetterChars + LowercaseLetterChars.upper()
NumberChars = "0123456789"
OpChars = "&|=!+-*/%<>^~?:,."
LongOps = map(lambda c: c+"=", "&|=+-*/%<>^~") + ["--","++","->"]
OpeningBrackets = "[({"
ClosingBrackets = "})]"

def simple_escape_char(c):
	if c == "n": return "\n"
	elif c == "t": return "\t"
	else: return c

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
				ret += c
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
	def getConstValue(self, stateStruct):
		assert len(self.args) == 0
		preprocessed = stateStruct.preprocess(self.rightside, None, repr(self))
		tokens = cpre2_parse(stateStruct, preprocessed)
		
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
		self._errors += [self.curPosAsStr() + ": " + s]

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
	
	def readGlobalInclude(self, filename):
		if filename == "inttypes.h": return "", None # we define those types as builtin-types
		elif filename == "stdint.h": return "", None
		else:
			self.error("no handler for global include-file '" + filename + "'")
			return "", None

	def preprocess_file(self, filename, local):
		if local:
			fullfilename = self.findIncludeFullFilename(filename, local)
			
			try:
				import codecs
				f = codecs.open(fullfilename, "r", "utf-8")
			except Exception, e:
				self.error("cannot open include-file '" + filename + "': " + str(e))
				return
			
			def reader():
				while True:
					c = f.read(1)
					if len(c) == 0: break
					yield c
			reader = reader()
		else:
			reader, fullfilename = self.readGlobalInclude(filename)

		for c in self.preprocess(reader, fullfilename, filename):
			yield c

	def preprocess(self, reader, fullfilename, filename):
		self.incIncludeLineChar(fullfilename=fullfilename, inc=filename)
		for c in cpreprocess_parse(self, reader):
			yield c		
		self._preprocessIncludeLevel = self._preprocessIncludeLevel[:-1]		

	def getCWrapper(self, clib):
		class CWrapper(object):
			stateStruct = self
			dll = clib
			def __getattribute__(self, attrib):
				if attrib in ("_cache","__dict__","__class__"):
					return object.__getattribute__(self, attrib)
				if not "_cache" in self.__dict__: self._cache = {}
				cache = self._cache
				if attrib in cache: return cache[attrib]
				stateStruct = self.__class__.stateStruct
				if attrib in stateStruct.macros and len(stateStruct.macros[attrib].args) == 0:
					t = stateStruct.macros[attrib].getConstValue(stateStruct)
				elif attrib in stateStruct.typedefs:
					t = stateStruct.typedefs[attrib].getCType(stateStruct)
				elif attrib in stateStruct.enumconsts:
					t = stateStruct.enumconsts[attrib].value
				elif attrib in stateStruct.funcs:
					t = stateStruct.funcs[attrib].getCType(stateStruct)((attrib, clib))
				else:
					raise AttributeError, attrib + " not found in " + str(stateStruct)
				cache[attrib] = t
				return t
		def iterAllAttribs():
			for attrib in self.macros:
				if len(self.macros[attrib].args) > 0: continue
				yield attrib
			for attrib in self.typedefs:
				yield attrib
			for attrib in self.enumconsts:
				yield attrib
			for attrib in self.funcs:
				yield attrib
		for attrib in iterAllAttribs():
			if not hasattr(CWrapper, attrib):
				setattr(CWrapper, attrib, None)
		wrapper = CWrapper()
		return wrapper

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
	for c in condstr:
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
					stateStruct.error("preprocessor eval: '" + c + "' not expected after '" + laststr + "'")
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
							stateStruct.error("preprocessor eval: expected op but got '" + c + "' in " + condstr)
							return
					else:
						if opstr == "!=": op = lambda x,y: x != y
						elif opstr == "==": op = lambda x,y: x == y
						elif opstr == "<=": op = lambda x,y: x <= y
						elif opstr == ">=": op = lambda x,y: x >= y
						elif opstr == "<": op = lambda x,y: x < y
						elif opstr == ">": op = lambda x,y: x > y
						elif opstr == "&&":
							op = lambda x,y: x and y
							# short path check
							if not lasteval: return lasteval
						elif opstr == "||":
							op = lambda x,y: x or y
							# short path check
							if lasteval: return lasteval
						elif opstr == "!":
							newprefixop = lambda x: not x
							if prefixOp: prefixOp = lambda x: prefixOp(newprefixop(x))
							else: prefixOp = newprefixop
						else:
							stateStruct.error("invalid op '" + opstr + "' with '" + c + "' following")
							return
						opstr = ""
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
		state.error("preprocessor: macro " + arg + " is not defined")
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
				elif c == "\\": state = 5 # escape next
				elif c == "\n":
					for c in handle_cpreprocess_cmd(stateStruct, cmd, arg): yield c
					state = 0
				else:
					if arg is None: cmd += c
					else: arg += c
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
	def __init__(self, data=None, rawstr=None, **kwargs):
		self.content = data
		self.rawstr = rawstr
		for k,v in kwargs.iteritems():
			setattr(self, k, v)
	def __repr__(self):
		if self.content is None: return "<" + self.__class__.__name__ + ">"
		return "<" + self.__class__.__name__ + " " + str(self.content) + ">"
	def __eq__(self, other):
		return self.__class__ is other.__class__ and self.content == other.content
	def asCCode(self): return self.content

class CStr(_CBase):
	def asCCode(self): return '"' + escape_cstr(self.content) + '"'
class CChar(_CBase):
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
				if c in SpaceChars + "\n": pass
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
	def __init__(self, **kwargs):
		self._type_tokens = []
		self._bracketlevel = None
		self._finalized = False
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
		name = ("'" + self.name + "'") if self.name else "<noname>"
		t = self.type or self._type_tokens
		l = []
		if self.attribs: l += [("attribs", self.attribs)]
		if t: l += [("type", t)]
		if self.args: l += [("args", self.args)]
		if self.arrayargs: l += [("arrayargs", self.arrayargs)]
		if self.body is not None: l += [("body", self.body)]
		if self.value is not None: l += [("value", self.value)]
		return \
			self.__class__.__name__ + " " + \
			name + " " + \
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
	
	def finalize(self, stateStruct, addToContent = True):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return
		self._finalized = True
		if not self: return
		
		#print "finalize", self, "at", stateStruct.curPosAsStr()
		if addToContent and self.parent.body: self.parent.body.contentlist += [self]
	
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
	def finalize(self, stateStruct):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return
		
		self.type = make_type_from_typetokens(stateStruct, self._type_tokens)
		_CBaseWithOptBody.finalize(self, stateStruct)
		
		if self.type is None:
			stateStruct.error("finalize " + str(self) + ": type is unknown")
		# Name can be unset. It depends where this is declared.
	def getCType(self, stateStruct):
		restype = getCType(self.type, stateStruct)
		argtypes = map(lambda a: getCType(a, stateStruct), self.args)
		return ctypes.CFUNCTYPE(restype, *argtypes)
		
def _finalizeBasicType(obj, stateStruct, dictName=None, listName=None):
	if obj._finalized:
		stateStruct.error("internal error: " + str(obj) + " finalized twice")
		return
	
	obj.type = make_type_from_typetokens(stateStruct, obj._type_tokens)
	_CBaseWithOptBody.finalize(obj, stateStruct, addToContent = obj.name is not None)
	
	if hasattr(obj.parent, "body"):
		d = getattr(obj.parent.body, dictName or listName)
		if dictName:
			if obj.name is None:
				# might be part of a typedef, so don't error
				return
	
			if obj.name in d:
				stateStruct.error("finalize " + obj.__class__.__name__ + " " + str(obj) + ": a previous equally named (" + obj.name + ") declaration exists")
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
	finalize = lambda *args: _finalizeBasicType(*args, dictName="structs")
	def getCType(self, stateStruct):
		return _getCTypeStruct(ctypes.Structure, self, stateStruct)

class CUnion(_CBaseWithOptBody):
	finalize = lambda *args: _finalizeBasicType(*args, dictName="unions")
	def getCType(self, stateStruct):
		return _getCTypeStruct(ctypes.Union, self, stateStruct)

class CEnum(_CBaseWithOptBody):
	finalize = lambda *args: _finalizeBasicType(*args, dictName="enums")
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
	def finalize(self, stateStruct):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return

		if self.value is None:
			if self.parent.body.contentlist:
				last = self.parent.body.contentlist[-1]
				self.value = last.value + 1
			else:
				self.value = 0

		_CBaseWithOptBody.finalize(self, stateStruct)

		if self.name:
			# self.parent.parent is the parent of the enum
			self.parent.parent.body.enumconsts[self.name] = self
		
class CFuncArgDecl(_CBaseWithOptBody):
	def finalize(self, stateStruct):
		if self._finalized:
			stateStruct.error("internal error: " + str(self) + " finalized twice")
			return
		
		self.type = make_type_from_typetokens(stateStruct, self._type_tokens)
		_CBaseWithOptBody.finalize(self, stateStruct, addToContent = False)
		
		if self.type != CBuiltinType(CVoidType()):
			self.parent.args += [self]
	def getCType(self, stateStruct):
		return getCType(self.type, stateStruct)

class CStatement(_CBaseWithOptBody):
	def __str__(self):
		return "CStatement " + (str(self._tokens) if hasattr(self, "_tokens") else "()")
	def _cpre3_handle_token(self, stateStruct, token):
		# TODO ...
		if not hasattr(self, "_tokens"): self._tokens = []
		self._tokens += [token]
	def _cpre3_parse_brackets(self, stateStruct, openingBracketToken, input_iter):
		subStatement = CStatement(parent=self.parent)
		for token in input_iter:
			if isinstance(token, COpeningBracket):
				subStatement._cpre3_parse_brackets(stateStruct, token, input_iter)
			elif isinstance(token, CClosingBracket):
				if token.brackets == openingBracketToken.brackets:
					subStatement.finalize(stateStruct)
					if not hasattr(self, "_tokens"): self._tokens = []
					self._tokens += [subStatement]
					return
				else:
					stateStruct.error("cpre3 statement parse brackets: internal error, closing brackets not expected")
			else:
				subStatement._cpre3_handle_token(stateStruct, token)
		stateStruct.error("cpre3 statement parse brackets: incomplete, missing closing bracket '" + openingBracketToken.content + "' at level " + str(openingBracketToken.brackets))
	
	def _tokensToConstValue(obj, tokens, stateStruct):
		if len(tokens) == 2 and tokens[0] == COp("-"):
			return - obj._tokensToConstValue(tokens[1:], stateStruct)
		if len(tokens) == 1:
			if isinstance(tokens[0], CNumber):
				return tokens[0].content
			if isinstance(tokens[0], CIdentifier):
				name = tokens[0].content
				idobj = findIdentifierInBody(obj.parent.body, name)
				if idobj is None:
					stateStruct.error(str(obj) + " getConstValue: identifier " + name + " unknown in " + str(body))
					return 0 # this is a useful fallback
				return idobj.value # expecting CEnumConst right now
			if isinstance(tokens[0], CStatement):
				return tokens[0].getConstValue(stateStruct)
		if len(tokens) >= 3 and isinstance(tokens[1], COp):
			# warning: expects that first op has always preference. TODO... :P
			value1 = obj._tokensToConstValue([tokens[0]], stateStruct)
			value2 = obj._tokensToConstValue(tokens[2:], stateStruct)
			try:
				if tokens[1] == COp("+"): return value1 + value2
				elif tokens[1] == COp("-"): return value1 - value2
				elif tokens[1] == COp("*"): return value1 * value2
				elif tokens[1] == COp("/"): return value1 / value2
				elif tokens[1] == COp("%"): return value1 % value2
				elif tokens[1] == COp("<<"): return value1 << value2
				elif tokens[1] == COp("|"): return value1 | value2
			except Exception, e:
				stateStruct.error(str(obj) + " getConstValue: cannot handle " + str(value1) + " " + str(tokens[1]) + " " + str(value2))
				return 0
		stateStruct.error(str(obj) + " getConstValue: not completely implemented yet for token list " + str(tokens))
		
	def getConstValue(self, stateStruct):
		return self._tokensToConstValue(self._tokens if hasattr(self, "_tokens") else [], stateStruct)
	
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
		if isinstance(token, CClosingBracket) and token.brackets == bracketLevel:
			return

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
					valueStmnt.finalize(stateStruct)
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
						valueStmnt.finalize(stateStruct)
						curCObj.value = valueStmnt.getConstValue(stateStruct)
					curCObj.finalize(stateStruct)
				parentCObj.finalize(stateStruct)
				return
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
					stateStruct.error("cpre3 parse func args: got unexpected '('")
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
				if typeObj is not None:
					typeObj.finalize(stateStruct)
				curCObj._type_tokens += ["*"]
			elif isinstance(token, COpeningBracket):
				curCObj._bracketlevel = list(token.brackets)
				if token.content == "(":
					if typeObj is None:
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
					typeObj.finalize(stateStruct)
				curCObj.finalize(stateStruct)
				return
			else:
				stateStruct.error("cpre3 parse typedef: got unexpected token " + str(token))
		elif state == 11: # unexpected bracket
			# just ignore everything until we get the closing bracket
			if isinstance(token, CClosingBracket):
				if token.brackets == curCObj._bracketlevel:
					state = 0
		else:
			stateStruct.error("cpre3 parse typedef: internal error. unexpected state " + str(state))
	stateStruct.error("cpre3 parse typedef: incomplete, missing ';'")

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
			elif token.content == "typedef":
				CTypedef.overtake(curCObj)
				cpre3_parse_typedef(stateStruct, curCObj, input_iter)
				curCObj = _CBaseWithOptBody(parent=parentCObj)							
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
					stateStruct.error("cpre3 parse: second identifier name " + token.content + ", first was " + curCObj.name + ", first might be an unknwon type")
					# fallback recovery, guess vardecl with the first identifier being an unknown type
					curCObj._type_tokens += [CUnknownType(name=curCObj.name)]
					curCObj.name = token.content
				
				if len(curCObj._type_tokens) == 0:
					CStatement.overtake(curCObj)
		elif isinstance(token, COp):
			if len(curCObj._type_tokens) == 0:
				CStatement.overtake(curCObj)
			if isinstance(curCObj, CStatement):
				curCObj._cpre3_handle_token(stateStruct, token)
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
				elif token.content == ":":
					if curCObj:
						CVarDecl.overtake(curCObj)
						curCObj.bitsize = None
				else:
					stateStruct.error("cpre3 parse: op '" + token.content + "' not expected in " + str(parentCObj) + " after " + str(curCObj))
		elif isinstance(token, CNumber):
			if isinstance(curCObj, CVarDecl) and hasattr(curCObj, "bitsize"):
				curCObj.bitsize = token.content
			else:
				CStatement.overtake(curCObj)
				curCObj._cpre3_handle_token(stateStruct, token)
		elif isinstance(token, COpeningBracket):
			curCObj._bracketlevel = list(token.brackets)
			if isinstance(curCObj, CStatement):
				if token.content == "{":
					cpre3_parse_body(stateStruct, curCObj, input_iter)
					curCObj.finalize(stateStruct)
					curCObj = _CBaseWithOptBody(parent=parentCObj)
				else:
					curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)
			elif token.content == "(":
				if len(curCObj._type_tokens) == 0:
					CStatement.overtake(curCObj)
					curCObj._cpre3_handle_token(stateStruct, token)
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
					if not parentObj.body is stateStruct: # not top level
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
				stateStruct.error("cpre3 parse: unexpected closing bracket '" + token.content + "'")
			if token.brackets == parentCObj._bracketlevel:
				return
		elif isinstance(token, CSemicolon):
			if not curCObj.isDerived() and curCObj:
				CVarDecl.overtake(curCObj)
			curCObj.finalize(stateStruct)
			curCObj = _CBaseWithOptBody(parent=parentCObj)
		else:
			stateStruct.error("cpre3 parse: unexpected token " + str(token))

	if curCObj and not curCObj._finalized:
		stateStruct.error("cpre3 parse: unfinished " + str(curCObj) + " at end")

	if parentCObj._bracketlevel is not None:
		stateStruct.error("cpre3 parse: read until end without closing brackets " + str(parentCObj._bracketlevel))

def cpre3_parse(stateStruct, input):
	input_iter = iter(input)
	parentObj = _CBaseWithOptBody()
	parentObj.body = stateStruct
	cpre3_parse_body(stateStruct, parentObj, input_iter)

def parse(filename):
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
