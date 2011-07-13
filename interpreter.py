# PyCParser - interpreter
# by Albert Zeyer, 2011
# code under LGPL

from cparser import *
from cwrapper import CStateWrapper

import ast
import sys

class CWrapValue:
	def __init__(self, value):
		self.value = value
	def __repr__(self):
		return "<" + self.__class__.__name__ + " " + repr(self.value) + ">"

def iterIdentifierNames():
	S = "abcdefghijklmnopqrstuvwxyz0123456789"
	n = 0
	while True:
		v = []
		x = n
		while x > 0 or len(v) == 0:
			v = [x % len(S)] + v
			x /= len(S)
		yield "".join(map(lambda x: S[x], v))
		n += 1

def iterIdWithPostfixes(name):
	if name is None:
		for postfix in iterIdentifierNames():
			yield "__dummy_" + postfix
		return
	yield name
	for postfix in iterIdentifierNames():
		yield name + "_" + postfix

PyReservedNames = set(dir(__builtins__))

def isValidVarName(name):
	return name not in PyReservedNames

class FuncEnv:
	def __init__(self, stateStruct):
		self._stateStruct = stateStruct
		self.outerScope = stateStruct
		self.vars = {} # name -> varDecl
		self.varNames = {} # id(varDecl) -> name
		self.scopeStack = [] # FuncCodeblockScope
		self.astNode = ast.FunctionDef(name=None, args=[], body=[], decorator_list=[])
	def _registerNewVar(self, varName, varDecl):
		assert varDecl is not None
		assert id(varDecl) not in self.varNames
		for name in iterIdWithPostfixes(varName):
			if not isValidVarName(name): continue
			if self.searchVarName(name) is None:
				self.vars[name] = varDecl
				self.varNames[id(varDecl)] = name
				return name
	def searchVarName(self, varName):
		if varName in self.vars: return self.vars[varName]
		if varName in self.outerScope.vars: return self.outerScope.vars[varName]
		return None
	def registerNewVar(self, varName, varDecl):
		return self.scopeStack[-1].registerNewVar(varName, varDecl)
	def getAstNodeForVarDecl(self, varDecl):
		assert varDecl is not None
		if id(varDecl) in self.varNames:
			# local var
			name = self.varNames[id(varDecl)]
			assert name is not None
			return ast.Name(id=name)
		# we expect this is a global
		assert varDecl.name in self.outerScope.vars, str(varDecl) + " is expected to be a global var"
		assert varDecl.name is not None
		return ast.Name(id=varDecl.name)
	def _unregisterVar(self, varName):
		varDecl = self.vars[varName]
		del self.varNames[id(varDecl)]
		del self.vars[varName]
	def pushScope(self):
		scope = FuncCodeblockScope(funcEnv=self)
		self.scopeStack += [scope]
		return scope
	def popScope(self):
		scope = self.scopeStack.pop()
		scope.finishMe()

def getAstNodeForVarType(varDecl):
	# TODO
	pass

def makeAstNodeCall(func, *args):
	if not isinstance(func, ast.AST):
		# TODO ...
		func = ast.Name(id="None")
	return ast.Call(func=func, args=args, keywords=[], starargs=None, kwargs=None)
	
class FuncCodeblockScope:
	def __init__(self, funcEnv):
		self.varNames = set()
		self.funcEnv = funcEnv
	def registerNewVar(self, varName, varDecl):
		varName = self.funcEnv._registerNewVar(varName, varDecl)
		assert varName is not None
		self.varNames.add(varName)
		a = ast.Assign()
		a.targets = [ast.Name(id=varName)]
		varTypeNode = getAstNodeForVarType(varDecl)
		a.value = makeAstNodeCall(varTypeNode)
		self.funcEnv.astNode.body.append(a)
		return varName
	def _astForDeleteVar(self, varName):
		assert varName is not None
		return ast.Delete(targets=[ast.Name(id=varName)])
	def finishMe(self):
		astCmds = []
		for varName in self.varNames:
			astCmds += [self._astForDeleteVar(varName)]
			self.funcEnv._unregisterVar(varName)
		self.varNames.clear()
		self.funcEnv.astNode.body.extend(astCmds)

OpUnary = {
	"~": ast.Invert,
	"!": ast.Not,
	"+": ast.UAdd,
	"-": ast.USub,
}

