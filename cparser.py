
SpaceChars = " \t"
LowercaseLetterChars = "abcdefghijklmnopqrstuvwxyz"
LetterChars = LowercaseLetterChars + LowercaseLetterChars.upper()
NumberChars = "0123456789"

class State:
	def __init__(self):
		self.macros = {} # name -> func
		self._preprocessIfLevels = []
		self._preprocessIgnoreCurrent = False
		# 0->didnt got true yet, 1->in true part, 2->after true part. and that as a stack
		self._preprocessIncludeLevel = []
		self._errors = []
	
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
				if self._preprocessIncludeLevel:
					import os.path
					dir = os.path.dirname(self._preprocessIncludeLevel[-1][0])
				if not dir: dir = "."
				dir += "/"
		else:
			dir = "./" # foo

		fullfilename = dir + filename
		return fullfilename
		
	def preprocess_file(self, filename, local):
		fullfilename = self.findIncludeFullFilename(filename, local)
		
		try:
			import codecs
			f = codecs.open(fullfilename, "r", "utf-8")
		except Exception, e:
			self.error("cannot open include-file '" + filename + "': " + str(e))
			return
		
		self.incIncludeLineChar(fullfilename=fullfilename, inc=filename)
		def reader():
			while True:
				c = f.read(1)
				if len(c) == 0: break
				yield c
		for c in cpreprocess_parse(self, reader()):
			yield c
		
		self._preprocessIncludeLevel = self._preprocessIncludeLevel[:-1]

def is_valid_defname(defname):
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

def cpreprocess_evaluate_cond(state, condstr):
	# TODO ...
	state.error("preprocessor: if-evaluation not yet implemented; cannot check '" + condstr + "'")
	return True # may be more often what we want :P

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
	print "include", arg
	for c in state.preprocess_file(filename=filename, local=local): yield c

def cpreprocess_handle_def(state, arg):
	# TODO
	pass

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
		if state._preprocessIgnoreCurrent: return # we don't really care
		check = cpreprocess_evaluate_ifdef(state, arg)
		if check: state._preprocessIfLevels[-1] = 1
		
	elif cmd == "ifndef":
		state._preprocessIfLevels += [0]
		if state._preprocessIgnoreCurrent: return # we don't really care
		check = not cpreprocess_evaluate_ifdef(state, arg)
		if check: state._preprocessIfLevels[-1] = 1

	elif cmd == "if":
		state._preprocessIfLevels += [0]
		if state._preprocessIgnoreCurrent: return # we don't really care
		check = cpreprocess_evaluate_cond(state, arg)
		if check: state._preprocessIfLevels[-1] = 1
		
	elif cmd == "elif":
		if state._preprocessIgnoreCurrent: return # we don't really care
		if len(state._preprocessIfLevels) == 0:
			state.error("preprocessor: elif without if")
			return
		if state._preprocessIfLevels[-1] >= 1:
			state._preprocessIfLevels[-1] = 2 # we already had True
			return
		check = cpreprocess_evaluate_cond(state, arg)
		if check: state._preprocessIfLevels[-1] = 1

	elif cmd == "else":
		if state._preprocessIgnoreCurrent: return # we don't really care
		if len(state._preprocessIfLevels) == 0:
			state.error("preprocessor: else without if")
			return
		if state._preprocessIfLevels[-1] >= 1:
			state._preprocessIfLevels[-1] = 2 # we already had True
			return
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
				
	elif cmd == "pragma": pass # ignore at all right now
	else:
		if state._preprocessIgnoreCurrent: return # we don't really care
		state.error("preprocessor command " + cmd + " unknown")
		
	state._preprocessIgnoreCurrent = any(map(lambda x: x != 1, state._preprocessIfLevels))

def cpreprocess_parse(stateStruct, input):
	cmd = ""
	arg = ""
	state = 0
	for c in input:		
		breakLoop = False
		while not breakLoop:
			breakLoop = True

			if state == 0:
				if c == "#":
					cmd = ""
					arg = None
					state = 1
				elif c == "/": state = 20
				else:
					if not stateStruct._preprocessIgnoreCurrent: yield c
			elif state == 1: # start of preprocessor command
				if c in SpaceChars: pass
				elif c == "\n": state = 0
				else:
					cmd = c
					state = 2
			elif state == 2: # in the middle of the command
				if c in SpaceChars: state = 3
				elif c == "(":
					arg = c
					state = 4
				elif c == "\n":
					for c in handle_cpreprocess_cmd(stateStruct, cmd, arg): yield c
					state = 0
				else: cmd += c
			elif state == 3: # command after space
				if c in SpaceChars: pass
				elif c == "(":
					state = 2
					breakLoop = False
				elif c == "\n":
					state = 2
					breakLoop = False
				else:
					arg = c
					state = 4
			elif state == 4: # argument(s) in command
				if c == "\\": state = 5 # escape next
				elif c == "\n":
					state = 2
					breakLoop = False
				else: arg += c
			elif state == 5: # after escape in arg in command
				if c == "\n": state = 4
				elif c in SpaceChars: pass
				else:
					state = 4
					breakLoop = False				
			elif state == 20: # after "/", possible start of comment
				if c == "*": state = 21 # C-style comment
				elif c == "/": state = 25 # C++-style comment
				else:
					state = 0
					if not stateStruct._preprocessIgnoreCurrent: yield "/"
					breakLoop = False
			elif state == 21: # C-style comment
				if c == "*": state = 22
				else: pass
			elif state == 22: # C-style comment after "*"
				if c == "/": state = 0
				elif c == "*": pass
				else: state = 21
			elif state == 25: # C++-style comment
				if c == "\n": state = 0
				else: pass
			else:
				self.error("internal error: invalid state " + str(state))
				state = 0 # reset. it's the best we can do

		if c == "\n": stateStruct.incIncludeLineChar(line=1)
		elif c == "\t": stateStruct.incIncludeLineChar(char=4, charMod=4)
		else: stateStruct.incIncludeLineChar(char=1)

def parse(state, input):
	
	
	state = 0
	
	while True:
		c = s.read(1)
		if len(c) == 0: break
		
		if state == 0:
			
			pass

def test():
	# Test
	import better_exchook
	better_exchook.install()
	
	state = State()
	s = "".join(state.preprocess_file("/Library/Frameworks/SDL.framework/Headers/SDL.h", local=True)).encode("utf-8")

	return state

if __name__ == '__main__':
	test()
