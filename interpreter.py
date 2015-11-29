# PyCParser - interpreter
# by Albert Zeyer, 2011
# code under LGPL

from cparser import *
from cwrapper import CStateWrapper

import ctypes
import _ctypes
import ast
import sys
import inspect
import goto

class CWrapValue(CType):
	def __init__(self, value, decl=None, name=None, **kwattr):
		if isinstance(value, int):
			value = ctypes.c_int(value)
		self.value = value
		self.decl = decl
		self.name = name
		for k,v in kwattr.iteritems():
			setattr(self, k, v)
	def __repr__(self):
		s = "<" + self.__class__.__name__ + " "
		if self.name: s += "%r " % self.name
		if self.decl is not None: s += repr(self.decl) + " "
		s += repr(self.value)
		s += ">"
		return s
	def getType(self):
		if self.decl is not None: return self.decl.type
		#elif self.value is not None and hasattr(self.value, "__class__"):
			#for k, v in State.CBuiltinTypes  # TODO...
		#	return self.value.__class__
			#if isinstance(self.value, (_ctypes._SimpleCData,ctypes.Structure,ctypes.Union)):
		return self	
	def getCType(self, stateStruct):
		return self.value.__class__
	def getConstValue(self, stateStruct):
		value = self.value
		if isinstance(value, _ctypes._Pointer):
			value = ctypes.cast(value, ctypes.c_void_p)
		if isinstance(value, ctypes._SimpleCData):
			value = value.value
		return value

class CWrapFuncType(CType):
	def __init__(self, func):
		"""
		:type func: CFunc
		"""
		self.func = func
	def getCType(self, stateStruct):
		assert False


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
	
	def getVar(self, name):
		if name in self.vars: return self.vars[name]
		decl = self.findIdentifier(name)
		assert isinstance(decl, CVarDecl)
		if decl.body is not None:
			anonFuncEnv = FuncEnv(self)
			bodyAst, t = astAndTypeForStatement(anonFuncEnv, decl.body)
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
		"""
		:type globalScope: GlobalScope
		"""
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
		elif isinstance(decl, CFuncPointerDecl):
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
		self.needGotoHandling = False
		self.astNode = ast.FunctionDef(
			args=ast.arguments(args=[], vararg=None, kwarg=None, defaults=[]),
			body=[], decorator_list=[])
	def __repr__(self):
		try: return "<" + self.__class__.__name__ + " of " + self.astNode.name + ">"
		except: return "<" + self.__class__.__name__ + " in invalid state>"			
	def _registerNewVar(self, varName, varDecl):
		if varDecl is not None:
			assert id(varDecl) not in self.varNames
		for name in iterIdWithPostfixes(varName):
			if not isValidVarName(name): continue
			if self.searchVarName(name): continue
			self.vars[name] = varDecl
			if varDecl is not None:
				self.varNames[id(varDecl)] = name
			return name
	def searchVarName(self, varName):
		if varName in self.vars: return True
		return self.globalScope.findIdentifier(varName) is not None
	def registerNewVar(self, varName, varDecl=None):
		return self.scopeStack[-1].registerNewVar(varName, varDecl)
	def registerNewUnscopedVarName(self, varName):
		return self._registerNewVar(varName, None)
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

class DidNotFindCTypesBasicType(Exception): pass

def getAstNodeForCTypesBasicType(t):
	if t is None: return NoneAstNode
	if t is CVoidType: return NoneAstNode
	if not inspect.isclass(t) and isinstance(t, CVoidType): return NoneAstNode
	if inspect.isclass(t) and issubclass(t, CVoidType): return None
	if not inspect.isclass(t): raise DidNotFindCTypesBasicType("not a class")
	if issubclass(t, ctypes._Pointer):
		base_type = t._type_
		a = getAstNodeAttrib("ctypes", "POINTER")
		return makeAstNodeCall(a, getAstNodeForCTypesBasicType(base_type))
	if not issubclass(t, ctypes._SimpleCData): raise DidNotFindCTypesBasicType("unknown type")
	assert issubclass(t, getattr(ctypes, t.__name__))
	return getAstNodeAttrib("ctypes", t.__name__)

