
import ctypes

SpaceChars = " \t"
LowercaseLetterChars = "abcdefghijklmnopqrstuvwxyz"
LetterChars = LowercaseLetterChars + LowercaseLetterChars.upper()
NumberChars = "0123456789"
OpChars = "&|=!+-*/%<>^~?:,."
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
		self.func = parse_macro_def_rightside(state, self.args, self.rightside)
		self.defPos = state.curPosAsStr() if state else "<unknown>"
	def __str__(self):
		return "(" + ", ".join(self.args) + ") -> " + self.rightside
	def __repr__(self):
		return "<Macro: " + str(self) + ">"
	def __call__(self, *args):
		if len(args) != len(self.args): raise TypeError, "invalid number of args in " + str(self)
		return self.func(*args)

class State:
	EmptyMacro = Macro(None, None, (), "")
	CBuiltinTypes = {
		("void",): None,
		("char",): ctypes.c_char,
		("unsigned","char"): ctypes.c_ubyte,
		("short",): ctypes.c_short,
		("unsigned", "short"): ctypes.c_ushort,
		("int",): ctypes.c_int,
		("unsigned", "int"): ctypes.c_uint,
		("unsigned",): ctypes.c_uint,
		("long",): ctypes.c_long,
		("unsigned", "long"): ctypes.c_ulong,
		("long","long"): ctypes.c_longlong,
		("unsigned","long","long"): ctypes.c_ulonglong,
		("float",): ctypes.c_float,
		("double",): ctypes.c_double,
		("long","double"): ctypes.c_longdouble,
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
		"size_t": ctypes.c_size_t
	}
	Attribs = [
		"extern",
		"static",
		"__inline__",
	]
	
	def __init__(self):
		self.macros = {} # name -> Macro
		self.typedefs = {} # name -> type
		self.structs = {} # name -> CStruct
		self.funcs = {} # name -> CFunc
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
		if filename == "inttypes.h": return "" # we define those types as builtin-types
		elif filename == "stdint.h": return ""
		else:
			self.error("no handler for global include-file '" + filename + "'")
			return ""

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
			fullfilename = None
			reader = self.readGlobalInclude(filename)

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
				elif c == "(": state = 10
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
					stateStruct.error("preprocessor eval: '" + c + "' not expected")
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
							resolved = macro(args)
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
					laststr = c
					state = 40
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
						if len(macroargs) == 0: macroargs = ["",""]
						else: macroargs += [""]
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
					resolved = stateStruct.macros[macroname](*macroargs)
					for t in cpre2_parse(stateStruct, resolved, brackets):
						yield t
				except Exception, e:
					stateStruct.error("cpre2 parse unfold macro " + macroname + " error: " + str(e))
				state = 0
				breakLoop = False
			elif state == 40: # op
				if c in OpChars:
					if c == "*": # this always separates
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


# either some basic type, another typedef or some complex like CStruct/CUnion/...
class CType:
	def __repr__(self):
		return str(self.__dict__)

class _CBaseWithOptBody:
	def __init__(self, **kwargs):
		self._type_tokens = []
		self._id_tokens = []
		self._bracketlevel = []
		self.type = None
		self.attribs = []
		self.name = None
		self.args = []
		self.arrayargs = []
		self.body = None
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
		name = self.name if self.name else str(self._id_tokens)
		return \
			self.__class__.__name__ + " " + \
			str(self.attribs) + " " + \
			str(self._type_tokens) + " " + \
			name + " " + str(self.body)

	def __nonzero__(self):
		return \
			bool(self._type_tokens) or \
			bool(self._id_tokens) or \
			bool(self.type) or \
			bool(self.name) or \
			bool(self.args) or \
			bool(self.arrayargs) or \
			bool(self.body)
	
	def make_type_from_typetokens(self, stateStruct):
		if tuple(self._type_tokens) in stateStruct.CBuiltinTypes:
			self.type = CType()
			self.type.builtinType = stateStruct.CBuiltinTypes[tuple(self._type_tokens)]
		elif len(self._type_tokens) == 1 and self._type_tokens[0] in stateStruct.StdIntTypes:
			self.type = CType()
			self.type.stdIntType = self._type_tokens[0]
		elif len(self._type_tokens) == 1 and self._type_tokens[0] in stateStruct.typedefs:
			self.type = CType()
			self.type.typedef = self._type_tokens[0]
		else:
			# TODO
			stateStruct.error("make_type_from_typetokens currently not supported for " + str(self._type_tokens))
	
	def finalize(self, stateStruct):
		print "finalize", self, "at", stateStruct.curPosAsStr()
	
	def copy(self):
		import copy
		return copy.deepcopy(self, memo={id(self.parent): self.parent})

	
