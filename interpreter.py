#!/usr/bin/env python3

"""
PyCParser - interpreter
by Albert Zeyer, 2011
code under BSD 2-Clause License
"""

from __future__ import print_function

import cparser
from cparser import *
from cwrapper import CStateWrapper
from cparser_utils import long, unicode
from interpreter_utils import ast_bin_op_to_func

import ctypes
import _ctypes
import ast
import sys
import inspect
import goto
from weakref import ref, WeakValueDictionary
from sortedcontainers.sortedset import SortedSet
from collections import OrderedDict

PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] >= 3


def iterIdentifierNames():
    S = "abcdefghijklmnopqrstuvwxyz0123456789"
    n = 0
    while True:
        v = []
        x = n
        while x > 0 or len(v) == 0:
            v = [x % len(S)] + v
            x //= len(S)
        yield "".join([S[x] for x in v])
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
PyReservedNames = set(dir(__builtins__) + keyword.kwlist + ["ctypes", "helpers"])


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

    def _getDeclTypeBodyAstAndType(self, decl):
        assert isinstance(decl, CVarDecl)

        if decl.body is not None:
            anonFuncEnv = FuncEnv(self)
            bodyAst, bodyType = astAndTypeForStatement(anonFuncEnv, decl.body)
        else:
            bodyAst, bodyType = None, None

        decl_type = decl.type
        # Arrays might have implicit length. If the len is not specified
        # explicitely, try to get it from the body.
        if isinstance(decl_type, CArrayType):
            arrayLen = None
            if decl_type.arrayLen:
                arrayLen = getConstValue(self.stateStruct, decl_type.arrayLen)
                assert isinstance(arrayLen, (int, long))
                assert arrayLen > 0
            if isinstance(bodyType, (tuple, list)):
                if arrayLen:
                    assert arrayLen >= len(bodyType)
                else:
                    arrayLen = len(bodyType)
                    assert arrayLen > 0
            elif isinstance(bodyType, CArrayType):
                _arrayLen = getConstValue(self.stateStruct, bodyType.arrayLen)
                assert isinstance(_arrayLen, (int, long))
                if arrayLen:
                    assert arrayLen >= _arrayLen
                else:
                    arrayLen = _arrayLen
            else:
                assert bodyType is None, "not expected: %r" % bodyType
            assert arrayLen, "array without explicit len and without body"
            if not decl_type.arrayLen:
                decl_type.arrayLen = CNumber(arrayLen)

        return decl_type, bodyAst, bodyType

    def _getEmptyValueAst(self, decl_type):
        return getAstNode_newTypeInstance(FuncEnv(self), decl_type)

    def _getVarBodyValueAst(self, decl, decl_type, bodyAst, bodyType):
        assert isinstance(decl, CVarDecl)
        if decl.body is None:
            return None

        v = decl.body.getConstValue(self.stateStruct)
        if v is not None and v == 0:
            return None  # no need to initialize it
        if not isinstance(decl_type, CArrayType) and isPointerType(decl_type) \
            and not isPointerType(bodyType):
            assert v is not None and v == 0, "Global: Initializing pointer type " + str(
                decl_type) + " only supported with 0 value but we got " + str(v) + " from " + str(decl.body)
            return None
        else:
            valueAst = getAstNode_newTypeInstance(FuncEnv(self), decl_type, bodyAst, bodyType)
            return valueAst

    def getVar(self, name):
        if name in self.vars: return self.vars[name]
        decl = self.findIdentifier(name)
        if self.interpreter.debug_print_getVar: print("+ getVar %s" % decl)
        assert isinstance(decl, CVarDecl)

        # Note: To avoid infinite loops, we must first create the object.
        # This is to avoid infinite loops, in case that the initializer
        # access the var itself.

        decl_type, bodyAst, bodyType = self._getDeclTypeBodyAstAndType(decl)

        def getEmpty():
            emptyValueAst = self._getEmptyValueAst(decl_type)
            v_empty = evalValueAst(self, emptyValueAst, "<PyCParser_globalvar_%s_init_empty>" % name)
            self.interpreter._storePtr(ctypes.pointer(v_empty))
            return v_empty
        self.vars[name] = getEmpty()

        bodyValueAst = self._getVarBodyValueAst(decl, decl_type, bodyAst, bodyType)
        if bodyValueAst is not None:
            value = evalValueAst(self, bodyValueAst, "<PyCParser_globalvar_" + name + "_init_value>")
            self.interpreter.helpers.assign(self.vars[name], value)

        return self.vars[name]


def evalValueAst(funcEnv, valueAst, srccode_name=None):
    if srccode_name is None: srccode_name = "<PyCParser_dynamic_eval>"
    if False:  # directly via AST
        valueExprAst = ast.Expression(valueAst)
        ast.fix_missing_locations(valueExprAst)
        valueCode = compile(valueExprAst, srccode_name, "eval")
    else:
        src = _unparse(valueAst)
        _set_linecache(srccode_name, src)
        valueCode = compile(src, srccode_name, "eval")
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


class GlobalsTypeWrapper:
    def __init__(self, globalScope, attrib):
        self.globalScope = globalScope
        self.attrib = attrib

    def __setattr__(self, name, value):
        self.__dict__[name] = value

    def __getattr__(self, name):
        collection = getattr(self.globalScope.stateStruct, self.attrib)
        decl = collection.get(name)
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
        self.localTypes = {} # type -> var-name
        self.scopeStack = []  # type: typing.List[FuncCodeblockScope]
        self.needGotoHandling = False
        self.astNode = ast.FunctionDef(
            args=ast.arguments(args=[], vararg=None, kwarg=None, defaults=[]),
            body=[], decorator_list=[])
    def get_name(self): return self.astNode.name
    def __repr__(self):
        try: return "<" + self.__class__.__name__ + " of " + self.get_name() + ">"
        except Exception: return "<" + self.__class__.__name__ + " in invalid state>"
    def _registerNewVar(self, varName, varDecl):
        if varDecl is not None:
            assert id(varDecl) not in self.varNames
        for name in iterIdWithPostfixes(varName):
            if not isValidVarName(name): continue
            if name in self.interpreter.globalsDict: continue
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
    def registerNewUnscopedVarName(self, varName, initNone=True):
        """
        :type varName: str
        :return: Python var name
        :rtype: str
        This will register a new var which is available in all scopes
        and we init it with None at the very beginning.
        """
        varName = self._registerNewVar(varName, None)
        if initNone:
            a = ast.Assign()
            a.targets = [ast.Name(id=varName, ctx=ast.Store())]
            a.value = ast.Name(id="None", ctx=ast.Load())
            # Add at the very front because this var might not be assigned otherwise when there is a goto.
            self.scopeStack[0].body.insert(0, a)
        return varName
    def registerLocalTypedef(self, typedef):
        assert isinstance(typedef, CTypedef)
        if typedef in self.localTypes: return
        varName = self.registerNewUnscopedVarName(typedef.name or "anon_type", initNone=False)
        self.localTypes[typedef] = varName
        a = ast.Assign()
        a.targets = [ast.Name(id=varName, ctx=ast.Store())]
        a.value = getAstNodeForVarType(self, typedef.type)
        self.scopeStack[-1].body.append(a)
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
        """
        :param list bodyStmntList:
        :rtype: FuncCodeblockScope
        """
        scope = FuncCodeblockScope(funcEnv=self, body=bodyStmntList)
        self.scopeStack += [scope]
        return scope

    def popScope(self):
        scope = self.scopeStack.pop()
        scope.finishMe()

    def getBody(self):
        """
        :rtype: list
        """
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
    t_name = t.__name__
    if t_name.startswith("wrapCTypeClass_"): t_name = t_name[len("wrapCTypeClass_"):]
    assert issubclass(t, getattr(ctypes, t_name))
    t = getattr(ctypes, t_name)  # get original type
    if needWrapCTypeClass(t):
        return getAstNodeAttrib("ctypes_wrapped", t_name)
    return getAstNodeAttrib("ctypes", t_name)