def getAstNodeForVarType(interpreter, t):
	if isinstance(t, CBuiltinType):
		return getAstNodeForCTypesBasicType(State.CBuiltinTypes[t.builtinType])
	elif isinstance(t, CStdIntType):
		return getAstNodeForCTypesBasicType(State.StdIntTypes[t.name])
	elif isinstance(t, CPointerType):
		a = getAstNodeAttrib("ctypes", "POINTER")
		return makeAstNodeCall(a, getAstNodeForVarType(interpreter, t.pointerOf))
	elif isinstance(t, CTypedef):
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
	elif isinstance(t, CArrayType):
		arrayOf = getAstNodeForVarType(interpreter, t.arrayOf)
		arrayLen = ast.Num(n=getConstValue(interpreter.globalScope.stateStruct, t.arrayLen))
		return ast.BinOp(left=arrayOf, op=ast.Mult(), right=arrayLen)
	elif isinstance(t, CWrapValue):
		return getAstNodeForVarType(interpreter, t.getCType(None))
	else:
		try: return getAstNodeForCTypesBasicType(t)
		except DidNotFindCTypesBasicType: pass
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

def isPointerType(t, checkWrapValue=False):
	if isinstance(t, CPointerType): return True
	if isinstance(t, CArrayType): return True
	if isinstance(t, CFuncPointerDecl): return True
	if checkWrapValue and isinstance(t, CWrapValue):
		return isPointerType(t.getCType(None), checkWrapValue=True)
	from inspect import isclass
	if isclass(t):
		if issubclass(t, _ctypes._Pointer): return True
		if issubclass(t, ctypes.c_void_p): return True
	return False

def isValueType(t):
	if isinstance(t, (CBuiltinType,CStdIntType)): return True
	from inspect import isclass
	if isclass(t):
		for c in State.StdIntTypes.values():
			if issubclass(t, c): return True
	return False

def getAstNode_valueFromObj(stateStruct, objAst, objType):
	if isPointerType(objType):
		from inspect import isclass
		if not isclass(objType) or not issubclass(objType, ctypes.c_void_p):
			astVoidPT = getAstNodeAttrib("ctypes", "c_void_p")
			astCast = getAstNodeAttrib("ctypes", "cast")
			astVoidP = makeAstNodeCall(astCast, objAst, astVoidPT)
		else:
			astVoidP = objAst
		astValue = getAstNodeAttrib(astVoidP, "value")
		return ast.BoolOp(op=ast.Or(), values=[astValue, ast.Num(0)])
	elif isValueType(objType):
		astValue = getAstNodeAttrib(objAst, "value")
		return astValue
	elif isinstance(objType, CArrayType):
		# cast array to ptr
		astVoidPT = getAstNodeAttrib("ctypes", "c_void_p")
		astCast = getAstNodeAttrib("ctypes", "cast")
		castToPtr = makeAstNodeCall(astCast, objAst, astVoidPT)
		astValue = getAstNodeAttrib(castToPtr, "value")
		return ast.BoolOp(op=ast.Or(), values=[astValue, ast.Num(0)])
	elif isinstance(objType, CTypedef):
		t = objType.type
		return getAstNode_valueFromObj(stateStruct, objAst, t)
	elif isinstance(objType, CWrapValue):
		# It's already the value. See astAndTypeForStatement().
		return getAstNode_valueFromObj(stateStruct, objAst, objType.getCType(stateStruct))
	elif isinstance(objType, CWrapFuncType):
		# It's already the value. See astAndTypeForStatement().
		return objAst
	else:
		assert False, "bad type: " + str(objType)
		