class CTypedef(_CBaseWithOptBody):
	def finalize(self, stateStruct):
		if self.type is None:
			stateStruct.error("finalize typedef: type is unknown")
			return
		if self.name is None:
			stateStruct.error("finalize typedef: name is unset")
			return
		stateStruct.typedefs[self.name] = self.type

class CVarDecl(_CBaseWithOptBody): pass
class CStruct(_CBaseWithOptBody): pass
class CUnion(_CBaseWithOptBody): pass
class CEnum(_CBaseWithOptBody): pass
class CFunc(_CBaseWithOptBody): pass

def cpre3_parse_struct(stateStruct, curCObj, input_iter):
	# TODO
	for token in input_iter:
		if isinstance(token, CClosingBracket):
			if token.brackets == curCObj._bracketlevel:
				curCObj.finalize(stateStruct)
				return
	stateStruct.error("cpre3 parse struct: incomplete, missing '}'")

def cpre3_parse_union(stateStruct, curCObj, input_iter):
	# TODO
	for token in input_iter:
		if isinstance(token, CClosingBracket):
			if token.brackets == curCObj._bracketlevel:
				curCObj.finalize(stateStruct)
				return
	stateStruct.error("cpre3 parse union: incomplete, missing '}'")

def cpre3_parse_enum(stateStruct, curCObj, input_iter):
	# TODO
	for token in input_iter:
		if isinstance(token, CClosingBracket):
			if token.brackets == curCObj._bracketlevel:
				curCObj.finalize(stateStruct)
				return
	stateStruct.error("cpre3 parse enum: incomplete, missing '}'")

def cpre3_parse_funcargs(stateStruct, curCObj, input_iter):
	# TODO
	for token in input_iter:
		if isinstance(token, CClosingBracket):
			if token.brackets == curCObj._bracketlevel:
				curCObj.finalize(stateStruct)
				return
	stateStruct.error("cpre3 parse func args: incomplete, missing ')'")

def cpre3_parse_funcbody(stateStruct, curCObj, input_iter):
	# TODO
	for token in input_iter:
		if isinstance(token, CClosingBracket):
			if token.brackets == curCObj._bracketlevel:
				curCObj.finalize(stateStruct)
				return
	stateStruct.error("cpre3 parse func body: incomplete, missing '}'")

def cpre3_parse_arrayargs(stateStruct, curCObj, input_iter):
	# TODO
	for token in input_iter:
		if isinstance(token, CClosingBracket):
			if token.brackets == curCObj._bracketlevel:
				curCObj.finalize(stateStruct)
				return
	stateStruct.error("cpre3 parse array args: incomplete, missing ']'")

def cpre3_parse_typedef(stateStruct, curCObj, input_iter):
	typeIsComplete = False
	state = 0
	for token in input_iter:
		if state == 0:
			if isinstance(token, CIdentifier):
				if token.content == "typedef":
					stateStruct.error("cpre3 parse typedef: typedef not expected twice")
				elif token.content in stateStruct.Attribs:
					curCObj.attribs += [token.content]
				elif token.content == "struct":
					curCObj.type = CStruct()
				elif token.content == "union":
					curCObj.type = CUnion()
				elif token.content == "enum":
					curCObj.type = CEnum()
				elif (token.content,) in stateStruct.CBuiltinTypes:
					curCObj._type_tokens += [token.content]
				elif token.content in stateStruct.StdIntTypes:
					curCObj._type_tokens += [token.content]
				elif token.content in stateStruct.typedefs:
					curCObj._type_tokens += [token.content]
				else:
					if curCObj._type_tokens and curCObj.type is None:
						curCObj.make_type_from_typetokens(stateStruct)
						typeIsComplete = True
					if not typeIsComplete and isinstance(curCObj.type, (CStruct,CUnion,CEnum)) and curCObj.type.name is None:
						curCObj.type.name = token.content
					elif curCObj.type is not None:
						if curCObj.name is None:
							curCObj.name = token.content
						else:
							stateStruct.error("cpre3 parse in typedef: got second identifier " + token.content + " after name " + curCObj.name)
					else:
						stateStruct.error("cpre3 parse in typedef: got unexpected identifier " + token.content)
			if isinstance(token, COpeningBracket):
				curCObj._bracketlevel = list(token.brackets)
				if token.content == "{":
					if isinstance(curCObj.type, CStruct):
						cpre3_parse_struct(stateStruct, curCObj.type, input_iter)
						typeIsComplete = True
					elif isinstance(curCObj.type, CUnion):
						cpre3_parse_union(stateStruct, curCObj.type, input_iter)
						typeIsComplete = True
					elif isinstance(curCObj.type, CEnum):
						cpre3_parse_enum(stateStruct, curCObj.type, input_iter)
						typeIsComplete = True
					else:
						stateStruct.error("cpre3 parse in typedef: got unexpected '{' after type " + str(curCObj.type))
						state = 11
				else:
					state = 11
			elif isinstance(token, CSemicolon):
				state = 0
				curCObj.finalize(stateStruct)
				return
		elif state == 11: # bracket
			# TODO ...
			if isinstance(token, CClosingBracket):
				if token.brackets == curCObj._bracketlevel:
					state = 0
		else:
			stateStruct.error("cpre3 parse typedef: internal error. unexpected state " + str(state))
	stateStruct.error("cpre3 parse typedef: incomplete, missing ';'")