OpBin = {
	"+": ast.Add,
	"-": ast.Sub,
	"*": ast.Mult,
	"/": ast.Div,
	"%": ast.Mod,
	"<<": ast.LShift,
	">>": ast.RShift,
	"|": ast.BitOr,
	"^": ast.BitXor,
	"&": ast.BitAnd,
}

OpBinBool = {
	"&&": ast.And,
	"||": ast.Or,
}

OpBinCmp = {
	"==": ast.Eq,
	"!=": ast.NotEq,
	"<": ast.Lt,
	"<=": ast.LtE,
	">": ast.Gt,
	">=": ast.GtE,
}

OpAugAssign = dict(map(lambda (k,v): (k + "=", v), OpBin.iteritems()))

def helper_prefixInc(a):
	a.value += 1
	return a

def helper_prefixDec(a):
	a.value -= 1
	return a

def helper_postfixInc(a):
	b = a.__class__(a.value) # copy
	a.value += 1
	return b

def helper_postfixDec(a):
	b = a.__class__(a.value) # copy
	a.value -= 1
	return b

def astForStatement(funcEnv, stmnt):
	if isinstance(stmnt, (CVarDecl,CFuncArgDecl)):
		return funcEnv.getAstNodeForVarDecl(stmnt)
	elif isinstance(stmnt, CStatement):
		return astForCStatement(funcEnv, stmnt)
	elif isinstance(stmnt, CAttribAccessRef):
		assert stmnt.name is not None
		a = ast.Attribute()
		a.value = astForStatement(funcEnv, stmnt.base)
		a.attr = stmnt.name
		return a
	elif isinstance(stmnt, CNumber):
		return ast.Num(n=stmnt.content)
	elif isinstance(stmnt, CStr):
		return ast.Str(s=stmnt.content)
	elif isinstance(stmnt, CChar):
		return ast.Str(s=stmnt.content)
	elif isinstance(stmnt, CFuncCall):
		if isinstance(stmnt.base, CFunc):
			assert stmnt.base.name is not None
			a = ast.Call(keywords=[], starargs=None, kwargs=None)
			a.func = ast.Name(id=stmnt.base.name)
			a.args = map(lambda arg: astForStatement(funcEnv, arg), stmnt.args)
			return a
		elif isinstance(stmnt.base, CStatement) and stmnt.base.isCType():
			# TODO cast ...
			return ast.Name(id="None")
		else:
			assert False, "cannot handle " + str(stmnt.base) + " call"
	elif isinstance(stmnt, CWrapValue):
		# TODO
		return ast.Name(id="None")
	else:
		assert False, "cannot handle " + str(stmnt)

def astForCStatement(funcEnv, stmnt):
	assert isinstance(stmnt, CStatement)
	if stmnt._leftexpr is None: # prefixed only
		rightAstNode = astForStatement(funcEnv, stmnt._rightexpr)
		if stmnt._op.content == "++":
			return makeAstNodeCall(helper_prefixInc, rightAstNode)
		elif stmnt._op.content == "--":
			return makeAstNodeCall(helper_prefixDec, rightAstNode)
		elif stmnt._op.content in OpUnary:
			a = ast.UnaryOp()
			a.op = OpUnary[stmnt._op.content]()
			a.operand = rightAstNode
			return a
		else:
			assert False, "unary prefix op " + str(stmnt._op) + " is unknown"
	if stmnt._op is None:
		return astForStatement(funcEnv, stmnt._leftexpr)
	if stmnt._rightexpr is None:
		leftAstNode = astForStatement(funcEnv, stmnt._leftexpr)
		if stmnt._op.content == "++":
			return makeAstNodeCall(helper_postfixInc, leftAstNode)
		elif stmnt._op.content == "--":
			return makeAstNodeCall(helper_postfixDec, leftAstNode)
		else:
			assert False, "unary postfix op " + str(stmnt._op) + " is unknown"
	leftAstNode = astForStatement(funcEnv, stmnt._leftexpr)
	rightAstNode = astForStatement(funcEnv, stmnt._rightexpr)
	if stmnt._op.content in OpBin:
		a = ast.BinOp()
		a.op = OpBin[stmnt._op.content]()
		a.left = leftAstNode
		a.right = rightAstNode
		return a
	elif stmnt._op.content in OpBinBool:
		a = ast.BoolOp()
		a.op = OpBinBool[stmnt._op.content]()
		a.values = [leftAstNode, rightAstNode]
		return a
	elif stmnt._op.content in OpBinCmp:
		a = ast.Compare()
		a.ops = [OpBinCmp[stmnt._op.content]()]
		a.left = leftAstNode
		a.comparators = [rightAstNode]
		return a
	elif stmnt._op.content == "=":
		a = ast.Assign()
		a.targets = [leftAstNode]
		a.value = rightAstNode
		return a
	elif stmnt._op.content in OpAugAssign:
		a = ast.AugAssign()
		a.op = OpAugAssign[stmnt._op.content]()
		a.target = leftAstNode
		a.value = rightAstNode
		return a
	elif stmnt._op.content == "?:":
		middleAstNode = astForStatement(funcEnv, stmnt._middleexpr)
		a = ast.IfExp()
		a.test = leftAstNode
		a.body = middleAstNode
		a.orelse = rightAstNode
		return a
	else:
		assert False, "binary op " + str(stmnt._op) + " is unknown"