def getAstNode_newTypeInstance(interpreter, objType, argAst=None, argType=None):
	"""
	Create a new instance of type `objType`.
	It can optionally be initialized with `argAst` (already AST) which is of type `argType`.
	If `argType` is None, `argAst` is supposed to be a value (e.g. via getAstNode_valueFromObj).
	"""
	if isinstance(argType, (tuple, list)):  # CCurlyArrayArgs
		# Handle array type extra here for the case when array-len is not specified.
		arrayOf, arrayLen = None, None
		if isinstance(objType, CArrayType):
			arrayOf = getAstNodeForVarType(interpreter, objType.arrayOf)
			if objType.arrayLen:
				arrayLen = getConstValue(interpreter.globalScope.stateStruct, objType.arrayLen)
				assert arrayLen == len(argType)
			else:
				arrayLen = len(argType)
			typeAst = ast.BinOp(left=arrayOf, op=ast.Mult(), right=ast.Num(n=arrayLen))
		else:
			typeAst = getAstNodeForVarType(interpreter, objType)

		assert isinstance(argAst, ast.Tuple)
		assert len(argAst.elts) == len(argType)
		args = [getAstNode_valueFromObj(interpreter._cStateWrapper, a[0], a[1])
				for a in zip(argAst.elts, argType)]
		return makeAstNodeCall(typeAst, *args)

	typeAst = getAstNodeForVarType(interpreter, objType)

	if isPointerType(objType, checkWrapValue=True) and isPointerType(argType, checkWrapValue=True):
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
			args += [getAstNode_valueFromObj(interpreter._cStateWrapper, argAst, argType)]
		else:
			# expect that it is the AST for the value.
			# there is no really way to 'assert' this.
			args += [argAst]

	if isPointerType(objType, checkWrapValue=True) and argAst is not None:
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
				v = getConstValue(self.funcEnv.globalScope.stateStruct, varDecl.body)
				if v is not None and not v:
					bodyAst = t = None
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

OpBinFuncsByOp = dict(map(lambda op: (op, _astOpToFunc(op)), OpBin.itervalues()))

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
		if isinstance(a, _ctypes.Array):
			return ctypes.cast(a, ctypes.POINTER(a._type_))
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
		aPtr.contents.value = OpBinFuncsByOp[op](aPtr.contents.value, bValue)
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
	assert isinstance(wrapValue, CWrapValue)
	orig_name = wrapValue.name or "anonymous_value"
	for name in iterIdWithPostfixes(orig_name):
		if not isValidVarName(name): continue
		obj = getattr(interpreter.wrappedValues, name, None)
		if obj is None:  # new
			setattr(interpreter.wrappedValues, name, wrapValue)
			obj = wrapValue
		if obj is wrapValue:
			v = getAstNodeAttrib("values", name)
			return v

def astForCast(funcEnv, new_type, arg_ast):
	"""
	:type new_type: _CBaseWithOptBody or derived
	:param arg_ast: the value to be casted, already as an AST
	:return: ast (of type new_type)
	"""
	aType = new_type
	aTypeAst = getAstNodeForVarType(funcEnv.globalScope.interpreter, aType)
	bValueAst = arg_ast

	if isPointerType(aType):
		astVoidPT = getAstNodeAttrib("ctypes", "c_void_p")
		astCast = getAstNodeAttrib("ctypes", "cast")
		astVoidP = makeAstNodeCall(astVoidPT, bValueAst)
		return makeAstNodeCall(astCast, astVoidP, aTypeAst)
	else:
		return makeAstNodeCall(aTypeAst, bValueAst)


def autoCastArgs(funcEnv, required_arg_types, stmnt_args):
	if required_arg_types and isinstance(required_arg_types[-1], CVariadicArgsType):
		# CFunc will have CVariadicArgsType.
		# CWrapValue to native functions will not have any indication for variadic args,
		# even when it supports it.
		# Thus, just remove it any assume we support it.
		required_arg_types = required_arg_types[:-1]
	assert len(stmnt_args) >= len(required_arg_types)
	# variable num of args
	required_arg_types = required_arg_types + [None] * (len(stmnt_args) - len(required_arg_types))
	r_args = []
	for f_arg_type, s_arg in zip(required_arg_types, stmnt_args):
		s_arg_ast, s_arg_type = astAndTypeForStatement(funcEnv, s_arg)
		if f_arg_type is not None:
			f_arg_ctype = getCType(f_arg_type, funcEnv.globalScope.stateStruct)
			s_arg_ctype = getCType(s_arg_type, funcEnv.globalScope.stateStruct)
			if s_arg_ctype != f_arg_ctype:
				s_value_ast = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, s_arg_ast, s_arg_type)
				s_arg_ast = astForCast(funcEnv, f_arg_type, s_value_ast)
		r_args += [s_arg_ast]
	return r_args