def getAstNodeForVarType(funcEnv, t):
    interpreter = funcEnv.interpreter
    if isinstance(t, CBuiltinType):
        return getAstNodeForCTypesBasicType(State.CBuiltinTypes[t.builtinType])
    elif isinstance(t, CStdIntType):
        return getAstNodeForCTypesBasicType(State.StdIntTypes[t.name])
    elif isinstance(t, CEnum):
        # Just use the related int type.
        stdtype = t.getMinCIntType()
        assert stdtype is not None
        return getAstNodeForCTypesBasicType(State.StdIntTypes[stdtype])
    elif isinstance(t, CPointerType):
        if t.pointerOf == CBuiltinType(("void",)):
            return getAstNodeAttrib("ctypes_wrapped", "c_void_p")
        a = getAstNodeAttrib("ctypes", "POINTER")
        return makeAstNodeCall(a, getAstNodeForVarType(funcEnv, t.pointerOf))
    elif isinstance(t, CTypedef):
        if t in funcEnv.localTypes:
            return ast.Name(id=funcEnv.localTypes[t], ctx=ast.Load())
        return getAstNodeAttrib("g", t.name)
    elif isinstance(t, CStruct):
        if t.name is None:
            # This is an anonymous struct. E.g. like in:
            # `struct A { struct { int x; } a; };`
            # Wrap it via CWrapValue.
            # TODO: is this the best solution? We could refer it to the named parent. If there is one.
            v = getAstForWrapValue(interpreter, CWrapValue(getCType(t, interpreter.globalScope.stateStruct)))
            return getAstNodeAttrib(v, "value")
        # TODO: this assumes the was previously declared globally.
        return getAstNodeAttrib("structs", t.name)
    elif isinstance(t, CUnion):
        assert t.name is not None
        return getAstNodeAttrib("unions", t.name)
    elif isinstance(t, CArrayType):
        arrayOf = getAstNodeForVarType(funcEnv, t.arrayOf)
        v = getConstValue(interpreter.globalScope.stateStruct, t.arrayLen)
        assert isinstance(v, (int,long))
        arrayLen = ast.Num(n=v)
        return ast.BinOp(left=arrayOf, op=ast.Mult(), right=arrayLen)
    elif isinstance(t, (CFuncPointerDecl, CFunc)):
        return makeAstNodeCall(
            getAstNodeAttrib("ctypes", "CFUNCTYPE"),
            makeAstNodeCall(
                getAstNodeAttrib("helpers", "fixReturnType"),
                getAstNodeForVarType(funcEnv, t.type)
            ),
            *[getAstNodeForVarType(funcEnv, a.type) for a in t.args]
        )
    elif isinstance(t, CWrapValue):
        return getAstNodeForVarType(funcEnv, t.getCType(None))
    elif isinstance(t, CWrapFuncType):
        return getAstNodeForVarType(funcEnv, t.func)
    else:
        try: return getAstNodeForCTypesBasicType(t)
        except DidNotFindCTypesBasicType: pass
    assert False, "cannot handle " + str(t)


def findHelperFunc(f):
    for k in dir(Helpers):
        v = getattr(Helpers, k)
        if v == f: return k
    return None


def makeAstNodeCall(func, *args):
    if not isinstance(func, ast.AST):
        name = findHelperFunc(func)
        assert name is not None, str(func) + " unknown"
        func = getAstNodeAttrib("helpers", name)
    return ast.Call(func=func, args=list(args), keywords=[], starargs=None, kwargs=None)


def makeCastToVoidP(v):
    astVoidPT = getAstNodeAttrib("ctypes_wrapped", "c_void_p")
    astCast = getAstNodeAttrib("ctypes", "cast")
    return makeAstNodeCall(astCast, v, astVoidPT)


def makeCastToVoidP_value(v):
    castToPtr = makeCastToVoidP(v)
    astValue = getAstNodeAttrib(castToPtr, "value")
    return ast.BoolOp(op=ast.Or(), values=[astValue, ast.Num(0)])


def getAstNode_valueFromObj(stateStruct, objAst, objType, isPartOfCOp=False):
    if isPartOfCOp:  # usually ==, != or so.
        # Some types need special handling. We cast them to integer.
        if isinstance(objType, CFuncPointerDecl):
            return makeCastToVoidP_value(objAst)  # return address
        if isinstance(objType, CWrapFuncType):
            return makeFuncPtrValue(objAst, objType)
    if isinstance(objType, CFuncPointerDecl):
        # It's already the value. See also CWrapFuncType below.
        return objAst
    elif isPointerType(objType):
        from inspect import isclass
        if not isclass(objType) or not issubclass(objType, ctypes.c_void_p):
            # Only c_void_p supports to get the pointer-value via the value-attrib.
            astVoidP = makeCastToVoidP(objAst)
        else:
            astVoidP = objAst
        astValue = getAstNodeAttrib(astVoidP, "value")
        return ast.BoolOp(op=ast.Or(), values=[astValue, ast.Num(0)])
    elif isValueType(objType):
        astValue = getAstNodeAttrib(objAst, "value")
        return astValue
    elif isinstance(objType, CEnum):
        # We expect that this is just the int type.
        return getAstNodeAttrib(objAst, "value")
    elif isinstance(objType, CArrayType):
        # cast array to ptr
        return makeCastToVoidP_value(objAst)
    elif isinstance(objType, CTypedef):
        t = objType.type
        return getAstNode_valueFromObj(stateStruct, objAst, t, isPartOfCOp=isPartOfCOp)
    elif isinstance(objType, CWrapValue):
        # It's already the value. See astAndTypeForStatement().
        return getAstNode_valueFromObj(stateStruct, objAst, objType.getCType(stateStruct), isPartOfCOp=isPartOfCOp)
    elif isinstance(objType, CWrapFuncType):
        # It's already the value. See astAndTypeForStatement(). And CFuncPointerDecl above.
        return objAst
    elif isinstance(objType, (CStruct, CUnion)):
        # Note that this is not always useable as a value.
        # It cannot be used in a copy constructor because there is no such thing.
        return objAst
    elif isinstance(objType, CVariadicArgsType):
        # We handle this special anyway.
        return objAst
    else:
        assert False, "bad type: " + str(objType)


def _makeVal(funcEnv, f_arg_type, s_arg_ast, s_arg_type):
    interpreter = funcEnv.interpreter
    stateStruct = interpreter.globalScope.stateStruct
    while isinstance(f_arg_type, CTypedef):
        f_arg_type = f_arg_type.type
    while isinstance(s_arg_type, CTypedef):
        s_arg_type = s_arg_type.type

    if isinstance(s_arg_type, (tuple, list)):  # CCurlyArrayArgs
        arrayLen = len(s_arg_type)
        typeAst = getAstNodeForVarType(funcEnv, f_arg_type)
        assert isinstance(s_arg_ast, ast.Tuple)
        assert len(s_arg_ast.elts) == len(s_arg_type)
        # There is a bit of inconsistency between basic types init
        # (like c_int), which must get a value (int),
        # and ctypes.Structure/ctypes.ARRAY, which for some field can either
        # get a value (int) or a c_int. For pointers, it must get
        # the var, not the value.
        # This is mostly the same as for calling functions.
        f_args = []
        if isinstance(f_arg_type, (CStruct,CUnion)):
            if not f_arg_type.body:
                assert f_arg_type.name
                if isinstance(f_arg_type, CStruct):
                    f_arg_type = interpreter.globalScope.stateStruct.structs[f_arg_type.name]
                elif isinstance(f_arg_type, CUnion):
                    f_arg_type = interpreter.globalScope.stateStruct.unions[f_arg_type.name]
            for c in f_arg_type.body.contentlist:
                if not isinstance(c, CVarDecl): continue
                f_args += [c.type]
        elif isinstance(f_arg_type, CArrayType):
            f_args += [f_arg_type.arrayOf] * arrayLen
        else:
            assert False, "did not expect type %r" % f_arg_type
        assert len(s_arg_type) <= len(f_args)
        # Somewhat like autoCastArgs():
        s_args = []
        for _f_arg_type, _s_arg_ast, _s_arg_type in zip(f_args, s_arg_ast.elts, s_arg_type):
            _s_arg_ast = _makeVal(funcEnv, _f_arg_type, _s_arg_ast, _s_arg_type)
            s_args += [_s_arg_ast]
        return makeAstNodeCall(typeAst, *s_args)

    f_arg_ctype = getCType(f_arg_type, stateStruct)
    if isinstance(s_arg_type, CArrayType) and not s_arg_type.arrayLen:
        # It can happen that we don't know the array-len yet.
        # Then, getCType() will fail.
        # However, it's probably enough here to just use the pointer-type instead.
        s_arg_type = CPointerType(s_arg_type.arrayOf)

    s_arg_ctype = getCType(s_arg_type, stateStruct)
    use_value = False
    if stateStruct.IndirectSimpleCTypes and needWrapCTypeClass(f_arg_ctype):
        # We cannot use e.g. c_int, because the Structure uses another wrapped field type.
        # However, using the value itself should be fine in those cases.
        use_value = True
    if use_value:
        s_arg_ast = getAstNode_valueFromObj(stateStruct, s_arg_ast, s_arg_type)
    else:
        need_cast = s_arg_ctype != f_arg_ctype
        if isinstance(s_arg_type, CWrapFuncType):
            # The new type instance might add some checks.
            need_cast = True
        if need_cast:
            s_arg_ast = getAstNode_newTypeInstance(funcEnv, f_arg_type, s_arg_ast, s_arg_type)
    return s_arg_ast