def cpre3_parse(stateStruct, input):
	state = 0
	curCObj = _CBaseWithOptBody()
	parent = None
	
	input_iter = iter(input)
	for token in input_iter:
		if isinstance(token, CIdentifier):
			if token.content == "typedef":
				CTypedef.overtake(curCObj)
				cpre3_parse_typedef(stateStruct, curCObj, input_iter)
				curCObj = _CBaseWithOptBody(parent=parent)							
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
				curCObj._id_tokens += [token.content]
		elif isinstance(token, COp):
			if token.content == "*":
				CVarDecl.overtake(curCObj)
				curCObj._type_tokens += [token.content]
			elif token.content == ",":
				CVarDecl.overtake(curCObj)
				curCObj.finalize(stateStruct)
				curCObj = curCObj.copy()
			else:
				stateStruct.error("cpre3 parse: op '" + token.content + "' not expected in base state")
		elif isinstance(token, COpeningBracket):
			curCObj._bracketlevel = list(token.brackets)
			if token.content == "(":
				CFunc.overtake(curCObj)
				cpre3_parse_funcargs(stateStruct, curCObj, input_iter)
			elif token.content == "[":
				CVarDecl.overtake(curCObj)
				cpre3_parse_arrayarg(stateStruct, curCObj, input_iter)
			elif token.content == "{":
				parent = curCObj
				if curCObj.isDerived():
					curCObj.body = []
					if isinstance(curCObj, CStruct):
						cpre3_parse_struct(stateStruct, curCObj, input_iter)
					elif isinstance(curCObj, CUnion):
						cpre3_parse_union(stateStruct, curCObj, input_iter)
					elif isinstance(curCObj, CEnum):
						cpre3_parse_enum(stateStruct, curCObj, input_iter)
					elif isinstance(curCObj, CFunc):
						cpre3_parse_funcbody(stateStruct, curCObj, input_iter)
					else:
						stateStruct.error("cpre3 parse: unexpected '{' after " + str(curCObj))
					curCObj = _CBaseWithOptBody(parent=parent)							
			else:
				stateStruct.error("cpre3 parse: unexpected opening bracket '" + token.content + "'")
		elif isinstance(token, CClosingBracket):
			if token.content == "}":
				if parent is None:
					stateStruct.error("cpre3 parse: runaway '}'")
				else:
					parent = parent.parent
					curCObj.finalize(stateStruct)
					curCObj = _CBaseWithOptBody(parent=parent)
			else:
				stateStruct.error("cpre3 parse: unexpected closing bracket '" + token.content + "'")
		elif isinstance(token, CSemicolon):
			if not curCObj.isDerived() and curCObj:
				CVarDecl.overtake(curCObj)
			curCObj.finalize(stateStruct)
			curCObj = _CBaseWithOptBody(parent=parent)
		else:
			stateStruct.error("cpre3 parse: unexpected token " + str(token))

			
def test():
	import better_exchook
	better_exchook.install()
	
	state = State()
	state.autoSetupSystemMacros()

	preprocessed = state.preprocess_file("/Library/Frameworks/SDL.framework/Headers/SDL.h", local=True)
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
	test()
