# PyCParser - interpreter
# by Albert Zeyer, 2011
# code under LGPL

from cparser import *
from cwrapper import CStateWrapper

import _ctypes
import ast
import sys
import inspect

class CWrapValue:
	def __init__(self, value, decl=None, **kwattr):
		self.value = value
		self.decl = decl
		for k,v in kwattr.iteritems():
			setattr(self, k, v)
	def __repr__(self):
		s = "<" + self.__class__.__name__ + " "
		if self.decl is not None: s += repr(self.decl) + " "
		s += repr(self.value)
		s += ">"
		return s
	def getCType(self):
		if self.decl is not None: return self.decl.type
		elif self.value is not None and hasattr(self.value, "__class__"):
			return self.value.__class__
			#if isinstance(self.value, (_ctypes._SimpleCData,ctypes.Structure,ctypes.Union)):
		return self	
			
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
	StateScopeDicts = ["vars", "typedefs", "funcs"]
	
	def __init__(self, interpreter, stateStruct):
		self.interpreter = interpreter
		self.stateStruct = stateStruct
		self.identifiers = {} # name -> CVarDecl | ...
		self.names = {} # id(decl) -> name
		self.vars = {} # name -> value
		
	def _findId(self, name):
		for D in self.StateScopeDicts:
			d = getattr(self.stateStruct, D)
			o = d.get(name)
			if o is not None: return o
		return None
	
	def findIdentifier(self, name):
		o = self.identifiers.get(name, None)
		if o is not None: return o
		o = self._findId(name)
		if o is None: return None
		self.identifiers[name] = o
		self.names[id(o)] = name
		return o
	
	def findName(self, decl):
		name = self.names.get(id(decl), None)
		if name is not None: return name
		o = self.findIdentifier(decl.name)
		if o is None: return None
		# Note: `o` might be a different object than `decl`.
		# This can happen if `o` is the extern declaration and `decl`
		# is the actual variable. Anyway, this is fine.
		return o.name
	
	def registerExternVar(self, name_prefix, value=None):
		if not isinstance(value, CWrapValue):
			value = CWrapValue(value)
		for name in iterIdWithPostfixes(name_prefix):
			if self.findIdentifier(name) is not None: continue
			self.identifiers[name] = value
			return name

	def registerExterns(self):
		self.varname_ctypes = self.registerExternVar("ctypes", ctypes)
		self.varname_helpers = self.registerExternVar("helpers", Helpers)

	def getVar(self, name):
		if name in self.vars: return self.vars[name]
		decl = self.findIdentifier(name)
		assert isinstance(decl, CVarDecl)
		if decl.body is not None:
			bodyAst, t = astAndTypeForStatement(self, decl.body)
			if isPointerType(decl.type) and not isPointerType(t):
				v = decl.body.getConstValue(self.stateStruct)
				assert not v, "Global: Initializing pointer type " + str(decl.type) + " only supported with 0 value but we got " + str(v) + " from " + str(decl.body)
				valueAst = getAstNode_newTypeInstance(self.interpreter, decl.type)
			else:
				valueAst = getAstNode_newTypeInstance(self.interpreter, decl.type, bodyAst, t)
		else:	
			valueAst = getAstNode_newTypeInstance(self.interpreter, decl.type)
		v = evalValueAst(self, valueAst, "<PyCParser_globalvar_" + name + "_init>")
		self.vars[name] = v
		return v

def evalValueAst(funcEnv, valueAst, srccode_name=None):
	if srccode_name is None: srccode_name = "<PyCParser_dynamic_eval>"
	valueExprAst = ast.Expression(valueAst)
	ast.fix_missing_locations(valueExprAst)
	valueCode = compile(valueExprAst, "<PyCParser_globalvar_" + srccode_name + "_init>", "eval")
	v = eval(valueCode, funcEnv.interpreter.globalsDict)
	return v

class GlobalsWrapper:
	def __init__(self, globalScope):
		self.globalScope = globalScope
	
	def __setattr__(self, name, value):
		self.__dict__[name] = value
	
	def __getattr__(self, name):
		decl = self.globalScope.findIdentifier(name)
		if decl is None: raise KeyError
		if isinstance(decl, CVarDecl):
			v = self.globalScope.getVar(name)
		elif isinstance(decl, CWrapValue):
			v = decl.value
		elif isinstance(decl, CFunc):
			v = self.globalScope.interpreter.getFunc(name)
		elif isinstance(decl, (CTypedef,CStruct,CUnion,CEnum)):
			v = getCType(decl, self.globalScope.stateStruct)
		else:
			assert False, "didn't expected " + str(decl)
		self.__dict__[name] = v
		return v
	
	def __repr__(self):
		return "<" + self.__class__.__name__ + " " + repr(self.__dict__) + ">"

class GlobalsStructWrapper:
	def __init__(self, globalScope):
		self.globalScope = globalScope
	
	def __setattr__(self, name, value):
		self.__dict__[name] = value
	
	def __getattr__(self, name):
		decl = self.globalScope.stateStruct.structs.get(name)
		if decl is None: raise AttributeError
		v = getCType(decl, self.globalScope.stateStruct)
		self.__dict__[name] = v
		return v
	
	def __repr__(self):
		return "<" + self.__class__.__name__ + " " + repr(self.__dict__) + ">"
	
