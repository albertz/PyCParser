
import ast


# We could use this funny little hack:
# background: http://stackoverflow.com/questions/6959360/goto-in-python
# code from here: http://code.activestate.com/recipes/576944-the-goto-decorator/
# by Carl Cerecke
# Licensed under the MIT License

class MissingLabelError(Exception):
	"""'goto' without matching 'label'."""
	pass

def goto(fn):
	import dis
	import new

	"""
	A function decorator to add the goto command for a function.

	Specify labels like so:

	label .foo

	Goto labels like so:

	goto .foo
	"""
	labels = {}
	gotos = {}
	globalName = None
	index = 0
	end = len(fn.func_code.co_code)
	i = 0

	# scan through the byte codes to find the labels and gotos
	while i < end:
		op = ord(fn.func_code.co_code[i])
		i += 1
		name = dis.opname[op]

		if op > dis.HAVE_ARGUMENT:
			b1 = ord(fn.func_code.co_code[i])
			b2 = ord(fn.func_code.co_code[i+1])
			num = b2 * 256 + b1

			if name == 'LOAD_GLOBAL':
				globalName = fn.func_code.co_names[num]
				index = i - 1
				i += 2
				continue

			if name == 'LOAD_ATTR':
				if globalName == 'label':
					labels[fn.func_code.co_names[num]] = index
				elif globalName == 'goto':
					gotos[fn.func_code.co_names[num]] = index

			name = None
			i += 2

	# no-op the labels
	ilist = list(fn.func_code.co_code)
	for label,index in labels.items():
		ilist[index:index+7] = [chr(dis.opmap['NOP'])]*7

	# change gotos to jumps
	for label,index in gotos.items():
		if label not in labels:
			raise MissingLabelError("Missing label: %s"%label)

		target = labels[label] + 7   # skip NOPs
		ilist[index] = chr(dis.opmap['JUMP_ABSOLUTE'])
		ilist[index + 1] = chr(target & 255)
		ilist[index + 2] = chr(target >> 8)

	# create new function from existing function
	c = fn.func_code
	newcode = new.code(c.co_argcount,
					   c.co_nlocals,
					   c.co_stacksize,
					   c.co_flags,
					   ''.join(ilist),
					   c.co_consts,
					   c.co_names,
					   c.co_varnames,
					   c.co_filename,
					   c.co_name,
					   c.co_firstlineno,
					   c.co_lnotab)
	newfn = new.function(newcode,fn.func_globals)
	return newfn


# Or, to avoid messing around with the bytecode, we can go the
# much more complicated route:
# - First, we flatten any Python AST into a series of statements,
#   with even more goto's added for while/for loops, if's, etc.
#   (We can avoid doing this for all sub-ASTs where there are no
#    no goto-labels. The goal is to have all goto-labels at
#    the top-level, not inside a sub-AST.)
# - Only conditional goto's can stay.
# - All Gotos and Goto-labels are marked somehow as special elements.
# So, we end up with sth like:
#   x()
#   y()
#   <goto-label "a">
#   z()
#   <goto-stmnt "a">
#   w()
#   if v(): <goto-stmnt "a">
#   q()
# Now, we can implement the goto-handling based on this flattened code:
# - Add a big endless loop around it. After the final statement,
#   a break would leave the loop.
# - Before the loop, we add the statement `goto = None`.
# - The goto-labels will split the code into multiple part, where
#   we add some `if goto is None:` before each part
#   (excluding the goto-labels).
# - For the goto-labels itself, we add this code:
#   `if goto == <goto-label>: goto = None`
# - For every goto-statement, we add this code:
#   `goto = <goto-stmnt>; continue`


class GotoLabel:
	def __init__(self, label):
		self.label = label


class GotoStatement:
	def __init__(self, label):
		self.label = label