def getAstNode_newTypeInstance(funcEnv, objType, argAst=None, argType=None):
    """
    Create a new instance of type `objType`.
    It can optionally be initialized with `argAst` (already AST) which is of type `argType`.
    If `argType` is None, `argAst` is supposed to be a value (e.g. via getAstNode_valueFromObj).
    :type interpreter: Interpreter
    """
    interpreter = funcEnv.interpreter
    origObjType = objType
    while isinstance(objType, CTypedef):
        objType = objType.type
    while isinstance(argType, CTypedef):
        argType = argType.type

    if isinstance(objType, CBuiltinType) and objType.builtinType == ("void",):
        # It's like a void cast. Return None.
        if argAst is None:
            return NoneAstNode
        tup = ast.Tuple(elts=(argAst, NoneAstNode), ctx=ast.Load())
        return getAstNodeArrayIndex(tup, 1)

    arrayLen = None
    if isinstance(objType, CArrayType):
        arrayOf = getAstNodeForVarType(funcEnv, objType.arrayOf)
        if objType.arrayLen:
            arrayLen = getConstValue(interpreter.globalScope.stateStruct, objType.arrayLen)
            assert arrayLen is not None
            if isinstance(argType, (tuple, list)):
                assert arrayLen == len(argType)
        else:
            # Handle array type extra here for the case when array-len is not specified.
            assert argType is not None
            if isinstance(argType, (tuple, list)):
                arrayLen = len(argType)
            else:
                assert isinstance(argType, CArrayType)
                arrayLen = getConstValue(interpreter.globalScope.stateStruct, argType.arrayLen)
                assert arrayLen is not None
            # Write back to type so that future getCType calls will succeed.
            objType.arrayLen = CNumber(arrayLen)

        typeAst = ast.BinOp(left=arrayOf, op=ast.Mult(), right=ast.Num(n=arrayLen))
    else:
        typeAst = getAstNodeForVarType(funcEnv, origObjType)

    if isinstance(argType, (tuple, list)):  # CCurlyArrayArgs
        assert isinstance(argAst, ast.Tuple)
        assert len(argAst.elts) == len(argType)
        # There is a bit of inconsistency between basic types init
        # (like c_int), which must get a value (int),
        # and ctypes.Structure/ctypes.ARRAY, which for some field can either
        # get a value (int) or a c_int. For pointers, it must get
        # the var, not the value.
        # This is mostly the same as for calling functions.
        f_args = []
        while isinstance(objType, CTypedef):
            objType = objType.type
        if isinstance(objType, CStruct):
            for c in objType.body.contentlist:
                if not isinstance(c, CVarDecl): continue
                f_args += [c.type]
        elif isinstance(objType, CArrayType):
            f_args += [objType.arrayOf] * arrayLen
        else:
            assert False, "did not expect type %r" % objType
        assert len(argType) <= len(f_args)
        # Somewhat like autoCastArgs():
        s_args = []
        for f_arg_type, s_arg_ast, s_arg_type in zip(f_args, argAst.elts, argType):
            s_arg_ast = _makeVal(funcEnv, f_arg_type, s_arg_ast, s_arg_type)
            s_args += [s_arg_ast]
        return makeAstNodeCall(typeAst, *s_args)

    if isinstance(objType, CArrayType) and isinstance(argType, CArrayType):
        return ast.Call(func=typeAst, args=[], keywords=[], starargs=argAst, kwargs=None)

    if isinstance(argType, CWrapFuncType):
        if isVoidPtrType(objType):
            vAst = getAstNode_newTypeInstance(
                funcEnv, CFuncPointerDecl(type=argType.func.type, args=argType.func.args),
                argAst=argAst, argType=argType)
            astCast = getAstNodeAttrib("ctypes", "cast")
            return makeAstNodeCall(astCast, vAst, typeAst)
        if isinstance(objType, CWrapFuncType):
            return argAst
        assert isinstance(objType, CFuncPointerDecl)  # what other case could there be?
        return makeAstNodeCall(getAstNodeAttrib("helpers", "makeFuncPtr"), typeAst, argAst)

    if isinstance(objType, CPointerType) and usePyRefForType(objType.pointerOf):
        # We expect a PyRef.
        return makeAstNodeCall(getAstNodeAttrib("helpers", "PyRef"),
                               *([getAstNodeAttrib(argAst, "ref")] if argAst else []))

    if isPointerType(objType, checkWrapValue=True) and isPointerType(argType, checkWrapValue=True):
        # We can have it simpler. This is even important in some cases
        # were the pointer instance is temporary and the object
        # would get freed otherwise!
        astCast = getAstNodeAttrib("ctypes", "cast")
        return makeAstNodeCall(astCast, argAst, typeAst)

    if isSameType(interpreter.globalScope.stateStruct, objType, ctypes.c_void_p) and \
        isinstance(argType, CFuncPointerDecl):
        # We treat CFuncPointerDecl not as a normal pointer.
        # However, we allow casts to c_void_p.
        astCast = getAstNodeAttrib("ctypes", "cast")
        return makeAstNodeCall(astCast, argAst, typeAst)

    if isinstance(objType, CFuncPointerDecl) and isinstance(argType, CFuncPointerDecl):
        # We did not allow a pointer-to-func-ptr cast above.
        # But we allow func-ptr-to-func-ptr.
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
        # Note that we already covered the case where both objType and argType
        # are pointer types, and we get a ctypes pointer object.
        # In that case, we can use ctypes.cast, which is more or less safe.
        # Note what this case here means:
        # We get an integer from somewhere, and interpret is as a pointer.
        # So, if there is a bug in how we got this integer, this can
        # potentially lead to an invalid pointer and hard to find bug.
        # Also, if the memory was allocated before by Python,
        # normally the ctypes pointer handling would keep a reference
        # to the underlying Python object.
        # When we however just get the raw pointer address as an integer
        # and then convert that back to a pointer at this place,
        # it doesn't know about the underlying Python objects.
        # When the underlying Python objects will get out-of-scope
        # at some later point, which we cannot control here,
        # this again would lead to hard to find bugs.
        assert len(args) == 1
        return makeAstNodeCall(getAstNodeAttrib("intp", "_getPtr"), args[0], typeAst)
        #astVoidPT = getAstNodeAttrib("ctypes", "c_void_p")
        #astCast = getAstNodeAttrib("ctypes", "cast")
        #astVoidP = makeAstNodeCall(astVoidPT, *args)
        #return makeAstNodeCall(astCast, astVoidP, typeAst)

    if isIntType(objType) and args:
        # Introduce a Python int-cast, because ctypes will fail if it is a float or so.
        assert len(args) == 1
        args = [makeAstNodeCall(ast.Name(id="int", ctx=ast.Load()), *args)]
    if isinstance(objType, (CStruct, CUnion)) and argAst:
        # We get the object itself. We expect that this is supposed to be a copy.
        # However, there is no such thing as a copy constructor.
        assert len(args) == 1
        return makeAstNodeCall(Helpers.assign, makeAstNodeCall(typeAst), *args)
    if isinstance(objType, CVariadicArgsType):
        if argAst:
            return makeAstNodeCall(Helpers.VarArgs, argAst)
        assert isinstance(funcEnv.astNode, ast.FunctionDef)
        # TODO: Normally, we would assign the var via va_start().
        # However, we just always initialize with the varargs tuple also already here
        # because we have the ref to the real varargs here.
        # See globalincludewrappers.
        return makeAstNodeCall(
            Helpers.VarArgs,
            ast.Name(id=funcEnv.astNode.args.vararg or "None", ctx=ast.Load()),
            ast.Name(id="intp", ctx=ast.Load()))
    return makeAstNodeCall(typeAst, *args)


class FuncCodeblockScope:
    def __init__(self, funcEnv, body):
        """
        :param FuncEnv funcEnv:
        :param list body:
        """
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
            a.value = getAstNode_newTypeInstance(self.funcEnv, varDecl.type, ast.Name(id=varName, ctx=ast.Load()), varDecl.type)
        elif isinstance(varDecl, CVarDecl):
            if varDecl.body is not None:
                bodyAst, t = astAndTypeForStatement(self.funcEnv, varDecl.body)
                v = getConstValue(self.funcEnv.globalScope.stateStruct, varDecl.body)
                if v is not None and not v:
                    # If we want to init with 0, we can skip this because we are always zero initialized.
                    bodyAst = t = None
                a.value = getAstNode_newTypeInstance(self.funcEnv, varDecl.type, bodyAst, t)
            else:
                a.value = getAstNode_newTypeInstance(self.funcEnv, varDecl.type)
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
    "/": ast.Div if PY2 else ast.FloorDiv,
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

OpAugAssign = {"%s=" % k: v for (k, v) in OpBin.items()}
OpBinFuncsByOp = {op: ast_bin_op_to_func(op) for op in OpBin.values()}