class FuncEnv:
	def __init__(self, globalScope):
		self.globalScope = globalScope
		self.interpreter = globalScope.interpreter
		self.vars = {} # name -> varDecl
		self.varNames = {} # id(varDecl) -> name
		self.scopeStack = [] # FuncCodeblockScope
		self.astNode = ast.FunctionDef(
			args=ast.arguments(args=[], vararg=None, kwarg=None, defaults=[]),
			body=[], decorator_list=[])
	def _registerNewVar(self, varName, varDecl):
		if varDecl is not None:
			assert id(varDecl) not in self.varNames
		for name in iterIdWithPostfixes(varName):
			if not isValidVarName(name): continue
			if self.searchVarName(name) is None:
				self.vars[name] = varDecl
				if varDecl is not None:
					self.varNames[id(varDecl)] = name
				return name
	def searchVarName(self, varName):
		if varName in self.vars: return self.vars[varName]
		return self.globalScope.findIdentifier(varName)
	def registerNewVar(self, varName, varDecl=None):
		return self.scopeStack[-1].registerNewVar(varName, varDecl)
	def getAstNodeForVarDecl(self, varDecl):
		assert varDecl is not None
		if id(varDecl) in self.varNames:
			# local var
			name = self.varNames[id(varDecl)]
			assert name is not None
			return ast.Name(id=name, ctx=ast.Load())
		# we expect this is a global
		name = self.globalScope.findName(varDecl)
		assert name is not None, str(varDecl) + " is expected to be a global var"
		return getAstNodeAttrib("g", name)
	def _unregisterVar(self, varName):
		varDecl = self.vars[varName]
		if varDecl is not None:
			del self.varNames[id(varDecl)]
		del self.vars[varName]
	def pushScope(self, bodyStmntList):
		scope = FuncCodeblockScope(funcEnv=self, body=bodyStmntList)
		self.scopeStack += [scope]
		return scope
	def popScope(self):
		scope = self.scopeStack.pop()
		scope.finishMe()
	def getBody(self):
		return self.scopeStack[-1].body
		
NoneAstNode = ast.Name(id="None", ctx=ast.Load())

def getAstNodeAttrib(value, attrib, ctx=ast.Load()):
	a = ast.Attribute(ctx=ctx)
	if isinstance(value, (str,unicode)):
		a.value = ast.Name(id=str(value), ctx=ctx)
	elif isinstance(value, ast.AST):
		a.value = value
	else:
		assert False, str(value) + " has invalid type"
	assert attrib is not None
	a.attr = str(attrib)
	return a

def getAstNodeForCTypesBasicType(t):
	if t is None: return NoneAstNode
	if t is CVoidType: return NoneAstNode
	if not inspect.isclass(t) and isinstance(t, CVoidType): return NoneAstNode
	if issubclass(t, CVoidType): return None
	assert issubclass(t, getattr(ctypes, t.__name__))
	return getAstNodeAttrib("ctypes", t.__name__)

def getAstNodeForVarType(interpreter, t):
	if isinstance(t, CBuiltinType):
		return getAstNodeForCTypesBasicType(t.builtinType)
	elif isinstance(t, CStdIntType):
		return getAstNodeForCTypesBasicType(State.StdIntTypes[t.name])
	elif isinstance(t, CPointerType):
		a = getAstNodeAttrib("ctypes", "POINTER")
		return makeAstNodeCall(a, getAstNodeForVarType(interpreter, t.pointerOf))
	elif isinstance(t, CTypedefType):
		return getAstNodeAttrib("g", t.name)
	elif isinstance(t, CStruct):
		if t.name is None:
			# We have a problem. Actually, I wonder how this can happen.
			# But we have an anonymous struct here.
			# Wrap it via CWrapValue
			v = getAstForWrapValue(interpreter, CWrapValue(t))
			return getAstNodeAttrib(v, "value")
		# TODO: this assumes the was previously declared globally.
		return getAstNodeAttrib("structs", t.name)
	else:
		try: return getAstNodeForCTypesBasicType(t)
		except: pass
	assert False, "cannot handle " + str(t)

def findHelperFunc(f):
	for k in dir(Helpers):
		v = getattr(Helpers, k)
		if v is f: return k
	return None

def makeAstNodeCall(func, *args):
	if not isinstance(func, ast.AST):
		name = findHelperFunc(func)
		assert name is not None, str(func) + " unknown"
		func = getAstNodeAttrib("helpers", name)
	return ast.Call(func=func, args=list(args), keywords=[], starargs=None, kwargs=None)

def isPointerType(t):
	if isinstance(t, CPointerType): return True
	import inspect
	if inspect.isclass(t) and issubclass(t, _ctypes._Pointer): return True
	return False

def getAstNode_valueFromObj(objAst, objType):
	if isPointerType(objType):
		astVoidPT = getAstNodeAttrib("ctypes", "c_void_p")
		astCast = getAstNodeAttrib("ctypes", "cast")
		astVoidP = makeAstNodeCall(astCast, objAst, astVoidPT)
		astValue = getAstNodeAttrib(astVoidP, "value")
		return ast.BoolOp(op=ast.Or(), values=[astValue, ast.Num(0)])
	else:
		astValue = getAstNodeAttrib(objAst, "value")
		return astValue		
		
