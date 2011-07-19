# PyCParser - interpreter
# by Albert Zeyer, 2011
# code under LGPL

from cparser import *
from cwrapper import CStateWrapper

import ast
import sys
import inspect

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

import keyword
PyReservedNames = set(dir(sys.modules["__builtin__"]) + keyword.kwlist + ["ctypes", "helpers"])

def isValidVarName(name):
	return name not in PyReservedNames

class GlobalScope:
	def __init__(self, stateStruct):
		self.stateStruct = stateStruct
		self.identifiers = {} # name -> CVarDecl | ...
		self.names = {} # id(decl) -> name
		
	def findIdentifier(self, name):
		o = self.identifiers.get(name, None)
		if o is not None: return o
		o = self.stateStruct.vars.get(name, None)
		if o is None: return None
		self.identifiers[name] = o
		self.names[id(o)] = name
		return o
	
	def findName(self, decl):
		name = self.names.get(id(decl), None)
		if name is not None: return name
		o = self.findIdentifier(decl.name)
		if o is decl: return decl.name
		return None
	
class FuncEnv:
	def __init__(self, globalScope):
		self.globalScope = globalScope
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
		return self.globalScope.findIdentifier(varName)
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
		name = self.globalScope.findName(varDecl)
		assert name is not None, str(varDecl) + " is expected to be a global var"
		return ast.Name(id=name)
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

NoneAstNode = ast.Name(id="None")

def getAstNodeAttrib(value, attrib):
	a = ast.Attribute()
	if isinstance(value, (str,unicode)):
		a.value = ast.Name(id=value)
	elif isinstance(value, ast.AST):
		a.value = value
	else:
		assert False, str(value) + " has invalid type"
	a.attr = attrib
	return a

def getAstNodeForCTypesBasicType(t):
	if t is None: return NoneAstNode
	if t is CVoidType: return NoneAstNode
	if not inspect.isclass(t) and isinstance(t, CVoidType): return NoneAstNode
	if issubclass(t, CVoidType): return None
	assert getattr(ctypes, t.__name__) is t
	return getAstNodeAttrib("ctypes", t.__name__)

def getAstNodeForVarType(t):
	if isinstance(t, CBuiltinType):
		return getAstNodeForCTypesBasicType(t.builtinType)
	elif isinstance(t, CStdIntType):
		return getAstNodeForCTypesBasicType(State.StdIntTypes[t.name])
	elif isinstance(t, CPointerType):
		a = ast.Attribute()
		a.value = ast.Name(id="ctypes")
		a.attr = "POINTER"
		return makeAstNodeCall(a, getAstNodeForVarType(t.pointerOf))
	elif isinstance(t, CTypedefType):
		return ast.Name(id=t.name)
	else:
		try: return getAstNodeForCTypesBasicType(t)
		except: pass
	assert False, "cannot handle " + str(t)

def makeAstNodeCall(func, *args):
	if not isinstance(func, ast.AST):
		# TODO ...
		func = NoneAstNode
	return ast.Call(func=func, args=args, keywords=[], starargs=None, kwargs=None)

def getAstNode_copyValue(objAst, objType):
	typeAst = getAstNodeForVarType(objType)
	return astForHelperFunc("copyWithTypeCheck", objAst, typeAst)

def getAstNode_newTypeInstance(objType, arg=None):
	typeAst = getAstNodeForVarType(objType)
	return makeAstNodeCall(typeAst, *([arg] if arg is not None else []))

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
		if isinstance(varDecl, CFuncArgDecl):
			a.value = getAstNode_copyValue(ast.Name(id=varName, ctx=ast.Load()), varDecl.type)
		elif isinstance(varDecl, CVarDecl):
			if varDecl.body is not None:
				bodyAst, t = astAndTypeForStatement(self.funcEnv, varDecl.body)
				a.value = getAstNode_newTypeInstance(t, bodyAst)
				if t != varDecl.type:
					a.value = getAstNode_newTypeInstance(varDecl.type, a.value)
			else:	
				a.value = getAstNode_newTypeInstance(varDecl.type)
		else:
			assert False, "didn't expected " + str(varDecl)
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