class Helpers:
    def __init__(self, interpreter):
        self.interpreter = interpreter

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
        if isinstance(a, ctypes.c_void_p):
            return ctypes.cast(a, wrapCTypeClass(ctypes.c_void_p))
        if isinstance(a, ctypes._Pointer):
            return ctypes.cast(a, a.__class__)
        if isinstance(a, ctypes.Array):
            return ctypes.pointer(a[0])  # should keep _b_base_
            # This would not:
            # return ctypes.cast(a, ctypes.POINTER(a._type_))
        if isinstance(a, ctypes._SimpleCData):
            # Safe, should not be a pointer.
            return a.__class__(a.value)
        raise NotImplementedError("cannot copy %r" % a)

    @staticmethod
    def assign(a, bValue):
        if isinstance(a, Helpers.VarArgs):
            a.assign(bValue)
        elif isinstance(a, type(bValue)):
            # WARNING: This can be dangerous/unsafe.
            # It will correctly copy the content. However, we might loose any Python obj refs,
            # from body_value._objects.
            # TODO: Fix this somehow? Better use a helper func which goes over the structure.
            ctypes.pointer(a)[0] = bValue
        elif isinstance(a, (ctypes.c_void_p, ctypes._SimpleCData)):
            assert hasattr(a, "value")
            a.value = bValue
        else:
            assert False, "assign: not handled: %r of type %r" % (a, type(a))
        return a

    @staticmethod
    def assignPtr(a, bValue):
        # WARNING: This can be dangerous/unsafe.
        # It will correctly copy the content. However, we might loose any Python obj refs.
        # TODO: Fix this somehow?
        _ctype_ptr_set_value(a, bValue)
        return a

    def getValueGeneric(self, b):
        if isinstance(b, (ctypes._Pointer, ctypes._CFuncPtr, ctypes.Array, ctypes.c_void_p)):
            self.interpreter._storePtr(b)
        if isinstance(b, (ctypes._Pointer, ctypes._CFuncPtr, ctypes.Array)):
            b = ctypes.cast(b, ctypes.c_void_p)
        if isinstance(b, (ctypes.c_void_p, ctypes._SimpleCData)):
            b = b.value
        return b

    def assignGeneric(self, a, bValue):
        from inspect import isfunction
        if isinstance(a, ctypes._CFuncPtr):
            if isfunction(bValue):
                bValue = self.makeFuncPtr(type(a), bValue)
            assert isinstance(bValue, ctypes._CFuncPtr)
            return self.assign(a, bValue)
        elif isPointerType(type(a), alsoArray=False):
            bValue = self.getValueGeneric(bValue)
            assert isinstance(bValue, (int, long))
            return self.assignPtr(a, bValue)
        else:
            bValue = self.getValueGeneric(bValue)
            assert isinstance(bValue, (int, long, float))
            return self.assign(a, bValue)

    @staticmethod
    def augAssign(a, op, bValue):
        if isinstance(a, (ctypes.c_void_p, ctypes._SimpleCData)):
            a.value = OpBinFuncs[op](a.value, bValue)
        else:
            assert False, "augAssign: not handled: %r of type %r" % (a, type(a))
        return a

    def augAssignPtr(self, a, op, bValue):
        # `a` is itself a pointer.
        assert op in ("+=","-=")
        op = OpBinFuncs[op]
        bValue *= ctypes.sizeof(a._type_)
        aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
        # Should be safe as long as `a` already contains all the refs.
        aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
        aPtr.contents.value = op(aPtr.contents.value, bValue)
        a = self.interpreter._storePtr(a, offset=op(0, bValue))
        return a

    def ptrArithmetic(self, a, op, bValue):
        assert op in ("+","-")
        return self.augAssignPtr(self.copy(a), op + "=", bValue)

    def fixReturnType(self, t):
        # Note: This behavior must match CFuncPointerDecl.getCType()
        # so that we stay compatible.
        if t is None: return None
        if issubclass(t, ctypes._Pointer):
            # A Python func wrapped in CFuncType cannot handle any pointer type
            # other than void-ptr.
            t = wrapCTypeClass(ctypes.c_void_p)
        stateStruct = self.interpreter.globalScope.stateStruct
        return getCTypeWrapped(t, stateStruct)

    def makeFuncPtr(self, funcCType, func):
        assert inspect.isfunction(func)
        if getattr(func, "C_funcPtr", None):
            return func.C_funcPtr
        # We store the pointer in the func itself
        # so that it don't get out of scope (because of casts).
        func.C_funcPtr = funcCType(func)
        func.C_funcPtrStorage = PointerStorage(ptr=func.C_funcPtr, value=func)
        self.interpreter._storePtr(func.C_funcPtr, value=func.C_funcPtrStorage)
        return func.C_funcPtr

    def checkedFuncPtrCall(self, f, *args):
        if _ctype_ptr_get_value(f) == 0:
            raise Exception("checkedFuncPtrCall: tried to call NULL ptr")
        for arg in args:
            # We might need to store some pointers to local vars here.
            if isinstance(arg, (ctypes.c_void_p, ctypes._Pointer)):
                self.interpreter._storePtr(arg)
        return f(*args)

    class VarArgs:
        """
        Explicit wrapping of variadic args. (tuple of args)
        """
        def __init__(self, args, intp=None):
            if isinstance(args, Helpers.VarArgs):
                intp = args.intp
                args = args.args
            if args is not None:
                assert isinstance(args, tuple)
            assert isinstance(intp, Interpreter)
            self.args = args
            self.intp = intp
            self.idx = 0
        def assign(self, other):
            assert isinstance(other, self.__class__)
            self.index = 0
            self.args = other.args
        def get_next(self):
            idx = self.idx
            self.idx += 1
            return self.args[idx]
        def __repr__(self):
            return "<VarArgs %r [%i]>" % (self.args, self.idx)

    class PyRef:
        """
        Python-level reference. Like a pointer but all the logic handled in Python.
        """
        def __init__(self, ref):
            self.ref = ref


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
    name = interpreter.wrappedValues.get_value(wrapValue)
    v = getAstNodeAttrib("values", name)
    return v

def astForCast(funcEnv, new_type, arg_ast):
    """
    :type new_type: _CBaseWithOptBody or derived
    :param arg_ast: the value to be casted, already as an AST
    :return: ast (of type new_type)
    """
    aType = new_type
    aTypeAst = getAstNodeForVarType(funcEnv, aType)
    bValueAst = arg_ast

    if isPointerType(aType):
        astVoidPT = getAstNodeAttrib("ctypes_wrapped", "c_void_p")
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
            if isinstance(f_arg_type, CFuncArgDecl):
                f_arg_type = f_arg_type.type
            f_arg_ctype = getCType(f_arg_type, funcEnv.globalScope.stateStruct)
            s_arg_ctype = getCType(s_arg_type, funcEnv.globalScope.stateStruct)
            if s_arg_ctype != f_arg_ctype:
                s_arg_ast = getAstNode_newTypeInstance(funcEnv, f_arg_type, s_arg_ast, s_arg_type)
            elif isinstance(s_arg_type, CWrapFuncType):
                # Need to store pointer.
                s_arg_ast = makeAstNodeCall(
                    getAstNodeAttrib("helpers", "makeFuncPtr"),
                    getAstNodeForVarType(funcEnv, f_arg_type), s_arg_ast)
        r_args += [s_arg_ast]
    return r_args