def astAndTypeForStatement(funcEnv, stmnt):
	if isinstance(stmnt, (CVarDecl,CFuncArgDecl)):
		return funcEnv.getAstNodeForVarDecl(stmnt), stmnt.type
	elif isinstance(stmnt, CFunc):
		return funcEnv.getAstNodeForVarDecl(stmnt), CWrapFuncType(stmnt)
	elif isinstance(stmnt, CStatement):
		return astAndTypeForCStatement(funcEnv, stmnt)
	elif isinstance(stmnt, CAttribAccessRef):
		assert stmnt.name is not None
		a = ast.Attribute(ctx=ast.Load())
		a.value, t = astAndTypeForStatement(funcEnv, stmnt.base)
		a.attr = stmnt.name
		while isinstance(t, CTypedef):
			t = t.type
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
		return makeAstNodeCall(getAstNodeAttrib("ctypes", "c_byte"), ast.Num(stmnt.content)), ctypes.c_byte
	elif isinstance(stmnt, CFuncCall):
		if isinstance(stmnt.base, CFunc):
			assert stmnt.base.name is not None
			a = ast.Call(keywords=[], starargs=None, kwargs=None)
			a.func = getAstNodeAttrib("g", stmnt.base.name)
			a.args = autoCastArgs(funcEnv, [f_arg.type for f_arg in stmnt.base.args], stmnt.args)
			return a, stmnt.base.type
		elif isinstance(stmnt.base, CSizeofSymbol):
			assert len(stmnt.args) == 1
			a = stmnt.args[0]
			if isinstance(a, CStatement) and not a.isCType():
				v, _ = astAndTypeForStatement(funcEnv, stmnt.args[0])
				sizeValueAst = makeAstNodeCall(getAstNodeAttrib("ctypes", "sizeof"), v)
				sizeAst = makeAstNodeCall(getAstNodeAttrib("ctypes", "c_size_t"), sizeValueAst)
				return sizeAst, CStdIntType("size_t")
			# We expect that it is a type.
			t = getCType(stmnt.args[0], funcEnv.globalScope.stateStruct)
			assert t is not None
			s = ctypes.sizeof(t)
			return ast.Num(s), CStdIntType("size_t")
		elif isinstance(stmnt.base, CWrapValue):
			# expect that we just wrapped a callable function/object
			a = ast.Call(keywords=[], starargs=None, kwargs=None)
			a.func = getAstNodeAttrib(getAstForWrapValue(funcEnv.globalScope.interpreter, stmnt.base), "value")
			if isinstance(stmnt.base.value, ctypes._CFuncPtr):
				a.args = autoCastArgs(funcEnv, stmnt.base.value.argtypes, stmnt.args)
			else:  # e.g. custom lambda / Python func
				a.args = map(lambda arg: astAndTypeForStatement(funcEnv, arg)[0], stmnt.args)
			return a, stmnt.base.returnType
		elif isinstance(stmnt.base, (CType,CTypedef)) or (isinstance(stmnt.base, CStatement) and stmnt.base.isCType()):
			# C static cast
			assert len(stmnt.args) == 1
			if isinstance(stmnt.base, CStatement):
				aType = stmnt.base.asType()
			else:
				aType = stmnt.base
			bAst, bType = astAndTypeForStatement(funcEnv, stmnt.args[0])
			bValueAst = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, bAst, bType)
			if isinstance(aType, CBuiltinType) and aType.builtinType == ("void",):
				# A void cast will discard the output.
				return bAst, aType
			return astForCast(funcEnv, aType, bValueAst), aType
		elif isinstance(stmnt.base, CStatement):
			# func ptr call
			a = ast.Call(keywords=[], starargs=None, kwargs=None)
			pAst, pType = astAndTypeForStatement(funcEnv, stmnt.base)
			assert isinstance(pType, CFuncPointerDecl)
			a.func = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, pAst, pType)
			a.args = autoCastArgs(funcEnv, pType.args, stmnt.args)
			return a, pType.type
		else:
			assert False, "cannot handle " + str(stmnt.base) + " call"
	elif isinstance(stmnt, CArrayIndexRef):
		aAst, aType = astAndTypeForStatement(funcEnv, stmnt.base)
		if isinstance(aType, (CPointerType, CArrayType)):
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
		#elif isinstance(aType, CArrayType):
		#	assert len(stmnt.args) == 1
		#	indexAst, _ = astAndTypeForStatement(funcEnv, stmnt.args[0])
		#	return getAstNodeArrayIndex(aAst, indexAst), aType.arrayOf
		else:
			assert False, "invalid array access to type %r" % aType
		# the following code may be useful
		#bAst, bType = astAndTypeForStatement(funcEnv, stmnt.args[0])
		#bValueAst = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, bAst, bType)
		#return getAstNodeArrayIndex(aAst, bValueAst), aType.pointerOf
	elif isinstance(stmnt, CWrapValue):
		v = getAstForWrapValue(funcEnv.globalScope.interpreter, stmnt)
		# Keep in sync with getAstNode_valueFromObj().
		return getAstNodeAttrib(v, "value"), stmnt.getType()
	elif isinstance(stmnt, CCurlyArrayArgs):
		elts = [astAndTypeForStatement(funcEnv, s) for s in stmnt.args]
		a = ast.Tuple(elts=tuple([e[0] for e in elts]), ctx=ast.Load())
		return a, tuple([e[1] for e in elts])
	else:
		assert False, "cannot handle " + str(stmnt)

