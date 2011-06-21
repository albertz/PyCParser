
class State:
	def __init__(self):
		self.macros = {} # name -> func
		self._preprocessIfLevels = []
		self._preprocessIgnoreCurrent = False
		
	def error(self, s): pass	
SpaceChars = " \t"

def handle_cpreprocess_cmd(state, cmd, arg):
	if cmd == "if":
		self._preprocessIfLevels += [0]
	elif cmd == "elif":
		pass
	elif cmd == "else":
		state._preprocessIgnoreCurrent = state._preprocessIfHadTruePart
		
	pass

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
				elif c in SpaceChars + "\n": pass
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
					handle_cpreprocess_cmd(stateStruct, cmd, arg)
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
		
def parse(state, input):
	
	
	state = 0
	
	while True:
		c = s.read(1)
		if len(c) == 0: break
		
		if state == 0:
			
			