def getAstNode_newTypeInstance(interpreter, objType, argAst=None, argType=None):
	typeAst = getAstNodeForVarType(interpreter, objType)

	if isPointerType(objType) and isPointerType(argType):
		# We can have it simpler. This is even important in some cases
		# were the pointer instance is temporary and the object
		# would get freed otherwise!
		astCast = getAstNodeAttrib("ctypes", "cast")
		return makeAstNodeCall(astCast, argAst, typeAst)		
		
	args = []
	if argAst is not None:
		if isinstance(argAst, (ast.Str, ast.Num)):
			args += [argAst]
		elif argType is not None:
			args += [getAstNode_valueFromObj(argAst, argType)]
		else:
			# expect that it is the AST for the value.
			# there is no really way to 'assert' this.
			args += [argAst]

	if isPointerType(objType) and argAst is not None:
		assert False, "not supported because unsafe! " + str(argAst)
		return makeAstNodeCall(typeAst)		
		#astVoidPT = getAstNodeAttrib("ctypes", "c_void_p")
		#astCast = getAstNodeAttrib("ctypes", "cast")
		#astVoidP = makeAstNodeCall(astVoidPT, *args)
		#return makeAstNodeCall(astCast, astVoidP, typeAst)
	else:
		return makeAstNodeCall(typeAst, *args)

class FuncCodeblockScope:
	def __init__(self, funcEnv, body):
		self.varNames = set()
		self.funcEnv = funcEnv
		self.body = body
	def registerNewVar(self, varName, varDecl):
		varName = self.funcEnv._registerNewVar(varName, varDecl)
		assert varName is not None
		self.varNames.add(varName)
		a = ast.Assign()
		a.targets = [ast.Name(id=varName, ctx=ast.Store())]
		if varDecl is None:
			a.value = ast.Name(id="None", ctx=ast.Load())
		elif isinstance(varDecl, CFuncArgDecl):
			# Note: We just assume that the parameter has the correct/same type.
			a.value = getAstNode_newTypeInstance(self.funcEnv.interpreter, varDecl.type, ast.Name(id=varName, ctx=ast.Load()), varDecl.type)
		elif isinstance(varDecl, CVarDecl):
			if varDecl.body is not None:
				bodyAst, t = astAndTypeForStatement(self.funcEnv, varDecl.body)
				if isPointerType(varDecl.type) and not isPointerType(t):
					v = varDecl.body.getConstValue(self.funcEnv.globalScope.stateStruct)
					assert not v, "Initializing pointer type " + str(varDecl.type) + " only supported with 0 value but we got " + str(v) + " from " + str(varDecl.body)
					a.value = getAstNode_newTypeInstance(self.funcEnv.interpreter, varDecl.type)
				else:
					a.value = getAstNode_newTypeInstance(self.funcEnv.interpreter, varDecl.type, bodyAst, t)
			else:	
				a.value = getAstNode_newTypeInstance(self.funcEnv.interpreter, varDecl.type)
		elif isinstance(varDecl, CFunc):
			# TODO: register func, ...
			a.value = ast.Name(id="None", ctx=ast.Load())
		else:
			assert False, "didn't expected " + str(varDecl)
		self.body.append(a)
		return varName
	def _astForDeleteVar(self, varName):
		assert varName is not None
		return ast.Delete(targets=[ast.Name(id=varName, ctx=ast.Del())])
	def finishMe(self):
		astCmds = []
		for varName in self.varNames:
			astCmds += [self._astForDeleteVar(varName)]
			self.funcEnv._unregisterVar(varName)
		self.varNames.clear()
		self.body.extend(astCmds)

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
		b = Helpers.copy(a)
		a.value += 1
		return b
	
	@staticmethod
	def postfixDec(a):
		b = Helpers.copy(a)
		a.value -= 1
		return b
	
	@staticmethod
	def prefixIncPtr(a):
		aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
		aPtr.contents.value += ctypes.sizeof(a._type_)
		return a

	@staticmethod
	def prefixDecPtr(a):
		aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
		aPtr.contents.value -= ctypes.sizeof(a._type_)
		return a
	
	@staticmethod
	def postfixIncPtr(a):
		b = Helpers.copy(a)
		aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
		aPtr.contents.value += ctypes.sizeof(a._type_)
		return b

	@staticmethod
	def postfixDecPtr(a):
		b = Helpers.copy(a)
		aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
		aPtr.contents.value -= ctypes.sizeof(a._type_)
		return b

	@staticmethod
	def copy(a):
		if isinstance(a, _ctypes._SimpleCData):
			c = a.__class__()
			ctypes.pointer(c)[0] = a
			return c
		if isinstance(a, _ctypes._Pointer):
			return ctypes.cast(a, a.__class__)
		assert False, "cannot copy " + str(a)
	
	@staticmethod
	def assign(a, bValue):
		a.value = bValue
		return a
	
	@staticmethod
	def assignPtr(a, bValue):
		aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
		aPtr.contents.value = bValue
		return a

	@staticmethod
	def augAssign(a, op, bValue):
		a.value = OpBinFuncs[op](a.value, bValue)
		return a

	@staticmethod
	def augAssignPtr(a, op, bValue):
		assert op in ("+","-")
		op = OpBin[op]
		bValue *= ctypes.sizeof(a._type_)
		aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
		aPtr.contents.value = OpBinFuncs[op](aPtr.contents.value, bValue)
		return a

	@staticmethod
	def ptrArithmetic(a, op, bValue):
		return Helpers.augAssignPtr(Helpers.copy(a), op, bValue)