def getAstNode_assign(stateStruct, aAst, aType, bAst, bType):
	bValueAst = getAstNode_valueFromObj(stateStruct, bAst, bType)
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.assignPtr, aAst, bValueAst)
	return makeAstNodeCall(Helpers.assign, aAst, bValueAst)

def getAstNode_augAssign(stateStruct, aAst, aType, opStr, bAst, bType):
	opAst = ast.Str(opStr)
	bValueAst = getAstNode_valueFromObj(stateStruct, bAst, bType)
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
	bValueAst = getAstNode_valueFromObj(stateStruct, bAst, bType)
	return makeAstNodeCall(Helpers.ptrArithmetic, aAst, opAst, bValueAst)

def _resolveSingleStatement(stmnt):
	if not isinstance(stmnt, CStatement): return stmnt
	if stmnt._op is None and stmnt._rightexpr is None:
		return _resolveSingleStatement(stmnt._leftexpr)
	return stmnt

def _getZeroPtrTypeOrNone(stmnt):
	"""
	We expect sth like `(PyObject*) 0`, i.e. a C-style cast.
	In that case, we return the base type, i.e. `PyObject`,
	otherwise None.
	"""
	stmnt = _resolveSingleStatement(stmnt)
	if not isinstance(stmnt, CFuncCall): return
	base = stmnt.base
	if isinstance(base, CStatement):
		if not base.isCType(): return
		base = base.asType()
	if not isinstance(base, CPointerType): return
	assert len(stmnt.args) == 1
	arg = stmnt.args[0]
	assert isinstance(arg, CStatement)
	arg = _resolveSingleStatement(arg)
	if not isinstance(arg, CNumber): return
	if arg.content != 0: return
	return base.pointerOf

def _resolveOffsetOf(stateStruct, stmnt):
	if stmnt._leftexpr is not None: return
	if stmnt._op.content != "&": return
	rightexpr = _resolveSingleStatement(stmnt._rightexpr)
	if not isinstance(rightexpr, CPtrAccessRef): return
	zero_ptr_type = _getZeroPtrTypeOrNone(rightexpr.base)
	if zero_ptr_type is None: return
	c_type = getCType(zero_ptr_type, stateStruct)
	field = getattr(c_type, rightexpr.name)
	return field.offset