def astAndTypeForStatement(funcEnv, stmnt):
    if isinstance(stmnt, (CVarDecl,CFuncArgDecl)):
        return funcEnv.getAstNodeForVarDecl(stmnt), stmnt.type
    elif isinstance(stmnt, CFunc):
        return funcEnv.getAstNodeForVarDecl(stmnt), CWrapFuncType(stmnt, funcEnv=funcEnv)
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
        assert attrDecl is not None, "attrib %r not found in %r" % (a.attr, t)
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
        # TODO handle stmnt.typeSpec
        if isinstance(stmnt.content, float):
            t = CBuiltinType(("double",))
            return getAstNode_newTypeInstance(funcEnv, t, ast.Num(n=stmnt.content)), t
        t = minCIntTypeForNums(stmnt.content, useUnsignedTypes=False)
        if t is None: t = "int64_t" # it's an overflow; just take a big type
        t = CStdIntType(t)
        return getAstNode_newTypeInstance(funcEnv, t, ast.Num(n=stmnt.content)), t
    elif isinstance(stmnt, CEnumConst):
        t = stmnt.parent
        assert isinstance(t, CEnum)
        return getAstNode_newTypeInstance(funcEnv, t, ast.Num(n=stmnt.value)), t
    elif isinstance(stmnt, CStr):
        s = str(stmnt.content)
        l = len(s) + 1
        ta = CArrayType(arrayOf=CBuiltinType(("char",)), arrayLen=CNumber(l))
        #tp = CPointerType(ctypes.c_byte)
        ss = makeAstNodeCall(getAstNodeAttrib("intp", "_make_string"), ast.Str(s=s))
        return ss, ta
    elif isinstance(stmnt, CChar):
        return makeAstNodeCall(getAstNodeAttrib("ctypes", "c_byte"), ast.Num(stmnt.content)), ctypes.c_byte
    elif isinstance(stmnt, CFuncCall):
        if isinstance(stmnt.base, CFunc):
            assert stmnt.base.name is not None
            a = ast.Call(keywords=[], starargs=None, kwargs=None)
            a.func = getAstNodeAttrib("g", stmnt.base.name)
            a.args = autoCastArgs(funcEnv, [f_arg.type for f_arg in stmnt.base.args], stmnt.args)
            if stmnt.base.type in (CBuiltinType(("void",)), CVoidType()):
                b = a  # Will (should) be ignored anyway. Should be None.
            else:
                # We expect the return by value. Thus create a new ctype around.
                b = getAstNode_newTypeInstance(funcEnv, stmnt.base.type, a)
            return b, stmnt.base.type
        elif isinstance(stmnt.base, CSizeofSymbol):
            assert len(stmnt.args) == 1
            a = stmnt.args[0]
            if isinstance(a, CStatement) and not a.isCType():
                v, _ = astAndTypeForStatement(funcEnv, stmnt.args[0])
                sizeValueAst = makeAstNodeCall(getAstNodeAttrib("ctypes", "sizeof"), v)
                sizeAst = makeAstNodeCall(getAstNodeAttrib("ctypes_wrapped", "c_size_t"), sizeValueAst)
                return sizeAst, CStdIntType("size_t")
            # We expect that it is a type.
            t = getCType(stmnt.args[0], funcEnv.globalScope.stateStruct)
            assert t is not None
            s = ctypes.sizeof(t)
            sizeAst = makeAstNodeCall(getAstNodeAttrib("ctypes_wrapped", "c_size_t"), ast.Num(s))
            return sizeAst, CStdIntType("size_t")
        elif isinstance(stmnt.base, CWrapValue):
            # expect that we just wrapped a callable function/object
            a = ast.Call(keywords=[], starargs=None, kwargs=None)
            a.func = getAstNodeAttrib(getAstForWrapValue(funcEnv.globalScope.interpreter, stmnt.base), "value")
            if isinstance(stmnt.base.value, ctypes._CFuncPtr):
                a.args = autoCastArgs(funcEnv, stmnt.base.argTypes, stmnt.args)
            else:  # e.g. custom lambda / Python func
                a.args = [astAndTypeForStatement(funcEnv, arg)[0] for arg in stmnt.args]
            returnType = stmnt.base.getReturnType(funcEnv.globalScope.stateStruct, stmnt.args)
            return a, returnType
        elif isType(stmnt.base):
            # C static cast
            if isinstance(stmnt.base, CStatement):
                aType = stmnt.base.asType()
            else:
                aType = stmnt.base
            args = [astAndTypeForStatement(funcEnv, a) for a in stmnt.args]
            if len(args) == 0:
                return getAstNode_newTypeInstance(funcEnv, aType), aType
            if len(args) == 1:
                bAst, bType = args[0]
            else:
                tup = ast.Tuple(elts=[a[0] for a in args], ctx=ast.Load())
                bAst = getAstNodeArrayIndex(tup, -1)
                bType = args[-1][1]
            return getAstNode_newTypeInstance(funcEnv, aType, bAst, bType), aType
        else:
            # Expect func ptr call.
            pAst, pType = astAndTypeForStatement(funcEnv, stmnt.base)
            while isinstance(pType, CTypedef):
                pType = pType.type
            assert isinstance(pType, CFuncPointerDecl)
            a = makeAstNodeCall(
                Helpers.checkedFuncPtrCall,
                pAst,
                *autoCastArgs(funcEnv, pType.args, stmnt.args))
            # See Helpers.fixReturnType. In some cases, we convert the return type to c_void_p.
            if isPointerType(pType.type, alsoArray=False) and not isVoidPtrType(pType.type):
                fixedReturnType = ctypes.c_void_p
                a = getAstNode_newTypeInstance(funcEnv, pType.type, a, fixedReturnType)
            return a, pType.type
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
    if isPointerType(bType):
        bAst = makeAstNodeCall(getAstNodeAttrib("intp", "_storePtr"), bAst)
    bValueAst = getAstNode_valueFromObj(stateStruct, bAst, bType, isPartOfCOp=True)
    if isPointerType(aType, alsoFuncPtr=True):
        return makeAstNodeCall(Helpers.assignPtr, aAst, bValueAst)
    return makeAstNodeCall(Helpers.assign, aAst, bValueAst)

def getAstNode_augAssign(stateStruct, aAst, aType, opStr, bAst, bType):
    opAst = ast.Str(opStr)
    if isPointerType(bType):
        bAst = makeAstNodeCall(getAstNodeAttrib("intp", "_storePtr"), bAst)
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
    assert not isPointerType(bType)
    bValueAst = getAstNode_valueFromObj(stateStruct, bAst, bType, isPartOfCOp=True)
    return makeAstNodeCall(Helpers.ptrArithmetic, aAst, opAst, bValueAst)

def getAstNode_ptrSubstract(stateStruct, aAst, aType, bAst, bType):
    if isinstance(aType, CArrayType):
        aType = CPointerType(aType.arrayOf)
    if isinstance(bType, CArrayType):
        bType = CPointerType(bType.arrayOf)
    assert isPointerType(aType)
    assert isPointerType(bType)
    assert isSameType(stateStruct, aType, bType)
    aValueAst = getAstNode_valueFromObj(stateStruct, aAst, aType, isPartOfCOp=True)
    bValueAst = getAstNode_valueFromObj(stateStruct, bAst, bType, isPartOfCOp=True)
    subAst = ast.BinOp(left=aValueAst, op=ast.Sub(), right=bValueAst)
    aCType = getCType(aType.pointerOf, stateStruct)
    assert aCType is not None
    s = ctypes.sizeof(aCType)
    divAst = ast.BinOp(left=subAst, op=ast.Div() if PY2 else ast.FloorDiv(), right=ast.Num(n=s))
    resultAst = makeAstNodeCall(getAstNodeAttrib("ctypes_wrapped", "c_long"), divAst)
    return resultAst


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
    attrib_chain = []
    while isinstance(rightexpr, CAttribAccessRef):
        attrib_chain = [rightexpr.name] + attrib_chain
        rightexpr = rightexpr.base
    if not isinstance(rightexpr, CPtrAccessRef): return
    zero_ptr_type = _getZeroPtrTypeOrNone(rightexpr.base)
    if zero_ptr_type is None: return
    attrib_chain = [rightexpr.name] + attrib_chain
    offset = 0
    base = zero_ptr_type
    for k in attrib_chain:
        while isinstance(base, CTypedef):
            base = base.type
        assert isinstance(base, (CStruct, CUnion))
        c_type = getCType(base, stateStruct)
        field = getattr(c_type, k)
        offset += field.offset
        sub = base.findAttrib(stateStruct, k)
        assert isinstance(sub, CVarDecl)
        base = sub.type
    return offset

def makeFuncPtrValue(argAst, argType):
    assert isinstance(argType, CWrapFuncType)
    v = getAstNode_newTypeInstance(argType.funcEnv, CBuiltinType(("void", "*")), argAst, argType)
    astValue = getAstNodeAttrib(v, "value")
    return ast.BoolOp(op=ast.Or(), values=[astValue, ast.Num(0)])