def _astOpToFunc(op):
	if inspect.isclass(op): op = op()
	assert isinstance(op, ast.operator)
	l = ast.Lambda()
	a = l.args = ast.arguments()
	a.args = [
		ast.Name(id="a", ctx=ast.Param()),
		ast.Name(id="b", ctx=ast.Param())]
	a.vararg = None
	a.kwarg = None
	a.defaults = []
	t = l.body = ast.BinOp()
	t.left = ast.Name(id="a", ctx=ast.Load())
	t.right = ast.Name(id="b", ctx=ast.Load())
	t.op = op
	expr = ast.Expression(body=l)
	ast.fix_missing_locations(expr)
	code = compile(expr, "<_astOpToFunc>", "eval")
	f = eval(code)
	return f

OpBinFuncs = dict(map(lambda op: (op, _astOpToFunc(op)), OpBin.itervalues()))

class Helpers:
	@staticmethod
	def prefixInc(a):
		a.value += 1
		return a
	
	@staticmethod
	def prefixDec(a):
		a.value -= 1
		return a
	
	@staticmethod
	def postfixInc(a):
		b = a.__class__(a.value) # copy
		a.value += 1
		return b
	
	@staticmethod
	def postfixDec(a):
		b = a.__class__(a.value) # copy
		a.value -= 1
		return b
	
	@staticmethod
	def copy(a):
		if isinstance(a, _ctypes._SimpleCData):
			c = a.__class__()
			pointer(c)[0] = a
			return c
			#if isinstance(a, _ctypes._Pointer):
			#	ptr = ctypes.cast(a, ctypes.c_void_p)
			#	return a.__class__(ptr.value)
		assert False, "cannot copy " + str(a)
	
	@staticmethod
	def copyWithTypeCheck(a, typ):
		assert a.__class__ == typ
		return copy(a)

	@staticmethod
	def assign(a, b):
		a.value = b.value
		return a
	
	@staticmethod
	def augAssign(a, op, b):
		a.value = OpBinFuncs[op](a.value, b.value)
		return a

def astForHelperFunc(helperFuncName, *astArgs):
	helperFuncAst = getAstNodeAttrib("helpers", helperFuncName)
	a = ast.Call(keywords=[], starargs=None, kwargs=None)
	a.func = helperFuncAst
	a.args = astArgs
	return a

def astAndTypeForStatement(funcEnv, stmnt):
	if isinstance(stmnt, (CVarDecl,CFuncArgDecl)):
		return funcEnv.getAstNodeForVarDecl(stmnt), stmnt.type
	elif isinstance(stmnt, CStatement):
		return astAndTypeForCStatement(funcEnv, stmnt)
	elif isinstance(stmnt, CAttribAccessRef):
		assert stmnt.name is not None
		a = ast.Attribute()
		a.value, t = astAndTypeForStatement(funcEnv, stmnt.base)
		a.attr = stmnt.name
		while isinstance(t, CTypedefType):
			t = funcEnv.globalScope.stateStruct.typedefs[t.name]
		assert isinstance(t, (CStruct,CUnion))
		attrDecl = t.findAttrib(a.attr)
		assert attrDecl is not None
		return a, attrDecl.type
	elif isinstance(stmnt, CNumber):
		t = minCIntTypeForNums(stmnt.content)
		if t is None: t = "int64_t" # it's an overflow; just take a big type
		return ast.Num(n=stmnt.content), CStdIntType(t)
	elif isinstance(stmnt, CStr):
		return ast.Str(s=stmnt.content), ctypes.c_char_p
	elif isinstance(stmnt, CChar):
		return ast.Str(s=stmnt.content), ctypes.c_char
	elif isinstance(stmnt, CFuncCall):
		if isinstance(stmnt.base, CFunc):
			assert stmnt.base.name is not None
			a = ast.Call(keywords=[], starargs=None, kwargs=None)
			a.func = ast.Name(id=stmnt.base.name)
			a.args = map(lambda arg: astAndTypeForStatement(funcEnv, arg)[0], stmnt.args)
			return a, stmnt.type
		elif isinstance(stmnt.base, CStatement) and stmnt.base.isCType():
			assert len(stmnt.args) == 1
			v, _ = astAndTypeForStatement(funcEnv, stmnt.args[0])
			return v, stmnt.base.asType()
		else:
			assert False, "cannot handle " + str(stmnt.base) + " call"
	elif isinstance(stmnt, CWrapValue):
		# TODO
		return ast.Name(id="None"), ctypes.c_int
	else:
		assert False, "cannot handle " + str(stmnt)