def astForHelperFunc(helperFuncName, *astArgs):
	helperFuncAst = getAstNodeAttrib("helpers", helperFuncName)
	a = ast.Call(keywords=[], starargs=None, kwargs=None)
	a.func = helperFuncAst
	a.args = list(astArgs)
	return a

def getAstNodeArrayIndex(base, index, ctx=ast.Load()):
	a = ast.Subscript(ctx=ctx)
	if isinstance(base, (str,unicode)):
		base = ast.Name(id=base, ctx=ctx)
	elif isinstance(base, ast.AST):
		pass # ok
	else:
		assert False, "base " + str(base) + " has invalid type"
	if isinstance(index, ast.AST):
		pass # ok
	elif isinstance(index, (int,long)):
		index = ast.Num(index)
	else:
		assert False, "index " + str(index) + " has invalid type"
	a.value = base
	a.slice = ast.Index(value=index)
	return a

def getAstForWrapValue(interpreter, wrapValue):
	interpreter.wrappedValuesDict[id(wrapValue)] = wrapValue
	v = getAstNodeArrayIndex("values", id(wrapValue))
	return v

def astAndTypeForStatement(funcEnv, stmnt):
	if isinstance(stmnt, (CVarDecl,CFuncArgDecl)):
		return funcEnv.getAstNodeForVarDecl(stmnt), stmnt.type
	elif isinstance(stmnt, CStatement):
		return astAndTypeForCStatement(funcEnv, stmnt)
	elif isinstance(stmnt, CAttribAccessRef):
		assert stmnt.name is not None
		a = ast.Attribute(ctx=ast.Load())
		a.value, t = astAndTypeForStatement(funcEnv, stmnt.base)
		a.attr = stmnt.name
		while isinstance(t, CTypedefType):
			t = funcEnv.globalScope.stateStruct.typedefs[t.name]
		assert isinstance(t, (CStruct,CUnion))
		attrDecl = t.findAttrib(funcEnv.globalScope.stateStruct, a.attr)
		assert attrDecl is not None, "attrib " + str(a.attr) + " not found"
		return a, attrDecl.type
	elif isinstance(stmnt, CPtrAccessRef):
		# build equivalent AttribAccess statement
		derefStmnt = CStatement()
		derefStmnt._op = COp("*")
		derefStmnt._rightexpr = stmnt.base
		attrStmnt = CAttribAccessRef()
		attrStmnt.base = derefStmnt
		attrStmnt.name = stmnt.name
		return astAndTypeForStatement(funcEnv, attrStmnt)		
	elif isinstance(stmnt, CNumber):
		t = minCIntTypeForNums(stmnt.content, useUnsignedTypes=False)
		if t is None: t = "int64_t" # it's an overflow; just take a big type
		t = CStdIntType(t)
		return getAstNode_newTypeInstance(funcEnv.interpreter, t, ast.Num(n=stmnt.content)), t
	elif isinstance(stmnt, CStr):
		t = CPointerType(ctypes.c_byte)
		v = makeAstNodeCall(getAstNodeAttrib("ctypes", "c_char_p"), ast.Str(s=str(stmnt.content)))
		return getAstNode_newTypeInstance(funcEnv.interpreter, t, v, t), t
	elif isinstance(stmnt, CChar):
		return makeAstNodeCall(getAstNodeAttrib("ctypes", "c_byte"), ast.Num(ord(str(stmnt.content)))), ctypes.c_byte
	elif isinstance(stmnt, CFuncCall):
		if isinstance(stmnt.base, CFunc):
			assert stmnt.base.name is not None
			a = ast.Call(keywords=[], starargs=None, kwargs=None)
			a.func = getAstNodeAttrib("g", stmnt.base.name)
			a.args = map(lambda arg: astAndTypeForStatement(funcEnv, arg)[0], stmnt.args)
			return a, stmnt.base.type
		elif isinstance(stmnt.base, CSizeofSymbol):
			assert len(stmnt.args) == 1
			t = getCType(stmnt.args[0], funcEnv.globalScope.stateStruct)
			assert t is not None
			s = ctypes.sizeof(t)
			return ast.Num(s), ctypes.c_size_t
		elif isinstance(stmnt.base, CStatement) and stmnt.base.isCType():
			# C static cast
			assert len(stmnt.args) == 1
			bAst, bType = astAndTypeForStatement(funcEnv, stmnt.args[0])
			bValueAst = getAstNode_valueFromObj(bAst, bType)
			aType = stmnt.base.asType()
			aTypeAst = getAstNodeForVarType(funcEnv.globalScope.interpreter, aType)

			if isPointerType(aType):
				astVoidPT = getAstNodeAttrib("ctypes", "c_void_p")
				astCast = getAstNodeAttrib("ctypes", "cast")
				astVoidP = makeAstNodeCall(astVoidPT, bValueAst)
				return makeAstNodeCall(astCast, astVoidP, aTypeAst), aType
			else:
				return makeAstNodeCall(aTypeAst, bValueAst), aType
		elif isinstance(stmnt.base, CWrapValue):
			# expect that we just wrapped a callable function/object
			a = ast.Call(keywords=[], starargs=None, kwargs=None)
			a.func = getAstNodeAttrib(getAstForWrapValue(funcEnv.globalScope.interpreter, stmnt.base), "value")
			a.args = map(lambda arg: astAndTypeForStatement(funcEnv, arg)[0], stmnt.args)
			return a, stmnt.base.returnType
		else:
			assert False, "cannot handle " + str(stmnt.base) + " call"
	elif isinstance(stmnt, CArrayIndexRef):
		aAst, aType = astAndTypeForStatement(funcEnv, stmnt.base)
		assert isinstance(aType, CPointerType)
		assert len(stmnt.args) == 1
		# kind of a hack: create equivalent ptr arithmetic expression
		ptrStmnt = CStatement()
		ptrStmnt._leftexpr = stmnt.base
		ptrStmnt._op = COp("+")
		ptrStmnt._rightexpr = stmnt.args[0]
		derefStmnt = CStatement()
		derefStmnt._op = COp("*")
		derefStmnt._rightexpr = ptrStmnt
		return astAndTypeForCStatement(funcEnv, derefStmnt)
		# TODO: support for real arrays.
		# the following code may be useful
		#bAst, bType = astAndTypeForStatement(funcEnv, stmnt.args[0])
		#bValueAst = getAstNode_valueFromObj(bAst, bType)
		#return getAstNodeArrayIndex(aAst, bValueAst), aType.pointerOf
	elif isinstance(stmnt, CWrapValue):
		v = getAstForWrapValue(funcEnv.globalScope.interpreter, stmnt)
		return getAstNodeAttrib(v, "value"), stmnt.getCType()
	else:
		assert False, "cannot handle " + str(stmnt)