def usePyRefForType(varType):
    t = resolveTypedef(varType)
    return isinstance(t, CVariadicArgsType)

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
                if usePyRefForType(rightType.pointerOf):
                    return getAstNodeAttrib(rightAstNode, "ref"), rightType.pointerOf
                return getAstNodeAttrib(rightAstNode, "contents"), rightType.pointerOf
            elif isinstance(rightType, CArrayType):
                return getAstNodeArrayIndex(rightAstNode, 0), rightType.arrayOf
            elif isinstance(rightType, CFuncPointerDecl):
                return rightAstNode, rightType # we cannot really dereference a funcptr with ctypes ...
            else:
                assert False, str(stmnt) + " has bad type " + str(rightType)
        elif stmnt._op.content == "&":
            if isinstance(resolveTypedef(rightType), CWrapFuncType):
                # Leave function as-is.
                # A pointer to a function is handled just like the function itself.
                return rightAstNode, rightType
            if usePyRefForType(rightType):
                return makeAstNodeCall(getAstNodeAttrib("helpers", "PyRef"), rightAstNode), CPointerType(rightType)
            # We need to catch offsetof-like calls here because ctypes doesn't allow
            # NULL pointer access. offsetof is like `&(struct S*)(0)->attrib`.
            offset = _resolveOffsetOf(funcEnv.globalScope.stateStruct, stmnt)
            if offset is not None:
                t = CStdIntType("intptr_t")
                return getAstNode_newTypeInstance(funcEnv, t, ast.Num(n=offset)), t
            return makeAstNodeCall(getAstNodeAttrib("ctypes", "pointer"), rightAstNode), CPointerType(rightType)
        elif stmnt._op.content in OpUnary:
            a = ast.UnaryOp()
            a.op = OpUnary[stmnt._op.content]()
            if isinstance(rightType, CWrapFuncType):
                assert stmnt._op.content == "!", "the only supported unary op for ptr types is '!'"
                a.operand = makeFuncPtrValue(rightAstNode, rightType)
                rightType = ctypes.c_int
            elif isPointerType(rightType, alsoFuncPtr=True):
                assert stmnt._op.content == "!", "the only supported unary op for ptr types is '!'"
                a.operand = makeCastToVoidP_value(rightAstNode)
                rightType = ctypes.c_int
            else:
                a.operand = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, rightAstNode, rightType)
            return getAstNode_newTypeInstance(funcEnv, rightType, a), rightType
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
            getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, leftAstNode, leftType, isPartOfCOp=True),
            getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, rightAstNode, rightType, isPartOfCOp=True)]
        return getAstNode_newTypeInstance(funcEnv, ctypes.c_int, a), ctypes.c_int
    elif stmnt._op.content in OpBinCmp:
        a = ast.Compare()
        a.ops = [OpBinCmp[stmnt._op.content]()]
        a.left = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, leftAstNode, leftType, isPartOfCOp=True)
        a.comparators = [getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, rightAstNode, rightType, isPartOfCOp=True)]
        return getAstNode_newTypeInstance(funcEnv, ctypes.c_int, a), ctypes.c_int
    elif stmnt._op.content == "?:":
        middleAstNode, middleType = astAndTypeForStatement(funcEnv, stmnt._middleexpr)
        commonType = getCommonValueType(funcEnv.globalScope.stateStruct, middleType, rightType)
        a = ast.IfExp()
        a.test = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, leftAstNode, leftType, isPartOfCOp=True)
        a.body = getAstNode_newTypeInstance(funcEnv, commonType, middleAstNode, middleType)
        a.orelse = getAstNode_newTypeInstance(funcEnv, commonType, rightAstNode, rightType)
        return a, commonType
    elif stmnt._op.content == ",":
        a = ast.Tuple(ctx=ast.Load())
        a.elts = (leftAstNode, rightAstNode)
        b = ast.Subscript(value=a, slice=ast.Num(n=1), ctx=ast.Load())
        return b, rightType
    elif isPointerType(leftType):
        if isinstance(leftType, CArrayType):
            # The value-AST will be a pointer.
            leftType = CPointerType(ptr=leftType.arrayOf)
        if isPointerType(rightType):
            assert stmnt._op.content == "-"
            return getAstNode_ptrSubstract(
                funcEnv.globalScope.stateStruct,
                leftAstNode, leftType,
                rightAstNode, rightType), CStdIntType("ptrdiff_t")
        return getAstNode_ptrBinOpExpr(
            funcEnv.globalScope.stateStruct,
            leftAstNode, leftType,
            stmnt._op.content,
            rightAstNode, rightType), leftType
    elif stmnt._op.content in OpBin:  # except comparisons. handled above
        a = ast.BinOp()
        a.op = OpBin[stmnt._op.content]()
        a.left = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, leftAstNode, leftType, isPartOfCOp=True)
        a.right = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, rightAstNode, rightType, isPartOfCOp=True)
        commonType = stmnt.getValueType(funcEnv.globalScope.stateStruct)
        # Note: No pointer arithmetic here, that case is caught above.
        return getAstNode_newTypeInstance(funcEnv, commonType, a), commonType
    else:
        assert False, "binary op " + str(stmnt._op) + " is unknown"

PyAstNoOp = ast.Assert(test=ast.Name(id="True", ctx=ast.Load()), msg=None)

def astForCWhile(funcEnv, stmnt):
    assert isinstance(stmnt, CWhileStatement)
    assert len(stmnt.args) == 1
    assert isinstance(stmnt.args[0], CStatement)

    whileAst = ast.While(body=[], orelse=[])
    whileAst.test = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, *astAndTypeForCStatement(funcEnv, stmnt.args[0]), isPartOfCOp=True)

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

    var_first_iteration = funcEnv.registerNewUnscopedVarName("first_iteration")
    a = ast.Assign()
    a.targets = [ast.Name(id=var_first_iteration, ctx=ast.Store())]
    a.value = ast.Name(id="True", ctx=ast.Load())
    ifAst.body.append(a)
    if stmnt.args[0]:  # could be empty
        cStatementToPyAst(funcEnv, stmnt.args[0])

    whileAst = ast.While(body=[], orelse=[], test=ast.Name(id="True", ctx=ast.Load()))
    ifAst.body.append(whileAst)

    ifFirstIterAst = ast.If(body=[], orelse=[], test=ast.Name(id=var_first_iteration, ctx=ast.Load()))
    a = ast.Assign()
    a.targets = [ast.Name(id=var_first_iteration, ctx=ast.Store())]
    a.value = ast.Name(id="False", ctx=ast.Load())
    ifFirstIterAst.body.append(a)
    if stmnt.args[2]:  # could be empty
        funcEnv.pushScope(ifFirstIterAst.orelse)
        cStatementToPyAst(funcEnv, stmnt.args[2])
        funcEnv.popScope() # ifFirstIterAst
    whileAst.body.append(ifFirstIterAst)

    if stmnt.args[1]:  # non-empty statement
        ifTestAst = ast.If(body=[ast.Pass()], orelse=[ast.Break()])
        ifTestAst.test = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, *astAndTypeForCStatement(funcEnv, stmnt.args[1]), isPartOfCOp=True)
        whileAst.body.append(ifTestAst)

    funcEnv.pushScope(whileAst.body)
    if stmnt.body is not None:
        cCodeToPyAstList(funcEnv, stmnt.body)
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
    ifAst.test = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, *astAndTypeForCStatement(funcEnv, stmnt.whilePart.args[0]), isPartOfCOp=True)
    whileAst.body.append(ifAst)

    return whileAst

def astForCIf(funcEnv, stmnt):
    assert isinstance(stmnt, CIfStatement)
    assert len(stmnt.args) == 1
    assert isinstance(stmnt.args[0], CStatement)

    ifAst = ast.If(body=[], orelse=[])
    ifAst.test = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, *astAndTypeForCStatement(funcEnv, stmnt.args[0]), isPartOfCOp=True)

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
    a.value = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, switchValueAst, switchValueType, isPartOfCOp=True)
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
                    comparators=[getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, *astAndTypeForCStatement(funcEnv, c.args[0]), isPartOfCOp=True)]
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
    if stmnt is not None:
        assert isinstance(stmnt, CReturnStatement)
    if isSameType(funcEnv.globalScope.stateStruct, funcEnv.func.type, CVoidType()):
        assert stmnt is None or not stmnt.body
        return ast.Return(value=None)
    # Note that we must return a value (int), not a ctypes-type (c_int).
    # This is so that these functions can be wrapped into a CFUNCTYPE (native func ptr).
    returnValueAst = None
    if stmnt is None:
        # No error for non-void return, because this will be the final return of the func,
        # and we just want a safe return in all cases.
        emptyAst = getAstNode_newTypeInstance(funcEnv, funcEnv.func.type)
        returnValueAst = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, emptyAst, funcEnv.func.type)
    else:
        assert isinstance(stmnt.body, CStatement)
        #if isPointerType(funcEnv.func.type):
        #	v = stmnt.body.getConstValue(funcEnv.globalScope.stateStruct)
        #	if v is not None and v == 0:
        #		# Return zero-initialized pointer.
        #		returnValueAst = getAstNode_newTypeInstance(funcEnv.interpreter, funcEnv.func.type)
        if returnValueAst is None:
            valueAst, valueType = astAndTypeForCStatement(funcEnv, stmnt.body)
            if isPointerType(valueType):
                valueAst = makeAstNodeCall(getAstNodeAttrib("intp", "_storePtr"), valueAst)
            returnValueAst = getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, valueAst, valueType)
            #returnValueAst = getAstNode_newTypeInstance(funcEnv.interpreter, funcEnv.func.type, valueAst, valueType)
            #returnValueAst = valueAst
    return ast.Return(value=returnValueAst)