class _Flatten:
	def __init__(self):
		self.c = 1

	def make_jump(self):
		label = self.c
		self.c += 1
		return GotoStatement(label)

	def flatten(self, body):
		"""
		:type body: list[ast.AST]
		:rtype: list[ast.AST]
		"""
		r = []
		for s in body:
			if isinstance(s, ast.If):
				a = ast.UnaryOp()
				a.op = ast.Not()
				a.operand = s.test
				goto_final_stmnt = self.make_jump()
				r += [ast.If(test=a, body=[goto_final_stmnt], orelse=[])]
				r += self.flatten(s.body)
				r += [GotoLabel(goto_final_stmnt.label)]
			elif isinstance(s, ast.While):
				if s.orelse: raise NotImplementedError
				goto_repeat_stmnt = self.make_jump()
				r += [GotoLabel(goto_repeat_stmnt.label)]
				a = ast.UnaryOp()
				a.op = ast.Not()
				a.operand = s.test
				goto_final_stmnt = self.make_jump()
				r += [ast.If(test=a, body=[goto_final_stmnt], orelse=[])]
				r += self.flatten(s.body)
				r += [goto_repeat_stmnt]
				r += [GotoLabel(goto_final_stmnt.label)]
			elif isinstance(s, ast.For):
				raise NotImplementedError
			elif isinstance(s, (ast.TryExcept, ast.TryFinally)):
				raise NotImplementedError
			else:
				r += [s]
		return r


def _ast_for_value(v):
	if isinstance(v, str): return ast.Str(s=v)
	elif isinstance(v, int): return ast.Num(n=v)
	else: raise NotImplementedError("type (%r) %r" % (type(v), v))


class _HandleGoto:

	def __init__(self, gotoVarName):
		self.gotoVarName = gotoVarName

	def handle_goto_stmnt(self, stmnt):
		assert isinstance(stmnt, GotoStatement)
		a = ast.Assign()
		a.targets = [ast.Name(id=self.gotoVarName, ctx=ast.Store())]
		a.value = _ast_for_value(stmnt.label)
		return [a, ast.Continue()]

	def handle_goto_label(self, stmnt):
		assert isinstance(stmnt, GotoLabel)
		reset_ast = ast.Assign()
		reset_ast.targets = [ast.Name(id=self.gotoVarName, ctx=ast.Store())]
		reset_ast.value = ast.Name(id="None", ctx=ast.Load())
		test_ast = ast.Compare()
		test_ast.ops = [ast.Eq()]
		test_ast.left = ast.Name(id=self.gotoVarName, ctx=ast.Store())
		test_ast.comparators = [_ast_for_value(stmnt.label)]
		return [ast.If(test=test_ast, body=[reset_ast], orelse=[])]

	def handle_body(self, body):
		"""
		:type body: list[ast.AST]
		:rtype: list[ast.AST]
		"""
		parts = [[]]
		for s in body:
			if isinstance(s, GotoLabel):
				parts += [s, []]
			else:
				parts[-1].append(s)
		r = []
		for l in parts:
			if not l: continue
			if isinstance(l, GotoLabel):
				r += self.handle_goto_label(l)
			else:
				sr = []
				for s in l:
					if isinstance(s, ast.If):
						assert not s.orelse
						assert len(s.body) == 1
						assert isinstance(s.body[0], GotoStatement)
						sr += [ast.If(test=s.test, orelse=[],
									  body=self.handle_goto_stmnt(s.body[0]))]
					elif isinstance(s, (ast.While, ast.For)):
						assert False, "not expected: %r" % s
					elif isinstance(s, GotoStatement):
						sr += self.handle_goto_stmnt(s)
					else:
						sr += [s]
				test_ast = ast.Compare()
				test_ast.ops = [ast.Is()]
				test_ast.left = ast.Name(id=self.gotoVarName, ctx=ast.Store())
				test_ast.comparators = [ast.Name(id="None", ctx=ast.Load())]
				r += [ast.If(test=test_ast, body=sr, orelse=[])]
		return r

	def wrap_func_body(self, flat_body):
		var_ast = ast.Assign()
		var_ast.targets = [ast.Name(id=self.gotoVarName, ctx=ast.Store())]
		var_ast.value = ast.Name(id="None", ctx=ast.Load())
		main_loop_ast = ast.While(orelse=[])
		main_loop_ast.test = ast.Name(id="True", ctx=ast.Load())
		main_loop_ast.body = self.handle_body(flat_body)
		main_loop_ast.body += [ast.Break()]
		return [var_ast, main_loop_ast]


def transform_goto(f, gotoVarName):
	assert isinstance(f, ast.FunctionDef)
	flat_body = _Flatten().flatten(f.body)
	new_body = _HandleGoto(gotoVarName).wrap_func_body(flat_body)
	new_func_ast = ast.FunctionDef(
		name=f.name,
		args=f.args,
		decorator_list=f.decorator_list,
		body=new_body)
	return new_func_ast