def getAstNode_assign(aAst, aType, bAst, bType):
	bValueAst = getAstNode_valueFromObj(bAst, bType)
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.assignPtr, aAst, bValueAst)
	return makeAstNodeCall(Helpers.assign, aAst, bValueAst)

def getAstNode_augAssign(aAst, aType, opStr, bAst, bType):
	opAst = ast.Str(opStr)
	bValueAst = getAstNode_valueFromObj(bAst, bType)
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.augAssignPtr, aAst, opAst, bValueAst)
	return makeAstNodeCall(Helpers.augAssign, aAst, opAst, bValueAst)

def getAstNode_prefixInc(aAst, aType):
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.prefixIncPtr, aAst)
	return makeAstNodeCall(Helpers.prefixInc, aAst)

def getAstNode_prefixDec(aAst, aType):
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.prefixDecPtr, aAst)
	return makeAstNodeCall(Helpers.prefixDec, aAst)

def getAstNode_postfixInc(aAst, aType):
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.postfixIncPtr, aAst)
	return makeAstNodeCall(Helpers.postfixInc, aAst)

def getAstNode_postfixDec(aAst, aType):
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.postfixDecPtr, aAst)
	return makeAstNodeCall(Helpers.postfixDec, aAst)

def getAstNode_ptrBinOpExpr(stateStruct, aAst, aType, opStr, bAst, bType):
	assert isPointerType(aType)
	opAst = ast.Str(opStr)
	bValueAst = getAstNode_valueFromObj(bAst, bType)
	return makeAstNodeCall(Helpers.ptrArithmetic, aAst, opAst, bValueAst)
	