def astAndTypeForCStatement(funcEnv, stmnt):
	assert isinstance(stmnt, CStatement)
	if stmnt._leftexpr is None: # prefixed only
		rightAstNode,rightType = astAndTypeForStatement(funcEnv, stmnt._rightexpr)
		if stmnt._op.content == "++":
			return makeAstNodeCall(helper_prefixInc, rightAstNode), rightType
		elif stmnt._op.content == "--":
			return makeAstNodeCall(helper_prefixDec, rightAstNode), rightType
		elif stmnt._op.content in OpUnary:
			a = ast.UnaryOp()
			a.op = OpUnary[stmnt._op.content]()
			a.operand = rightAstNode
			return a, rightType
		else:
			assert False, "unary prefix op " + str(stmnt._op) + " is unknown"
	if stmnt._op is None:
		return astAndTypeForStatement(funcEnv, stmnt._leftexpr)
	if stmnt._rightexpr is None:
		leftAstNode, leftType = astAndTypeForStatement(funcEnv, stmnt._leftexpr)
		if stmnt._op.content == "++":
			return makeAstNodeCall(helper_postfixInc, leftAstNode), leftType
		elif stmnt._op.content == "--":
			return makeAstNodeCall(helper_postfixDec, leftAstNode), leftType
		else:
			assert False, "unary postfix op " + str(stmnt._op) + " is unknown"
	leftAstNode, leftType = astAndTypeForStatement(funcEnv, stmnt._leftexpr)
	rightAstNode, rightType = astAndTypeForStatement(funcEnv, stmnt._rightexpr)
	if stmnt._op.content in OpBin:
		a = ast.BinOp()
		a.op = OpBin[stmnt._op.content]()
		a.left = leftAstNode
		a.right = rightAstNode
		return a, leftType # TODO: not really correct. e.g. int + float -> float
	elif stmnt._op.content in OpBinBool:
		a = ast.BoolOp()
		a.op = OpBinBool[stmnt._op.content]()
		a.values = [leftAstNode, rightAstNode]
		return a, ctypes.c_int
	elif stmnt._op.content in OpBinCmp:
		a = ast.Compare()
		a.ops = [OpBinCmp[stmnt._op.content]()]
		a.left = leftAstNode
		a.comparators = [rightAstNode]
		return a, ctypes.c_int
	elif stmnt._op.content == "=":
		a = ast.Assign()
		a.targets = [leftAstNode]
		a.value = rightAstNode
		return a, leftType
	elif stmnt._op.content in OpAugAssign:
		a = ast.AugAssign()
		a.op = OpAugAssign[stmnt._op.content]()
		a.target = leftAstNode
		a.value = rightAstNode
		return a, leftType
	elif stmnt._op.content == "?:":
		middleAstNode, middleType = astAndTypeForStatement(funcEnv, stmnt._middleexpr)
		a = ast.IfExp()
		a.test = leftAstNode
		a.body = middleAstNode
		a.orelse = rightAstNode
		return a, middleType # TODO: not really correct...
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
		self.globalScope = GlobalScope(self._cStateWrapper)
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
		base = FuncEnv(globalScope=self.globalScope)
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
				a, t = astAndTypeForCStatement(base, c)
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