def astAndTypeForCStatement(funcEnv, stmnt):
	assert isinstance(stmnt, CStatement)
	if stmnt._leftexpr is None: # prefixed only
		rightAstNode,rightType = astAndTypeForStatement(funcEnv, stmnt._rightexpr)
		if stmnt._op.content == "++":
			return getAstNode_prefixInc(rightAstNode, rightType), rightType
		elif stmnt._op.content == "--":
			return getAstNode_prefixDec(rightAstNode, rightType), rightType
		elif stmnt._op.content == "*":
			while isinstance(rightType, CTypedef):
				rightType = rightType.type
			if isinstance(rightType, CPointerType):
				return getAstNodeAttrib(rightAstNode, "contents"), rightType.pointerOf
			elif isinstance(rightType, CFuncPointerDecl):
				return rightAstNode, rightType # we cannot really dereference a funcptr with ctypes ...
			else:
				assert False, str(stmnt) + " has bad type " + str(rightType)
		elif stmnt._op.content == "&":
			# We need to catch offsetof-like calls here because ctypes doesn't allow
			# NULL pointer access.
			offset = _resolveOffsetOf(funcEnv.globalScope.stateStruct, stmnt)
			if offset is not None:
				t = CStdIntType("intptr_t")
				return getAstNode_newTypeInstance(funcEnv.interpreter, t, ast.Num(n=offset)), t
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
				a.operand = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, rightAstNode, rightType)
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
		return getAstNode_assign(funcEnv.globalScope.stateStruct, leftAstNode, leftType, rightAstNode, rightType), leftType
	elif stmnt._op.content in OpAugAssign:
		return getAstNode_augAssign(funcEnv.globalScope.stateStruct, leftAstNode, leftType, stmnt._op.content, rightAstNode, rightType), leftType
	elif stmnt._op.content in OpBinBool:
		a = ast.BoolOp()
		a.op = OpBinBool[stmnt._op.content]()
		a.values = [
			getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, leftAstNode, leftType),
			getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, rightAstNode, rightType)]
		return getAstNode_newTypeInstance(funcEnv.interpreter, ctypes.c_int, a), ctypes.c_int
	elif stmnt._op.content in OpBinCmp:
		a = ast.Compare()
		a.ops = [OpBinCmp[stmnt._op.content]()]
		a.left = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, leftAstNode, leftType)
		a.comparators = [getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, rightAstNode, rightType)]
		return getAstNode_newTypeInstance(funcEnv.interpreter, ctypes.c_int, a), ctypes.c_int
	elif stmnt._op.content == "?:":
		middleAstNode, middleType = astAndTypeForStatement(funcEnv, stmnt._middleexpr)
		a = ast.IfExp()
		a.test = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, leftAstNode, leftType)
		a.body = middleAstNode
		a.orelse = rightAstNode
		# TODO: we take the type from middleType right now. not really correct...
		# So, cast the orelse part.
		a.orelse = getAstNode_newTypeInstance(funcEnv.interpreter, middleType, a.orelse, rightType)
		return a, middleType
	elif isPointerType(leftType):
		if isinstance(leftType, CArrayType):
			# The value-AST will be a pointer.
			leftType = CPointerType(ptr=leftType.arrayOf)
		return getAstNode_ptrBinOpExpr(
			funcEnv.globalScope.stateStruct,
			leftAstNode, leftType,
			stmnt._op.content,
			rightAstNode, rightType), leftType
	elif stmnt._op.content in OpBin:
		a = ast.BinOp()
		a.op = OpBin[stmnt._op.content]()
		a.left = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, leftAstNode, leftType)
		a.right = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, rightAstNode, rightType)
		# We assume that the type of `a` is leftType.
		# TODO: type not really correct. e.g. int + float -> float
		# Note: No pointer arithmetic here, that case is caught above.
		return getAstNode_newTypeInstance(funcEnv.interpreter, leftType, a), leftType
	else:
		assert False, "binary op " + str(stmnt._op) + " is unknown"

PyAstNoOp = ast.Assert(test=ast.Name(id="True", ctx=ast.Load()), msg=None)

def astForCWhile(funcEnv, stmnt):
	assert isinstance(stmnt, CWhileStatement)
	assert len(stmnt.args) == 1
	assert isinstance(stmnt.args[0], CStatement)

	whileAst = ast.While(body=[], orelse=[])
	whileAst.test = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, *astAndTypeForCStatement(funcEnv, stmnt.args[0]))

	funcEnv.pushScope(whileAst.body)
	if stmnt.body is not None:
		cCodeToPyAstList(funcEnv, stmnt.body)
	if not whileAst.body: whileAst.body.append(ast.Pass())
	funcEnv.popScope()

	return whileAst

def astForCFor(funcEnv, stmnt):
	assert isinstance(stmnt, CForStatement)
	assert len(stmnt.args) == 3
	assert isinstance(stmnt.args[1], CStatement) # second arg is the check; we must be able to evaluate that

	# introduce dummy 'if' AST so that we have a scope for the for-loop (esp. the first statement)
	ifAst = ast.If(body=[], orelse=[], test=ast.Name(id="True", ctx=ast.Load()))
	funcEnv.pushScope(ifAst.body)
	if stmnt.args[0]:  # could be empty
		cStatementToPyAst(funcEnv, stmnt.args[0])
	
	whileAst = ast.While(body=[], orelse=[], test=ast.Name(id="True", ctx=ast.Load()))
	ifAst.body.append(whileAst)

	if stmnt.args[1]:  # non-empty statement
		ifTestAst = ast.If(body=[ast.Pass()], orelse=[ast.Break()])
		ifTestAst.test = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, *astAndTypeForCStatement(funcEnv, stmnt.args[1]))
		whileAst.body.append(ifTestAst)
	
	funcEnv.pushScope(whileAst.body)
	if stmnt.body is not None:
		cCodeToPyAstList(funcEnv, stmnt.body)
	if stmnt.args[2]:  # could be empty
		cStatementToPyAst(funcEnv, stmnt.args[2])
	funcEnv.popScope() # whileAst / main for-body
	
	funcEnv.popScope() # ifAst
	return ifAst