def astAndTypeForCStatement(funcEnv, stmnt):
	assert isinstance(stmnt, CStatement)
	if stmnt._leftexpr is None: # prefixed only
		rightAstNode,rightType = astAndTypeForStatement(funcEnv, stmnt._rightexpr)
		if stmnt._op.content == "++":
			return getAstNode_prefixInc(rightAstNode, rightType), rightType
		elif stmnt._op.content == "--":
			return getAstNode_prefixDec(rightAstNode, rightType), rightType
		elif stmnt._op.content == "*":
			assert isinstance(rightType, CPointerType)
			return getAstNodeAttrib(rightAstNode, "contents"), rightType.pointerOf
		elif stmnt._op.content == "&":
			return makeAstNodeCall(getAstNodeAttrib("ctypes", "pointer"), rightAstNode), CPointerType(rightType)
		elif stmnt._op.content in OpUnary:
			a = ast.UnaryOp()
			a.op = OpUnary[stmnt._op.content]()
			if isPointerType(rightType):
				assert stmnt._op.content == "!", "the only supported unary op for ptr types is '!'"
				a.operand = makeAstNodeCall(
					ast.Name(id="bool", ctx=ast.Load()),
					rightAstNode)
				rightType = ctypes.c_int
			else:
				a.operand = getAstNode_valueFromObj(rightAstNode, rightType)
			return getAstNode_newTypeInstance(funcEnv.interpreter, rightType, a), rightType
		else:
			assert False, "unary prefix op " + str(stmnt._op) + " is unknown"
	if stmnt._op is None:
		return astAndTypeForStatement(funcEnv, stmnt._leftexpr)
	if stmnt._rightexpr is None:
		leftAstNode, leftType = astAndTypeForStatement(funcEnv, stmnt._leftexpr)
		if stmnt._op.content == "++":
			return getAstNode_postfixInc(leftAstNode, leftType), leftType
		elif stmnt._op.content == "--":
			return getAstNode_postfixDec(leftAstNode, leftType), leftType
		else:
			assert False, "unary postfix op " + str(stmnt._op) + " is unknown"
	leftAstNode, leftType = astAndTypeForStatement(funcEnv, stmnt._leftexpr)
	rightAstNode, rightType = astAndTypeForStatement(funcEnv, stmnt._rightexpr)
	if stmnt._op.content == "=":
		return getAstNode_assign(leftAstNode, leftType, rightAstNode, rightType), leftType
	elif stmnt._op.content in OpAugAssign:
		return getAstNode_augAssign(leftAstNode, leftType, stmnt._op.content, rightAstNode, rightType), leftType
	elif stmnt._op.content in OpBinBool:
		a = ast.BoolOp()
		a.op = OpBinBool[stmnt._op.content]()
		a.values = [
			getAstNode_valueFromObj(leftAstNode, leftType),
			getAstNode_valueFromObj(rightAstNode, rightType)]
		return getAstNode_newTypeInstance(funcEnv.interpreter, ctypes.c_int, a), ctypes.c_int
	elif stmnt._op.content in OpBinCmp:
		a = ast.Compare()
		a.ops = [OpBinCmp[stmnt._op.content]()]
		a.left = getAstNode_valueFromObj(leftAstNode, leftType)
		a.comparators = [getAstNode_valueFromObj(rightAstNode, rightType)]
		return getAstNode_newTypeInstance(funcEnv.interpreter, ctypes.c_int, a), ctypes.c_int
	elif stmnt._op.content == "?:":
		middleAstNode, middleType = astAndTypeForStatement(funcEnv, stmnt._middleexpr)
		a = ast.IfExp()
		a.test = getAstNode_valueFromObj(leftAstNode, leftType)
		a.body = middleAstNode
		a.orelse = rightAstNode
		# TODO: we take the type from middleType right now. not really correct...
		# So, cast the orelse part.
		a.orelse = getAstNode_newTypeInstance(funcEnv.interpreter, middleType, a.orelse, rightType)
		return a, middleType
	elif isPointerType(leftType):
		return getAstNode_ptrBinOpExpr(
			funcEnv.globalScope.stateStruct,
			leftAstNode, leftType,
			stmnt._op.content,
			rightAstNode, rightType), leftType
	elif stmnt._op.content in OpBin:
		a = ast.BinOp()
		a.op = OpBin[stmnt._op.content]()
		a.left = getAstNode_valueFromObj(leftAstNode, leftType)
		a.right = getAstNode_valueFromObj(rightAstNode, rightType)		
		return getAstNode_newTypeInstance(funcEnv.interpreter, leftType, a), leftType # TODO: not really correct. e.g. int + float -> float
	else:
		assert False, "binary op " + str(stmnt._op) + " is unknown"

PyAstNoOp = ast.Assert(test=ast.Name(id="True", ctx=ast.Load()), msg=None)

def astForCWhile(funcEnv, stmnt):
	assert isinstance(stmnt, CWhileStatement)
	assert stmnt.body is not None
	assert len(stmnt.args) == 1
	assert isinstance(stmnt.args[0], CStatement)
	whileAst = ast.While(body=[], orelse=[])
	whileAst.test = getAstNode_valueFromObj(*astAndTypeForCStatement(funcEnv, stmnt.args[0]))
	funcEnv.pushScope(whileAst.body)
	cCodeToPyAstList(funcEnv, stmnt.body)
	if not whileAst.body: whileAst.body.append(ast.Pass())
	funcEnv.popScope()
	return whileAst

def astForCFor(funcEnv, stmnt):
	# TODO
	return PyAstNoOp

def astForCDoWhile(funcEnv, stmnt):
	# TODO
	return PyAstNoOp

def astForCIf(funcEnv, stmnt):
	assert isinstance(stmnt, CIfStatement)
	assert stmnt.body is not None
	assert len(stmnt.args) == 1
	assert isinstance(stmnt.args[0], CStatement)

	ifAst = ast.If(body=[], orelse=[])
	ifAst.test = getAstNode_valueFromObj(*astAndTypeForCStatement(funcEnv, stmnt.args[0]))
	funcEnv.pushScope(ifAst.body)
	cCodeToPyAstList(funcEnv, stmnt.body)
	if not ifAst.body: ifAst.body.append(ast.Pass())
	funcEnv.popScope()
	
	if stmnt.elsePart is not None:
		assert stmnt.elsePart.body is not None
		funcEnv.pushScope(ifAst.orelse)
		cCodeToPyAstList(funcEnv, stmnt.elsePart.body)
		if not ifAst.orelse: ifAst.orelse.append(ast.Pass())
		funcEnv.popScope()

	return ifAst

