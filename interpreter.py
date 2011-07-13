# PyCParser - interpreter
# by Albert Zeyer, 2011
# code under LGPL

from cparser import *
from cwrapper import CStateWrapper

import ast

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

class FuncEnv:
	def __init__(self, stateStruct):
		self._stateStruct = stateStruct
		self.vars = {} # name -> varDecl
		self.varNames = {} # id(varDecl) -> name
		self.scopeStack = [] # FuncCodeblockScope
		self.astNode = ast.FunctionDef(arguments=[], body=[])
	def _registerNewVar(self, varName, varDecl):
		assert varDecl is not None
		assert id(varDecl) not in self.varNames
		for name in iterIdWithPostfixes(varName):
			if name not in self.vars:
				self.vars[name] = varDecl
				self.varNames[id(varDecl)] = name
				return name
	def registerNewVar(self, varName, varDecl):
		self.scopeStack[-1].registerNewVar(varName, varDecl)
	def _unregisterVar(self, varName):
		varDecl = self.vars[varName]
		del self.varNames[id(varDecl)]
		del self.vars[varName]
	def pushScope(self):
		scope = FuncCodeblockScope(funcEnv=self)
		self.scopeStack += [scope]
		return scope
	def popScope(self, astFuncBody):
		scope = self.scopeStack.pop()
		scope.finishMe()

def getAstNodeForVarType(varDecl):
	# TODO
	pass

def makeAstNodeCall(baseExpr):
	return ast.Call(func=baseExpr)

class FuncCodeblockScope:
	def __init__(self, funcEnv):
		self.varNames = set()
		self.funcEnv = funcEnv
	def registerNewVar(self, varName, varDecl):
		varName = self.funcEnv._registerNewVar(varName, varDecl)
		self.varNames.add(varName)
		a = ast.Assign()
		a.targets = [ast.Name(id=varName)]
		varTypeNode = getAstNodeForVarType(varDecl)
		a.value = makeAstNodeCall(varTypeNode)
		self.funcEnv.astNode.body.append(a)
	def _astForDeleteVar(self, varName):
		return ast.Delete(targets=[ast.Name(id=varName)])
	def finishMe(self):
		astCmds = []
		for varName in self.varNames:
			astCmds += [self._astForDeleteVar(varName)]
			self.funcEnv._unregisterVar(varName)
		self.varNames.clear()
		self.funcEnv.astNode.body.extend(astCmds)

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
			base.astNode.arguments.append(ast.Name(id=name))
		for c in func.body.contentlist:
			if isinstance(c, CVarDecl):
				base.registerNewVar(c.name, c)
			else:
				assert False, "cannot handle " + str(c) + " yet"
		base.popScope()
		return base
	
	def runFunc(self, funcname, *args):
		if funcname in self._func_cache:
			func = self._func_cache[funcname]
		else:
			func = self.translateFuncToPy(funcname)
			self._func_cache[funcname] = func
		func(*args)