def cStatementToPyAst(funcEnv, c):
    """
    :param FuncEnv funcEnv:
    :param cparser._CBaseWithOptBody c:
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
    elif isinstance(c, CTypedef):
        funcEnv.registerLocalTypedef(c)
    else:
        assert False, "cannot handle " + str(c)


def cCodeToPyAstList(funcEnv, cBody):
    """
    :param FuncEnv funcEnv:
    :param CBody|cparser._CBaseWithOptBody cBody:
    """
    if isinstance(cBody, CBody):
        for c in cBody.contentlist:
            cStatementToPyAst(funcEnv, c)
    else:
        cStatementToPyAst(funcEnv, cBody)


class WrappedValues:

    def __init__(self):
        self.callbacks_register_new = []
        self.list = set()

    def get_value(self, wrapValue):
        assert isinstance(wrapValue, CWrapValue)
        orig_name = wrapValue.name or "anonymous_value"
        for name in iterIdWithPostfixes(orig_name):
            if not isValidVarName(name): continue
            obj = getattr(self, name, None)
            if obj is None:  # new
                self.list.add(name)
                setattr(self, name, wrapValue)
                for cb in self.callbacks_register_new:
                    cb(name, wrapValue)
                obj = wrapValue
            if obj is wrapValue:
                return name


def _unparse(pyAst):
    from six import StringIO
    output = StringIO()
    from py_demo_unparse import Unparser
    Unparser(pyAst, file=output)
    output.write("\n")
    return output.getvalue()

def _set_linecache(filename, source):
    import linecache
    linecache.cache[filename] = None, None, [line+'\n' for line in source.splitlines()], filename

def _ctype_ptr_get_value(ptr):
    """
    :param ctypes.c_void_p ptr:
    :rtype: int
    """
    ptr = ctypes.cast(ptr, wrapCTypeClass(ctypes.c_void_p))
    return ptr.value or 0

def _ctype_ptr_set_value(ptr, addr):
    assert isinstance(addr, (int, long))
    aPtr = ctypes.cast(ctypes.pointer(ptr), ctypes.POINTER(ctypes.c_void_p))
    aPtr.contents.value = addr

def _ctype_get_ptr_addr(obj):
    return _ctype_ptr_get_value(ctypes.pointer(obj))

def _ctype_collect_objects(obj):
    """
    :param ctypes._CData obj: ctypes obj
    _CData has the relevant attribs _b_base_, _b_needsfree_, _objects.
    _b_base_ would be a counted-ref to a base _CData object which shares mem with it.
    _b_needsfree_ is True/False, depending if we need to free sth.
    _objects is a dict, where the values are counted-refs to objects which we depend on.
    counted-ref as opposed to weak-ref, i.e. as long as `obj` lives,
    all the ref'd objects will live, too.
    """
    d = OrderedDict()  # id(o) -> o
    def collect(o):
        if o is None: return
        if id(o) in d: return
        if not hasattr(o, "_objects"): return
        d[id(o)] = o
        visit_c(o)
    def visit_generic(o):
        if isinstance(o, dict):
            for s in o.values():
                visit_generic(s)
        elif isinstance(o, tuple):
            for s in o:
                visit_generic(s)
        elif isinstance(o, str):
            pass
        else:
            collect(o)
    def visit_c(b):
        # Usually, we get a ctypes object with _objects and _b_base_ here.
        # However, sometimes get ctypes.CThunkObject here which does not have these attribs.
        visit_generic(b._objects)
        collect(b._b_base_)
    collect(obj)
    return d.values()


class CTypesWrapper(object):
    def __setattr__(self, name, value):
        self.__dict__[name] = value

    def __getattr__(self, name):
        t = getattr(ctypes, name)
        t_wrapped = wrapCTypeClass(t)
        self.__dict__[name] = t_wrapped
        return t_wrapped


class PointerStorage:
    def __init__(self, ptr, value):
        self.ptr = ptr
        self.valueRef = ref(value)


class Interpreter:
    def __init__(self):
        self.stateStructs = []
        self._cStateWrapper = CStateWrapper(self)
        self._cStateWrapper.IndirectSimpleCTypes = True
        self._cStateWrapper.error = self._cStateWrapperError
        self.globalScope = GlobalScope(self, self._cStateWrapper)
        self._func_cache = {}
        self.globalsWrapper = GlobalsWrapper(self.globalScope)
        self.globalsStructWrapper = GlobalsTypeWrapper(self.globalScope, "structs")
        self.globalsUnionsWrapper = GlobalsTypeWrapper(self.globalScope, "unions")
        self.wrappedValues = WrappedValues()  # attrib -> obj
        self.ctypes_wrapped = CTypesWrapper()
        self.helpers = Helpers(self)
        self.mallocs = {}  # ptr addr -> ctype obj
        # Note: The pointerStorage will only weakly ref the ctype objects.
        # When the real ctype objects go out of scope, we don't want to
        # keep them alive.
        self.pointerStorage = WeakValueDictionary()  # ptr addr -> weak ctype obj ref
        self.pointerStorageRanges = SortedSet()  # (ptr-addr,size) tuples
        # Here we hold constant strings, because they need some global
        # storage which will not get freed.
        self.constStrings = {}  # str -> ctype c_char_p
        self.globalsDict = {
            "ctypes": ctypes,
                "ctypes_wrapped": self.ctypes_wrapped,
                "helpers": self.helpers,
                "g": self.globalsWrapper,
                "structs": self.globalsStructWrapper,
                "unions": self.globalsUnionsWrapper,
                "values": self.wrappedValues,
                "intp": self
        }
        self.debug_print_getFunc = False
        self.debug_print_getVar = False

    def _cStateWrapperError(self, s):
        print("Error (ignored):", s)

    def register(self, stateStruct):
        """
        :param State stateStruct:
        """
        self.stateStructs += [stateStruct]
        if stateStruct._global_include_wrapper:
            stateStruct._global_include_wrapper.interpreter = self

    def setupStatic(self):
        stateStruct = State()
        stateStruct.autoSetupGlobalIncludeWrappers()
        stateStruct._global_include_wrapper.add_all_to_state(stateStruct)
        self.register(stateStruct)

    def getCType(self, obj):
        wrappedStateStruct = self._cStateWrapper
        for T,DictName in [(CStruct,"structs"), (CUnion,"unions"), (CEnum,"enums")]:
            if isinstance(obj, T):
                if obj.name is not None:
                    return getattr(wrappedStateStruct, DictName)[obj.name].getCValue(wrappedStateStruct)
                else:
                    return obj.getCValue(wrappedStateStruct)
        return obj.getCValue(wrappedStateStruct)

    def _abort(self):
        print("C abort() call.")
        raise Exception("C abort()")

    def _exit(self, i):
        print("C exit(%i) call." % i)
        sys.exit(i)

    def _make_string(self, s):
        """
        :param str s:
        :rtype: ctypes.Array
        """
        if s in self.constStrings:
            return self.constStrings[s]
        if PY3:
            s = s.encode("utf8")
        # Array so that we have the len info.
        # c_byte because we always treat `char` as c_byte to avoid problems.
        t = self.ctypes_wrapped.c_byte * (len(s) + 1)
        if PY3:
            assert isinstance(s, bytes)
            buf = t(*s)
        else:
            assert isinstance(s, str)
            buf = t(*map(ord, s))
        self.constStrings[s] = buf
        self._storePtr(buf)
        return buf

    def _malloc(self, size):
        """
        :param int size:
        :rtype: ctypes.c_void_p
        """
        if size == 0:
            size = 1
        buf = (self.ctypes_wrapped.c_byte * size)()
        ptr_addr = _ctype_get_ptr_addr(buf)
        self.mallocs[ptr_addr] = buf
        ret = ctypes.cast(ctypes.pointer(buf), wrapCTypeClass(ctypes.c_void_p))
        self._storePtr(ret)
        return ret

    def _realloc(self, ptr_addr, size):
        """
        :param int ptr_addr:
        :param int size:
        :rtype: ctypes.c_void_p
        """
        if not ptr_addr:
            return self._malloc(size)
        try:
            buf = self.mallocs.pop(ptr_addr)
        except KeyError:
            raise Exception("_realloc: address 0x%x was not allocated by us" % ptr_addr)
        if buf._length_ >= size:
            return ctypes.cast(buf, wrapCTypeClass(ctypes.c_void_p))
        ptr = self._malloc(size)
        ctypes.memmove(ptr, ctypes.cast(buf, wrapCTypeClass(ctypes.c_void_p)), ctypes.c_size_t(buf._length_))
        return ptr

    def _free(self, ptr_addr):
        """
        :param int ptr_addr:
        """
        try:
            self.mallocs.pop(ptr_addr)
        except KeyError:
            raise Exception("_free: address 0x%x was not allocated by us" % ptr_addr)

    def _storePtr(self, ptr, offset=0, value=None):
        """
        :param ctypes.c_void_p ptr:
        :param int offset:
        :param PointerStorage|None value:
        """
        assert isinstance(ptr, (ctypes.c_void_p, ctypes._Pointer, ctypes.Array, ctypes._CFuncPtr))
        ptr_addr = _ctype_ptr_get_value(ptr)
        if ptr_addr == 0:
            return ptr  # Nothing needed to store.
        if ptr_addr in self.pointerStorage:
            return ptr
        if value is not None:
            # No extra logic.
            assert isinstance(value, PointerStorage)
            assert offset == 0
            self.pointerStorage[ptr_addr] = value
            return ptr
        assert not isinstance(ptr, ctypes._CFuncPtr)  # should have been catched above
        if ptr_addr - offset in self.pointerStorage:
            self.pointerStorage[ptr_addr] = self.pointerStorage[ptr_addr - offset]
            return ptr
        objs = _ctype_collect_objects(ptr)
        # Later collected objects are more likely the ones we want.
        # So go over in reverse order.
        for obj in reversed(objs):
            obj_ptr_addr = _ctype_get_ptr_addr(obj)
            if ptr_addr == obj_ptr_addr + offset:
                self.pointerStorage[obj_ptr_addr] = obj
                if offset != 0:
                    self.pointerStorage[ptr_addr] = obj
                obj_size = ctypes.sizeof(obj)
                self.pointerStorageRanges.add((obj_ptr_addr, obj_size))
                return ptr
        # This is slower. Check pointerStorageRanges if we have it.
        for obj_ptr_addr, obj_size in self.pointerStorageRanges.irange(
                reverse=True, maximum=(ptr_addr + 1, 0), inclusive=(True, False)
        ):
            if obj_ptr_addr + obj_size <= ptr_addr: break
            obj = self.pointerStorage.get(obj_ptr_addr, None)
            if obj is None:  # not alive anymore
                self.pointerStorageRanges.remove((obj_ptr_addr, obj_size))
            elif obj_ptr_addr <= ptr_addr:
                # Found it!
                self.pointerStorage[ptr_addr] = obj
                return ptr
        # Note: This can also/esp happen when the ptr was not allocated by us.
        # Not sure how to handle that yet...
        raise NotImplementedError(
            "_storePtr: ptr %r, objs %r, ptr_addr 0x%x, obj_ptr_addr %s" % (
                ptr, objs, ptr_addr, [hex(_ctype_get_ptr_addr(o) + offset) for o in objs]))

    def _getPtr(self, addr, ptr_type=None):
        """
        :param int addr:
        :param type ptr_type:
        :rtype: ctypes.pointer
        """
        assert isinstance(addr, (int, long))
        if addr == 0:
            assert ptr_type
            return ptr_type()
        try:
            obj = self.pointerStorage[addr]
        except KeyError:
            raise Exception("invalid pointer access to address 0x%x of type %r" % (addr, ptr_type))
        if isinstance(obj, PointerStorage):
            return obj.ptr
        ptr = ctypes.pointer(obj)
        ptr_addr = _ctype_ptr_get_value(ptr)
        if ptr_addr != addr:  # might be different if we had an offset in _setPtr
            _ctype_ptr_set_value(ptr, addr)
        return ptr

    def _translateFuncToPyAst(self, func, noBodyMode="warn-empty"):
        assert isinstance(func, CFunc)
        base = FuncEnv(globalScope=self.globalScope)
        assert func.name is not None
        base.func = func
        base.astNode.name = func.name
        base.pushScope(base.astNode.body)
        for arg in func.args:
            if isinstance(arg.type, CVariadicArgsType):
                name = base.registerNewUnscopedVarName("varargs", initNone=False)
                assert name
                base.astNode.args.vararg = name
            else:  # normal param
                name = base.registerNewVar(arg.name, arg)
                assert name
                base.astNode.args.args.append(ast.Name(id=name, ctx=ast.Param()))
        if func.body is None:
            # TODO: search in other C files
            # Hack for now: ignore :)
            if noBodyMode == "warn-empty":
                print("TODO (missing C source code file):", func.name, "is not loaded yet")
            elif noBodyMode == "code-with-exception":
                base.astNode.body.append(
                    ast.Raise(type=makeAstNodeCall(
                        ast.Name(id="Exception", ctx=ast.Load()),
                        ast.Str(s="Function '%s' only predeclared. Body is missing. Missing C source code."
                                % func.name)
                    ), inst=None, tback=None))
            else:
                assert False, "unknown no-body-mode: %r" % noBodyMode
        else:
            cCodeToPyAstList(base, func.body)
        base.popScope()
        base.astNode.body.append(astForCReturn(base, None))
        if base.needGotoHandling:
            gotoVarName = base.registerNewUnscopedVarName("goto", initNone=False)
            base.astNode = goto.transform_goto(base.astNode, gotoVarName)
        return base

    def _compile(self, pyAst, mode="single"):
        # We unparse + parse again for now for better debugging (so we get some code in a backtrace).
        SRC_FILENAME = "<PyCParser_%s>" % getattr(pyAst, "name", "unknown")
        def _unparseAndParse(pyAst):
            src = _unparse(pyAst)
            _set_linecache(SRC_FILENAME, src)
            return compile(src, SRC_FILENAME, mode)
        def _justCompile(pyAst):
            exprAst = ast.Interactive(body=[pyAst])
            ast.fix_missing_locations(exprAst)
            return compile(exprAst, SRC_FILENAME, mode)
        return _unparseAndParse(pyAst)

    def _translateFuncToPy(self, funcname):
        cfunc = self._cStateWrapper.funcs[funcname]
        if self.debug_print_getFunc: print("+ getFunc %s" % cfunc)
        funcEnv = self._translateFuncToPyAst(cfunc)
        pyAst = funcEnv.astNode
        compiled = self._compile(pyAst)
        d = {}
        eval(compiled, self.globalsDict, d)
        func = d[funcname]
        func.C_cFunc = cfunc
        func.C_pyAst = pyAst
        func.C_interpreter = self
        func.C_argTypes = [a.type for a in cfunc.args]
        func.C_resType = cfunc.type
        func.C_unparse = lambda: _unparse(pyAst)
        return func

    def getFunc(self, funcname):
        """
        :param str funcname:
        :return: generated Python function, via :func:`_translateFuncToPy`
        :rtype: function
        """
        if funcname in self._func_cache:
            return self._func_cache[funcname]
        else:
            func = self._translateFuncToPy(funcname)
            self._func_cache[funcname] = func
            return func

    def runSingleStatement(self, statement, dump=False):
        """
        :param CStatement|cparser._CControlStructure statement:
        :param bool dump:
        :return: value
        """
        # Create a dummy FuncEnv, as the API requires that.
        # See _translateFuncToPyAst.
        funcEnv = FuncEnv(globalScope=self.globalScope)
        funcEnv.pushScope(funcEnv.astNode.body)
        cStatementToPyAst(funcEnv, statement)
        d = {}
        res = None
        for pyAst in funcEnv.astNode.body:
            if dump:
                print("Python:", _unparse(pyAst).strip())
            compiled = self._compile(pyAst, mode="eval" if isinstance(statement, CStatement) else "exec")
            res = eval(compiled, self.globalsDict, d)
        return res

    def dumpFunc(self, funcname, output=sys.stdout):
        f = self.getFunc(funcname)
        print(f.C_unparse(), file=output)

    def _castArgToCType(self, arg, typ):
        if isinstance(typ, CPointerType):
            ctyp = getCType(typ, self._cStateWrapper)
            if arg is None:
                return ctyp()
            elif isinstance(arg, (str,unicode)):
                return self._make_string(arg)
            assert isinstance(arg, (list,tuple))
            o = (ctyp._type_ * (len(arg) + 1))()
            for i in range(len(arg)):
                o[i] = self._castArgToCType(arg[i], typ.pointerOf)
            op = ctypes.pointer(o)
            op = ctypes.cast(op, ctyp)
            return self._storePtr(op)
        elif isinstance(arg, (int,long)):
            t = minCIntTypeForNums(arg)
            if t is None: t = "int64_t" # it's an overflow; just take a big type
            return self._cStateWrapper.StdIntTypes[t](arg)
        else:
            assert False, "cannot cast " + str(arg) + " to " + str(typ)

    def _runFunc_kwargs_resolve(self, return_as_ctype=True):
        return {"return_as_ctype": return_as_ctype}

    def runFunc(self, funcname, *args, **kwargs):
        kwargs = self._runFunc_kwargs_resolve(**kwargs)
        f = self.getFunc(funcname)
        assert len(args) == len(f.C_argTypes)
        args = [self._castArgToCType(arg,typ) for (arg, typ) in zip(args,f.C_argTypes)]
        res = f(*args)
        if kwargs["return_as_ctype"]:
            res_ctype = f.C_resType.getCType(self.globalScope.stateStruct)
            if res_ctype is not None:
                if isPointerType(f.C_resType, checkWrapValue=True):
                    res = self._getPtr(res, res_ctype)
                    res = ctypes.cast(res, res_ctype)
                else:
                    res = res_ctype(res)
        return res