def astForCSwitch(funcEnv, stmnt):
	assert isinstance(stmnt, CSwitchStatement)
	assert isinstance(stmnt.body, CBody)
	assert len(stmnt.args) == 1
	assert isinstance(stmnt.args[0], CStatement)

	# introduce dummy 'if' AST so that we can return a single AST node
	ifAst = ast.If(body=[], orelse=[], test=ast.Name(id="True", ctx=ast.Load()))
	funcEnv.pushScope(ifAst.body)

	switchVarName = funcEnv.registerNewVar("_switchvalue")	
	switchValueAst, switchValueType = astAndTypeForCStatement(funcEnv, stmnt.args[0])
	a = ast.Assign()
	a.targets = [ast.Name(id=switchVarName, ctx=ast.Store())]
	a.value = getAstNode_valueFromObj(switchValueAst, switchValueType)
	funcEnv.getBody().append(a)
	
	fallthroughVarName = funcEnv.registerNewVar("_switchfallthrough")
	a = ast.Assign()
	a.targets = [ast.Name(id=fallthroughVarName, ctx=ast.Store())]
	a.value = ast.Name(id="False", ctx=ast.Load())
	fallthroughVarAst = ast.Name(id=fallthroughVarName, ctx=ast.Load())
	funcEnv.getBody().append(a)

	# use 'while' AST so that we can just use 'break' as intended
	whileAst = ast.While(body=[], orelse=[], test=ast.Name(id="True", ctx=ast.Load()))
	funcEnv.getBody().append(whileAst)	
	funcEnv.pushScope(whileAst.body)
	
	curCase = None
	for c in stmnt.body.contentlist:
		if isinstance(c, CCaseStatement):
			if curCase is not None: funcEnv.popScope()
			assert len(c.args) == 1
			curCase = ast.If(body=[], orelse=[])
			curCase.test = ast.BoolOp(op=ast.Or(), values=[
				fallthroughVarAst,
				ast.Compare(
					left=ast.Name(id=switchVarName, ctx=ast.Load()),
					ops=[ast.Eq()],
					comparators=[getAstNode_valueFromObj(*astAndTypeForCStatement(funcEnv, c.args[0]))]
					)
				])
			funcEnv.getBody().append(curCase)
			funcEnv.pushScope(curCase.body)
			a = ast.Assign()
			a.targets = [ast.Name(id=fallthroughVarName, ctx=ast.Store())]
			a.value = ast.Name(id="True", ctx=ast.Load())
			funcEnv.getBody().append(a)
			
		elif isinstance(c, CCaseDefaultStatement):
			if curCase is not None: funcEnv.popScope()
			curCase = ast.If(body=[], orelse=[])
			curCase.test = ast.UnaryOp(op=ast.Not(), operand=fallthroughVarAst)
			funcEnv.getBody().append(curCase)
			funcEnv.pushScope(curCase.body)

		else:
			assert curCase is not None
			cStatementToPyAst(funcEnv, c)
	if curCase is not None: funcEnv.popScope()
	
	# finish 'while'
	funcEnv.getBody().append(ast.Break())
	funcEnv.popScope()
	
	# finish 'if'
	funcEnv.popScope()
	return ifAst

def astForCReturn(funcEnv, stmnt):
	assert isinstance(stmnt, CReturnStatement)
	if not stmnt.body:
		assert isSameType(funcEnv.globalScope.stateStruct, funcEnv.func.type, CVoidType())
		return ast.Return(value=None)
	assert isinstance(stmnt.body, CStatement)
	valueAst = getAstNode_valueFromObj(*astAndTypeForCStatement(funcEnv, stmnt.body))
	returnTypeAst = getAstNodeForVarType(funcEnv.globalScope.interpreter, funcEnv.func.type)
	returnValueAst = makeAstNodeCall(returnTypeAst, valueAst)
	return ast.Return(value=returnValueAst)

def cStatementToPyAst(funcEnv, c):
	body = funcEnv.getBody()
	if isinstance(c, (CVarDecl,CFunc)):
		funcEnv.registerNewVar(c.name, c)
	elif isinstance(c, CStatement):
		a, t = astAndTypeForCStatement(funcEnv, c)
		if isinstance(a, ast.expr):
			a = ast.Expr(value=a)
		body.append(a)
	elif isinstance(c, CWhileStatement):
		body.append(astForCWhile(funcEnv, c))
	elif isinstance(c, CForStatement):
		body.append(astForCFor(funcEnv, c))
	elif isinstance(c, CDoStatement):
		body.append(astForCDoWhile(funcEnv, c))
	elif isinstance(c, CIfStatement):
		body.append(astForCIf(funcEnv, c))
	elif isinstance(c, CSwitchStatement):
		body.append(astForCSwitch(funcEnv, c))
	elif isinstance(c, CReturnStatement):
		body.append(astForCReturn(funcEnv, c))
	elif isinstance(c, CBreakStatement):
		body.append(ast.Break())
	elif isinstance(c, CContinueStatement):
		body.append(ast.Continue())
	elif isinstance(c, CCodeBlock):
		funcEnv.pushScope(body)
		cCodeToPyAstList(funcEnv, c.body)
		funcEnv.popScope()
	else:
		assert False, "cannot handle " + str(c)

def cCodeToPyAstList(funcEnv, cBody):
	if isinstance(cBody, CBody):
		for c in cBody.contentlist:
			cStatementToPyAst(funcEnv, c)
	else:
		cStatementToPyAst(funcEnv, cBody)
		