PyAstNoOp = ast.Assert(test=ast.Name(id="True"), msg=None)

def astForCWhile(funcEnv, stmnt):
	assert isinstance(stmnt, CWhileStatement)
	assert len(stmnt.args) == 1
	# TODO ...
	return PyAstNoOp

def astForCFor(funcEnv, stmnt):
	# TODO
	return PyAstNoOp

def astForCDoWhile(funcEnv, stmnt):
	# TODO
	return PyAstNoOp

def astForCIf(funcEnv, stmnt):
	# TODO
	return PyAstNoOp

def astForCReturn(funcEnv, stmnt):
	# TODO
	return PyAstNoOp

class Interpreter:
	def __init__(self):
		self.stateStructs = []
		self._cStateWrapper = CStateWrapper(self)
		self._func_cache = {}
		
	def register(self, stateStruct):
		self.stateStructs += [stateStruct]
	
	def getCType(self, obj):
		wrappedStateStruct = self._cStateWrapper
		for T,DictName in [(CStruct,"structs"), (CUnion,"unions"), (CEnum,"enums")]:
			if isinstance(obj, T):
				if obj.name is not None:
					return getattr(wrappedStateStruct, DictName)[obj.name].getCValue(wrappedStateStruct)
				else:
					return obj.getCValue(wrappedStateStruct)
		return obj.getCValue(wrappedStateStruct)
	
	def translateFuncToPy(self, funcname):
		func = self._cStateWrapper.funcs[funcname]
		base = FuncEnv(stateStruct=self._cStateWrapper)
		base.astNode.name = funcname
		base.pushScope()
		for arg in func.args:
			name = base.registerNewVar(arg.name, arg)
			assert name is not None
			base.astNode.args.append(ast.Name(id=name))
		for c in func.body.contentlist:
			if isinstance(c, CVarDecl):
				base.registerNewVar(c.name, c)
			elif isinstance(c, CStatement):
				a = astForCStatement(base, c)
				if isinstance(a, ast.expr):
					a = ast.Expr(value=a)
				base.astNode.body.append(a)
			elif isinstance(c, CWhileStatement):
				base.astNode.body.append(astForCWhile(base, c))
			elif isinstance(c, CForStatement):
				base.astNode.body.append(astForCFor(base, c))
			elif isinstance(c, CDoStatement):
				base.astNode.body.append(astForCDoWhile(base, c))
			elif isinstance(c, CIfStatement):
				base.astNode.body.append(astForCIf(base, c))
			elif isinstance(c, CReturnStatement):
				base.astNode.body.append(astForCReturn(base, c))
			else:
				assert False, "cannot handle " + str(c)
		base.popScope()
		return base
	
	def getFunc(self, funcname):
		if funcname in self._func_cache:
			return self._func_cache[funcname]
		else:
			func = self.translateFuncToPy(funcname)
			self._func_cache[funcname] = func
			return func
	
	def dumpFunc(self, funcname, output=sys.stdout):
		f = self.getFunc(funcname)
		from py_demo_unparse import Unparser
		Unparser(f.astNode, output)
		
	def runFunc(self, funcname, *args):
		self.getFunc(funcname)(*args)