def astForCDoWhile(funcEnv, stmnt):
	assert isinstance(stmnt, CDoStatement)
	assert isinstance(stmnt.whilePart, CWhileStatement)
	assert stmnt.whilePart.body is None
	assert len(stmnt.args) == 0
	assert len(stmnt.whilePart.args) == 1
	assert isinstance(stmnt.whilePart.args[0], CStatement)
	whileAst = ast.While(body=[], orelse=[], test=ast.Name(id="True", ctx=ast.Load()))
	
	funcEnv.pushScope(whileAst.body)
	if stmnt.body is not None:
		cCodeToPyAstList(funcEnv, stmnt.body)
	funcEnv.popScope()

	ifAst = ast.If(body=[ast.Continue()], orelse=[ast.Break()])
	ifAst.test = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, *astAndTypeForCStatement(funcEnv, stmnt.whilePart.args[0]))
	whileAst.body.append(ifAst)
	
	return whileAst

def astForCIf(funcEnv, stmnt):
	assert isinstance(stmnt, CIfStatement)
	assert len(stmnt.args) == 1
	assert isinstance(stmnt.args[0], CStatement)

	ifAst = ast.If(body=[], orelse=[])
	ifAst.test = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, *astAndTypeForCStatement(funcEnv, stmnt.args[0]))

	funcEnv.pushScope(ifAst.body)
	if stmnt.body is not None:
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
	a.value = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, switchValueAst, switchValueType)
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
					comparators=[getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, *astAndTypeForCStatement(funcEnv, c.args[0]))]
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
	valueAst, valueType = astAndTypeForCStatement(funcEnv, stmnt.body)
	returnValueAst = getAstNode_newTypeInstance(funcEnv.interpreter, funcEnv.func.type, valueAst, valueType)
	return ast.Return(value=returnValueAst)

def cStatementToPyAst(funcEnv, c):
	"""
	:type funcEnv: FuncEnv
	"""
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
	elif isinstance(c, CGotoStatement):
		funcEnv.needGotoHandling = True
		body.append(goto.GotoStatement(c.name))
	elif isinstance(c, CGotoLabel):
		funcEnv.needGotoHandling = True
		body.append(goto.GotoLabel(c.name))
	else:
		assert False, "cannot handle " + str(c)

def cCodeToPyAstList(funcEnv, cBody):
	if isinstance(cBody, CBody):
		for c in cBody.contentlist:
			cStatementToPyAst(funcEnv, c)
	else:
		cStatementToPyAst(funcEnv, cBody)

class WrappedValues:
	pass


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
		self.wrappedValues = WrappedValues()  # attrib -> obj
		self.globalsDict = {
			"ctypes": ctypes,
			"helpers": Helpers,
			"g": self.globalsWrapper,
			"structs": self.globalsStructWrapper,
			"values": self.wrappedValues,
			"intp": self
			}
	
	def _cStateWrapperError(self, s):
		print "Error:", s
		
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
			print "TODO (missing C source code file):", func.name, "is not loaded yet"
		else:
			cCodeToPyAstList(base, func.body)
		base.popScope()
		if isSameType(self._cStateWrapper, func.type, CVoidType()):
			returnValueAst = NoneAstNode
		else:
			returnTypeAst = getAstNodeForVarType(self, func.type)
			returnValueAst = makeAstNodeCall(returnTypeAst)
		base.astNode.body.append(ast.Return(value=returnValueAst))
		if base.needGotoHandling:
			gotoVarName = base.registerNewUnscopedVarName("goto")
			base.astNode = goto.transform_goto(base.astNode, gotoVarName)
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