class Interpreter:
	def __init__(self):
		self.stateStructs = []
		self._cStateWrapper = CStateWrapper(self)
		self._cStateWrapper.IndirectSimpleCTypes = True
		self._cStateWrapper.error = self._cStateWrapperError
		self.globalScope = GlobalScope(self, self._cStateWrapper)
		self._func_cache = {}
		self.globalsWrapper = GlobalsWrapper(self.globalScope)
		self.globalsStructWrapper = GlobalsStructWrapper(self.globalScope)
		self.wrappedValuesDict = {} # id(obj) -> obj
		self.globalsDict = {
			"ctypes": ctypes,
			"helpers": Helpers,
			"g": self.globalsWrapper,
			"structs": self.globalsStructWrapper,
			"values": self.wrappedValuesDict,
			"intp": self
			}
	
	def _cStateWrapperError(self, s):
		print "Error:", s
		
	def register(self, stateStruct):
		self.stateStructs += [stateStruct]
	
	def registerFinalize(self):
		self.globalScope.registerExterns()
	
	def getCType(self, obj):
		wrappedStateStruct = self._cStateWrapper
		for T,DictName in [(CStruct,"structs"), (CUnion,"unions"), (CEnum,"enums")]:
			if isinstance(obj, T):
				if obj.name is not None:
					return getattr(wrappedStateStruct, DictName)[obj.name].getCValue(wrappedStateStruct)
				else:
					return obj.getCValue(wrappedStateStruct)
		return obj.getCValue(wrappedStateStruct)
	
	def _translateFuncToPyAst(self, func):
		assert isinstance(func, CFunc)
		base = FuncEnv(globalScope=self.globalScope)
		assert func.name is not None
		base.func = func
		base.astNode.name = func.name
		base.pushScope(base.astNode.body)
		for arg in func.args:
			name = base.registerNewVar(arg.name, arg)
			assert name is not None
			base.astNode.args.args.append(ast.Name(id=name, ctx=ast.Param()))
		if func.body is None:
			# TODO: search in other C files
			# Hack for now: ignore :)
			print "XXX:", func.name, "is not loaded yet"
		else:
			cCodeToPyAstList(base, func.body)
		base.popScope()
		if isSameType(self._cStateWrapper, func.type, CVoidType()):
			returnValueAst = NoneAstNode
		else:
			returnTypeAst = getAstNodeForVarType(self, func.type)
			returnValueAst = makeAstNodeCall(returnTypeAst)
		base.astNode.body.append(ast.Return(value=returnValueAst))
		return base

	@staticmethod
	def _unparse(pyAst):
		from cStringIO import StringIO
		output = StringIO()
		from py_demo_unparse import Unparser
		Unparser(pyAst, output)
		output.write("\n")
		return output.getvalue()

	def _compile(self, pyAst):
		# We unparse + parse again for now for better debugging (so we get some code in a backtrace).
		def _set_linecache(filename, source):
			import linecache
			linecache.cache[filename] = None, None, [line+'\n' for line in source.splitlines()], filename
		SRC_FILENAME = "<PyCParser_" + pyAst.name + ">"
		def _unparseAndParse(pyAst):
			src = self._unparse(pyAst)
			_set_linecache(SRC_FILENAME, src)
			return compile(src, SRC_FILENAME, "single")
		def _justCompile(pyAst):
			exprAst = ast.Interactive(body=[pyAst])		
			ast.fix_missing_locations(exprAst)
			return compile(exprAst, SRC_FILENAME, "single")
		return _unparseAndParse(pyAst)
	
	def _translateFuncToPy(self, funcname):
		cfunc = self._cStateWrapper.funcs[funcname]
		funcEnv = self._translateFuncToPyAst(cfunc)
		pyAst = funcEnv.astNode
		compiled = self._compile(pyAst)
		d = {}
		exec compiled in self.globalsDict, d
		func = d[funcname]
		func.C_cFunc = cfunc
		func.C_pyAst = pyAst
		func.C_interpreter = self
		func.C_argTypes = map(lambda a: a.type, cfunc.args)
		func.C_unparse = lambda: self._unparse(pyAst)
		return func

	def getFunc(self, funcname):
		if funcname in self._func_cache:
			return self._func_cache[funcname]
		else:
			func = self._translateFuncToPy(funcname)
			self._func_cache[funcname] = func
			return func
	
	def dumpFunc(self, funcname, output=sys.stdout):
		f = self.getFunc(funcname)
		print >>output, f.C_unparse()
	
	def _castArgToCType(self, arg, typ):
		if isinstance(typ, CPointerType):
			ctyp = getCType(typ, self._cStateWrapper)
			if arg is None:
				return ctyp()
			elif isinstance(arg, (str,unicode)):
				return ctypes.cast(ctypes.c_char_p(arg), ctyp)
			assert isinstance(arg, (list,tuple))
			o = (ctyp._type_ * (len(arg) + 1))()
			for i in xrange(len(arg)):
				o[i] = self._castArgToCType(arg[i], typ.pointerOf)
			op = ctypes.pointer(o)
			op = ctypes.cast(op, ctyp)
			# TODO: what when 'o' goes out of scope and freed?
			return op
		elif isinstance(arg, (int,long)):
			t = minCIntTypeForNums(arg)
			if t is None: t = "int64_t" # it's an overflow; just take a big type
			return self._cStateWrapper.StdIntTypes[t](arg)			
		else:
			assert False, "cannot cast " + str(arg) + " to " + str(typ)
	
	def runFunc(self, funcname, *args):
		f = self.getFunc(funcname)
		assert len(args) == len(f.C_argTypes)
		args = map(lambda (arg,typ): self._castArgToCType(arg,typ), zip(args,f.C_argTypes))
		return f(*args)
