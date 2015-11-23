

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
