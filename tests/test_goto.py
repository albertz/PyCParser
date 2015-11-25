
from nose.tools import assert_equal, assert_is_instance, assert_in, assert_greater, assert_true, assert_false

import ast
import goto

def unparse(pyAst):
	from cStringIO import StringIO
	output = StringIO()
	from py_demo_unparse import Unparser
	Unparser(pyAst, output)
	output.write("\n")
	return output.getvalue()

def parse(s):
	return ast.parse(s)

def get_indent_prefix(s):
	return s[:len(s) - len(s.lstrip())]

def get_same_indent_prefix(lines):
	if not lines: return ""
	prefix = get_indent_prefix(lines[0])
	if not prefix: return ""
	if all([l.startswith(prefix) for l in lines]):
		return prefix
	return None

def remove_indent_lines(s):
	if not s: return ""
	lines = s.splitlines(True)
	prefix = get_same_indent_prefix(lines)
	if prefix is None:  # not in expected format. just lstrip all lines
		return "".join([l.lstrip() for l in lines])
	return "".join([l[len(prefix):] for l in lines])

def fix_code(s):
	if not s: return ""
	if not s[0]: return fix_code(s[1:])
	s = remove_indent_lines(s[1:])
	s = s.replace("\t", " " * 4)
	return s

def test_parse_unparse():
	s = """
	def foo():
		pass
	"""
	s = fix_code(s)
	print s
	a = parse(s)
	ss = unparse(a)
	assert_equal(s.strip(), ss.strip())

def test_transform_goto():
	s = """
	def foo():
		i = 0
		# :label
		if i == 5: return i
		i += 1
		print "hello"
		# goto label
	"""
	s = fix_code(s)
	print s
	m = parse(s)
	assert_is_instance(m, ast.Module)
	assert_equal(len(m.body), 1)
	f = m.body[0]
	assert_is_instance(f, ast.FunctionDef)
	assert_equal(len(f.body), 4)
	f.body = f.body[:1] + [goto.GotoLabel("label")] + f.body[1:] + [goto.GotoStatement("label")]
	f = goto.transform_goto(f, "goto")
	ss = unparse(f)
	print ss

	c = compile(ss, "<src>", "single")
	d = {}
	exec c in d, d
	func = d["foo"]
	r = func()
	assert_equal(r, 5)

