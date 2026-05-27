#!/usr/bin/env python3

"""
PyCParser - interpreter
by Albert Zeyer, 2011
code under BSD 2-Clause License
"""

from __future__ import print_function

import ctypes
import _ctypes
import ast
import sys
import inspect
from weakref import ref, WeakValueDictionary
from collections import OrderedDict

from . import cparser
from .cparser import *
from .cwrapper import CStateWrapper
from .cparser_utils import long, unicode, py_safe_identifier
from .interpreter_utils import ast_bin_op_to_func
from . import goto
from .sortedcontainers.sortedset import SortedSet

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
                # Compute needed array length.  Common case: no
                # designators -> ``len(bodyType)`` (fast).  Designated
                # case: ``[N] = value`` can skip indices, so the array
                # length is max-designator-index + 1, not just the
                # number of initializers.  Without this, e.g. ``ops[]
                # = {[Invert] = ..., [Not] = ..., ...}`` (enum
                # constants 1..4) gives 4 initializers but the array
                # must be size 5.
                has_designator = any(d for (d, _) in bodyType)
                if not has_designator:
                    needed = len(bodyType)
                else:
                    needed = 0
                    cur_idx = 0
                    for designators, _ in bodyType:
                        if designators:
                            v = getConstValue(self.stateStruct, designators[0])
                            if isinstance(v, int):
                                cur_idx = v
                        if cur_idx + 1 > needed:
                            needed = cur_idx + 1
                        cur_idx += 1
                if arrayLen:
                    assert arrayLen >= needed
                else:
                    arrayLen = needed
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

        # Warn about "unresolved extern" globals -- analogous to a C linker
        # error.  This happens when a translation unit declares a symbol
        # via `extern T name;` (often through a public-API header like
        # `PyAPI_DATA(PyTypeObject) PyByteArray_Type;`) but no other parsed
        # `.c` file provides the matching definition.  We would silently
        # zero-fill such a variable, which then cascades into far-removed
        # crashes (e.g. `PyType_Ready` returning -1 with no Python-level
        # error because the type struct is all zeros).  Print once per
        # symbol so the actionable signal is visible without spam.
        if decl.body is None and "extern" in getattr(decl, "attribs", ()):
            if not getattr(self, "_warned_extern", None):
                self._warned_extern = set()
            if name not in self._warned_extern:
                self._warned_extern.add(name)
                print("WARNING: getVar(%r): symbol is `extern`-declared but has no "
                      "definition in any parsed source file" % name,
                      flush=True)

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
        # Translate Python-keyword/dunder-renamed names back to the
        # C-side identifier so the lookup hits ``state.funcs`` /
        # ``state.vars`` using the original C name.
        # ``py_safe_identifier`` appends ``_`` for renamed names;
        # strip it here when the rename rule says so.
        c_name = name
        if c_name.endswith("_"):
            stripped = c_name[:-1]
            if py_safe_identifier(stripped) == c_name:
                c_name = stripped
        decl = self.globalScope.findIdentifier(c_name)
        if decl is None: raise AttributeError(name)
        if isinstance(decl, CVarDecl):
            v = self.globalScope.getVar(c_name)
        elif isinstance(decl, CWrapValue):
            v = decl.value
        elif isinstance(decl, CFunc):
            v = self.globalScope.interpreter.getFunc(c_name)
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
        self.localTypeNames = {} # (type-class, name) -> var-name
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
        if typedef.name:
            self.localTypeNames[(CTypedef, typedef.name)] = varName
        a = ast.Assign()
        a.targets = [ast.Name(id=varName, ctx=ast.Store())]
        a.value = getAstNodeForVarType(self, typedef.type)
        if self.interpreter.debug_log_assign:
            a.value = makeAstNodeCall(getAstNodeAttrib("helpers", "logAssign"), ast.Str(varName), a.value)
        self.scopeStack[-1].body.append(a)
    def registerLocalType(self, typeObj):
        assert isinstance(typeObj, (CStruct, CUnion, CEnum))
        if typeObj in self.localTypes: return
        name = getattr(typeObj, "name", None) or "anon_type"
        varName = self.registerNewUnscopedVarName(name, initNone=False)
        self.localTypes[typeObj] = varName
        if getattr(typeObj, "name", None):
            self.localTypeNames[(typeObj.__class__, typeObj.name)] = varName
        a = ast.Assign()
        a.targets = [ast.Name(id=varName, ctx=ast.Store())]
        wrappedType = self.interpreter.getCType(typeObj)
        v = getAstForWrapValue(self.interpreter, CWrapValue(wrappedType))
        a.value = getAstNodeAttrib(v, "value")
        if self.interpreter.debug_log_assign:
            a.value = makeAstNodeCall(getAstNodeAttrib("helpers", "logAssign"), ast.Str(varName), a.value)
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
        # Rename Python reserved words (e.g. ``lambda`` from
        # ``static identifier lambda`` in symtable.c) so the
        # generated ``g.lambda_`` is valid Python.  ``GlobalsWrapper``
        # maps the renamed name back when looking up.
        return getAstNodeAttrib("g", py_safe_identifier(name))
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
        if t in funcEnv.localTypes:
            return ast.Name(id=funcEnv.localTypes[t], ctx=ast.Load())
        if (CEnum, t.name) in funcEnv.localTypeNames:
            return ast.Name(id=funcEnv.localTypeNames[(CEnum, t.name)], ctx=ast.Load())
        # Just use the related int type.
        stdtype = t.getMinCIntType()
        assert stdtype is not None
        return getAstNodeForCTypesBasicType(State.StdIntTypes[stdtype])
    elif isinstance(t, CBitfieldType):
        return getAstNodeForVarType(funcEnv, t.type)
    elif isinstance(t, CPointerType):
        if isinstance(t.pointerOf, CBuiltinType) and t.pointerOf.builtinType == ("void",):
            return getAstNodeAttrib("ctypes_wrapped", "c_void_p")
        return makeAstNodeCall(
            ast.Name(id="get_pointer_type", ctx=ast.Load()),
            getAstNodeForVarType(funcEnv, t.pointerOf)
        )
    elif isinstance(t, CTypedef):
        if t in funcEnv.localTypes:
            return ast.Name(id=funcEnv.localTypes[t], ctx=ast.Load())
        # If the typedef is registered globally, refer by name via
        # ``g.<name>``.  Otherwise it's a function-local typedef being
        # referenced from outside its function (typically a
        # function-scope static that's been promoted to global storage
        # and is now being materialised by the global scope's empty
        # FuncEnv -- e.g. ast_opt.c::fold_unaryop defines ``typedef
        # ... unary_op`` then declares ``static const unary_op
        # ops[]``).  Inline the underlying type in that case.
        if t.name is not None and t.name in funcEnv.globalScope.stateStruct.typedefs:
            return getAstNodeAttrib("g", t.name)
        return getAstNodeForVarType(funcEnv, t.type)
    elif isinstance(t, CStruct):
        if t in funcEnv.localTypes:
            return ast.Name(id=funcEnv.localTypes[t], ctx=ast.Load())
        if t.name in funcEnv.globalScope.stateStruct.structs:
            if funcEnv.globalScope.stateStruct.structs[t.name] in funcEnv.localTypes:
                return ast.Name(id=funcEnv.localTypes[funcEnv.globalScope.stateStruct.structs[t.name]], ctx=ast.Load())
        if (CStruct, t.name) in funcEnv.localTypeNames:
            return ast.Name(id=funcEnv.localTypeNames[(CStruct, t.name)], ctx=ast.Load())
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
        if t in funcEnv.localTypes:
            return ast.Name(id=funcEnv.localTypes[t], ctx=ast.Load())
        if (CUnion, t.name) in funcEnv.localTypeNames:
            return ast.Name(id=funcEnv.localTypeNames[(CUnion, t.name)], ctx=ast.Load())
        if t.name is None:
            # This is an anonymous union. E.g. like in:
            # `typedef union { int x; long y; } MyUnion;`
            # Wrap it via CWrapValue (same as anonymous struct handling).
            v = getAstForWrapValue(interpreter, CWrapValue(getCType(t, interpreter.globalScope.stateStruct)))
            return getAstNodeAttrib(v, "value")
        return getAstNodeAttrib("unions", t.name)
    elif isinstance(t, CArrayType):
        arrayOf = getAstNodeForVarType(funcEnv, t.arrayOf)
        # C99 flexible array member: ``T x[];`` (e.g. PyDictKeysObject's
        # trailing ``char dk_indices[]``).  ``t.arrayLen`` is a
        # ``CArrayStatement`` with no left/right expression -- its
        # ``__bool__`` returns False.  Layout-wise the FAM contributes
        # zero bytes to the struct header (the allocator extends the
        # buffer past the struct), so use length 0 here.
        if not t.arrayLen:
            return ast.BinOp(left=arrayOf, op=ast.Mult(), right=ast.Num(n=0))
        v = getConstValue(interpreter.globalScope.stateStruct, t.arrayLen)
        if isinstance(v, (int, long)):
            arrayLen = ast.Num(n=v)
        else:
            arrayLen, _ = astAndTypeForStatement(funcEnv, t.arrayLen)
            # astAndTypeForStatement always yields a ctypes-wrapped instance,
            # so we extract .value.
            arrayLen = ast.Attribute(value=arrayLen, attr="value", ctx=ast.Load())
        return ast.BinOp(left=arrayOf, op=ast.Mult(), right=arrayLen)
    elif isinstance(t, (CFuncPointerDecl, CFunc)):
        return makeAstNodeCall(
            ast.Name(id="get_cfunctype", ctx=ast.Load()),
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
    assert False, "getAstNodeForVarType cannot handle " + str(t)


def findHelperFunc(f):
    for k in dir(Helpers):
        v = getattr(Helpers, k)
        if v == f: return k
    return None


def makeAstNodeCall(func, *args, **kwargs):
    if not isinstance(func, ast.AST):
        name = findHelperFunc(func)
        assert name is not None, str(func) + " unknown"
        func = getAstNodeAttrib("helpers", name)
    keywords = [ast.keyword(arg=k, value=v) for k, v in kwargs.items()]
    return ast.Call(func=func, args=list(args), keywords=keywords, starargs=None, kwargs=None)


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
    elif isinstance(objType, CBitfieldType):
        # bitfields are returned as plain ints by ctypes
        return objAst
    elif isPointerType(objType):
        if isinstance(objType, CPointerType) and usePyRefForType(objType.pointerOf):
            # The "pointer" is a `Helpers.PyRef` (e.g. `&va_list`) -- a
            # Python-level reference with no materialized C address.
            # Truthy iff its `.ref` is not None; this lets a NULL PyRef
            # (built when C passes `NULL` for `va_list *`, e.g.
            # `skipitem(&format, NULL, 0)`) compare equal to 0.
            return makeAstNodeCall(
                ast.Name(id="int", ctx=ast.Load()),
                ast.Compare(
                    left=getAstNodeAttrib(objAst, "ref"),
                    ops=[ast.IsNot()],
                    comparators=[ast.Name(id="None", ctx=ast.Load())]))
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
        if isinstance(objType, CStdIntType) and objType.name == "wchar_t":
            # c_wchar.value returns a Python str char; convert to int for arithmetic/comparison
            return makeAstNodeCall(ast.Name(id="ord", ctx=ast.Load()), astValue)
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
        from inspect import isclass
        if isclass(objType) and issubclass(objType, ctypes._SimpleCData):
            # Raw ctypes type from a wrapped C function return value (e.g. c_double, c_float).
            return getAstNodeAttrib(objAst, "value")
        assert False, "bad type: " + str(objType)


def getAstNode_curlyArrayArgsInit(funcEnv, objType, argAst, argType):
    """
    Handle initialization of struct/array with curly braces { ... }.
    argType is a list of (designators, type).
    """
    interpreter = funcEnv.interpreter
    stateStruct = interpreter.globalScope.stateStruct
    while isinstance(objType, CTypedef):
        objType = objType.type

    typeAst = getAstNodeForVarType(funcEnv, objType)
    assert isinstance(argAst, ast.Tuple)
    assert len(argAst.elts) == len(argType)

    if isinstance(objType, (CStruct, CUnion)):
        if not objType.body:
            assert objType.name
            if isinstance(objType, CStruct):
                objType = interpreter.globalScope.stateStruct.structs[objType.name]
            elif isinstance(objType, CUnion):
                objType = interpreter.globalScope.stateStruct.unions[objType.name]

        fields = []
        for c in objType.body.contentlist:
            if not isinstance(c, CVarDecl): continue
            fields.append(c)

        if isinstance(objType, CUnion):
            # Only use the first field or the designated field
            idx = 0
            s_arg_ast = None
            s_arg_type = None
            if argType:
                designators, s_arg_type = argType[-1] # last one wins
                s_arg_ast = argAst.elts[-1]
                if designators:
                    # TODO: support multiple designators
                    designator = designators[0]
                    if isinstance(designator, str):
                        for i, field in enumerate(fields):
                            if field.name == designator:
                                idx = i
                                break
                else:
                    idx = 0
            
            if s_arg_ast is not None:
                field = fields[idx]
                _s_arg_ast = _makeVal(funcEnv, field.type, s_arg_ast, s_arg_type)
                # Match the rename done at struct ``_fields_`` time
                # (in ``_getCTypeStruct``) so the kwarg name is a
                # valid Python identifier.
                field_name = py_safe_identifier(str(field.name))
                return makeAstNodeCall(typeAst, **{field_name: _s_arg_ast})
            else:
                return makeAstNodeCall(typeAst)

        # CStruct
        s_args_map = {} # field idx -> (ast, type)
        cur_field_idx = 0
        for i, (designators, s_arg_type) in enumerate(argType):
            s_arg_ast = argAst.elts[i]
            if designators:
                # TODO: support multiple designators
                designator = designators[0]
                if isinstance(designator, str):
                    found = False
                    for idx, field in enumerate(fields):
                        if field.name == designator:
                            cur_field_idx = idx
                            found = True
                            break
                    if not found:
                        stateStruct.error("field %r not found in %r" % (designator, objType))
                else:
                    # [index] designator or similar
                    stateStruct.error("invalid designator %r for struct" % designator)

            s_args_map[cur_field_idx] = (s_arg_ast, s_arg_type)
            cur_field_idx += 1

        s_args_kwargs = {}
        for idx, field in enumerate(fields):
            if idx in s_args_map:
                _s_arg_ast, _s_arg_type = s_args_map[idx]
                _s_arg_ast = _makeVal(funcEnv, field.type, _s_arg_ast, _s_arg_type)
                # Rename to match ``_fields_`` (see ``py_safe_identifier``).
                s_args_kwargs[py_safe_identifier(str(field.name))] = _s_arg_ast
        return makeAstNodeCall(typeAst, **s_args_kwargs)

    elif isinstance(objType, CArrayType):
        arrayLen = None
        if objType.arrayLen:
            arrayLen = getConstValue(stateStruct, objType.arrayLen)

        s_args_map = {} # index -> (ast, type)
        cur_idx = 0
        for i, (designators, s_arg_type) in enumerate(argType):
            s_arg_ast = argAst.elts[i]
            if designators:
                # Per C99 §6.7.8: ``[N] = ...`` sets the current index
                # to N; subsequent initializers without designators
                # continue from there.  Real-world hit:
                # ast_opt.c::fold_unaryop's ``static const unary_op
                # ops[] = {[Invert] = ..., [Not] = ..., ...}`` where
                # the enum constants are 1..4 (index 0 is an unused
                # zero-init hole).  Without this, the array is sized
                # by element-count rather than by max-designator+1 and
                # the function-pointer table is off by one -> NULL-call
                # SIGSEGV at runtime when ``compile()`` is invoked.
                # Multiple designators on one initializer (e.g.
                # ``[N].field``) aren't supported yet.
                designator = designators[0]
                v = getConstValue(stateStruct, designator)
                if not isinstance(v, int):
                    stateStruct.error(
                        "array designator %r is not a constant int" % designator)
                else:
                    cur_idx = v
            s_args_map[cur_idx] = (s_arg_ast, s_arg_type)
            cur_idx += 1

        # Re-derive arrayLen from the highest filled index.  The
        # earlier estimate (in ``getAstNode_newTypeInstance``) used
        # ``len(argType)``, which is wrong when designators skip
        # indices.
        if s_args_map:
            needed = max(s_args_map.keys()) + 1
            if arrayLen is None or needed > arrayLen:
                arrayLen = needed
                objType.arrayLen = CNumber(arrayLen)
                typeAst = ast.BinOp(
                    left=getAstNodeForVarType(funcEnv, objType.arrayOf),
                    op=ast.Mult(), right=ast.Num(n=arrayLen))

        s_args = []
        for idx in range(arrayLen):
            if idx in s_args_map:
                _s_arg_ast, _s_arg_type = s_args_map[idx]
                _s_arg_ast = _makeVal(funcEnv, objType.arrayOf, _s_arg_ast, _s_arg_type)
                s_args.append(_s_arg_ast)
            else:
                s_args.append(getAstNode_newTypeInstance(funcEnv, objType.arrayOf))
        return makeAstNodeCall(typeAst, *s_args)

    else:
        assert False, "did not expect type %r for curly braces init" % objType


def _makeVal(funcEnv, f_arg_type, s_arg_ast, s_arg_type):
    interpreter = funcEnv.interpreter
    stateStruct = interpreter.globalScope.stateStruct
    while isinstance(f_arg_type, CTypedef):
        f_arg_type = f_arg_type.type
    while isinstance(s_arg_type, CTypedef):
        s_arg_type = s_arg_type.type

    if isinstance(s_arg_type, (tuple, list)):  # CCurlyArrayArgs
        return getAstNode_curlyArrayArgsInit(funcEnv, f_arg_type, s_arg_ast, s_arg_type)

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
                # C allows fewer initializers than the array length; the
                # remaining elements are zero-initialized.  E.g.
                #   static PyObject *unicode_latin1[256] = {NULL};
                # specifies just one element; the other 255 are zero.
                # getAstNode_curlyArrayArgsInit fills in the gap below.
                assert len(argType) <= arrayLen, \
                    "too many initializers (%d) for array of size %d" % (len(argType), arrayLen)
        else:
            # Handle array type extra here for the case when array-len is not specified.
            assert argType is not None
            if isinstance(argType, (tuple, list)):
                # Common case: no designators -> ``len(argType)``.
                # Designated: ``[N] = ...`` can skip indices, so the
                # array length is max-designator-index + 1.  See
                # _getDeclTypeBodyAstAndType for the full motivation.
                if not any(d for (d, _) in argType):
                    arrayLen = len(argType)
                else:
                    arrayLen = 0
                    cur_idx = 0
                    stateStruct = interpreter.globalScope.stateStruct
                    for designators, _ in argType:
                        if designators:
                            v = getConstValue(stateStruct, designators[0])
                            if isinstance(v, int):
                                cur_idx = v
                        if cur_idx + 1 > arrayLen:
                            arrayLen = cur_idx + 1
                        cur_idx += 1
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
        return getAstNode_curlyArrayArgsInit(funcEnv, objType, argAst, argType)

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
        # We expect a PyRef.  If `argAst` is itself a PyRef pointer
        # (e.g. a copy of an existing `&va_list`), unwrap its `.ref`.
        # Otherwise (e.g. a `NULL`/`0` literal cast as in CPython's
        # `skipitem(&format, NULL, 0)`), construct an empty PyRef --
        # accessing `.ref` on the integer 0 would raise
        # AttributeError.
        src_is_pyref = (isinstance(argType, CPointerType)
                        and usePyRefForType(argType.pointerOf))
        if argAst is not None and src_is_pyref:
            return makeAstNodeCall(getAstNodeAttrib("helpers", "PyRef"),
                                   getAstNodeAttrib(argAst, "ref"))
        return makeAstNodeCall(getAstNodeAttrib("helpers", "PyRef"))

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

    if isinstance(objType, CStdIntType) and objType.name == "wchar_t" and args:
        # c_wchar expects a unicode character string, not an int
        assert len(args) == 1
        args = [makeAstNodeCall(ast.Name(id="chr", ctx=ast.Load()), *args)]
    elif isIntType(objType) and args:
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
        
        if self.funcEnv.interpreter.debug_log_assign:
            a.value = makeAstNodeCall(getAstNodeAttrib("helpers", "logAssign"), ast.Str(varName), a.value)
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
    "/": ast.Div,  # we cast after the div to right type
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

    def _checkAborted(self):
        if self.interpreter.aborted:
            raise InterruptedError("Interpreter aborted")

    def prefixInc(self, a):
        self._checkAborted()
        if self.interpreter.debug_log_assign: print("LOG: prefixInc %r" % a)
        a.value += 1
        return a

    def prefixDec(self, a):
        self._checkAborted()
        if self.interpreter.debug_log_assign: print("LOG: prefixDec %r" % a)
        a.value -= 1
        return a

    def postfixInc(self, a):
        self._checkAborted()
        if self.interpreter.debug_log_assign: print("LOG: postfixInc %r" % a)
        b = self.copy(a)
        a.value += 1
        return b

    def postfixDec(self, a):
        self._checkAborted()
        if self.interpreter.debug_log_assign: print("LOG: postfixDec %r" % a)
        b = self.copy(a)
        a.value -= 1
        return b

    def prefixIncPtr(self, a):
        self._checkAborted()
        if self.interpreter.debug_log_assign: print("LOG: prefixIncPtr %r" % a)
        aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
        aPtr.contents.value += ctypes.sizeof(a._type_)
        return a

    def prefixDecPtr(self, a):
        self._checkAborted()
        if self.interpreter.debug_log_assign: print("LOG: prefixDecPtr %r" % a)
        aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
        aPtr.contents.value -= ctypes.sizeof(a._type_)
        return a

    def postfixIncPtr(self, a):
        self._checkAborted()
        if self.interpreter.debug_log_assign: print("LOG: postfixIncPtr %r" % a)
        b = self.copy(a)
        aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
        aPtr.contents.value += ctypes.sizeof(a._type_)
        return b

    def postfixDecPtr(self, a):
        self._checkAborted()
        if self.interpreter.debug_log_assign: print("LOG: postfixDecPtr %r" % a)
        b = self.copy(a)
        aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
        aPtr.contents.value -= ctypes.sizeof(a._type_)
        return b

    def postfixIncBitfield(self, obj, attr):
        self._checkAborted()
        old = getattr(obj, attr)
        setattr(obj, attr, old + 1)
        return old

    def postfixDecBitfield(self, obj, attr):
        self._checkAborted()
        old = getattr(obj, attr)
        setattr(obj, attr, old - 1)
        return old

    def prefixIncBitfield(self, obj, attr):
        self._checkAborted()
        val = getattr(obj, attr) + 1
        setattr(obj, attr, val)
        return val

    def prefixDecBitfield(self, obj, attr):
        self._checkAborted()
        val = getattr(obj, attr) - 1
        setattr(obj, attr, val)
        return val

    def augAssignBitfield(self, obj, attr, opStr, bValue):
        self._checkAborted()
        val = getattr(obj, attr)
        val = OpBinFuncs[opStr[:-1]](val, bValue)
        setattr(obj, attr, val)
        return val

    def assignBitfield(self, obj, attr, bValue):
        """Like ``assign`` but for bitfields: ctypes won't let us take
        a pointer to a bitfield, so we set the attribute directly.
        Returns ``bValue`` (as a Python int) so chained assignments --
        e.g. ``a->bf1 = a->bf2 = 1;`` -- work."""
        self._checkAborted()
        setattr(obj, attr, bValue)
        return bValue

    def copy(self, a):
        self._checkAborted()
        if isinstance(a, ctypes.c_void_p):
            return ctypes.cast(a, wrapCTypeClass(ctypes.c_void_p))
        if isinstance(a, ctypes._Pointer):
            return ctypes.cast(a, a.__class__)
        if isinstance(a, ctypes.Array):
            if len(a) == 0:
                return ctypes.cast(a, ctypes.POINTER(a._type_))
            return ctypes.pointer(a[0])  # should keep _b_base_
            # This would not:
            # return ctypes.cast(a, ctypes.POINTER(a._type_))
        if isinstance(a, ctypes._SimpleCData):
            # Safe, should not be a pointer.
            return a.__class__(a.value)
        raise NotImplementedError("cannot copy %r" % a)

    def logAssign(self, name, value):
        self._checkAborted()
        if self.interpreter.debug_log_assign:
            print("LOG: assign local %s = %r" % (name, value))
        return value

    def assign(self, a, bValue):
        self._checkAborted()
        if self.interpreter.debug_log_assign:
            print("LOG: assign %r = %r" % (a, bValue))
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
            if isinstance(a, ctypes.c_wchar) and isinstance(bValue, int):
                bValue = chr(bValue)
            a.value = bValue
        else:
            assert False, "assign: not handled: %r of type %r" % (a, type(a))
        return a

    def assignPtr(self, a, bValue):
        self._checkAborted()
        if self.interpreter.debug_log_assign:
            print("LOG: assignPtr %r = 0x%x" % (a, bValue))
        # WARNING: This can be dangerous/unsafe.
        # It will correctly copy the content. However, we might loose any Python obj refs.
        # TODO: Fix this somehow?
        _ctype_ptr_set_value(a, bValue)
        return a

    def getValueGeneric(self, b):
        self._checkAborted()
        if isinstance(b, (ctypes._Pointer, ctypes._CFuncPtr, ctypes.Array, ctypes.c_void_p)):
            self.interpreter._storePtr(b)
        if isinstance(b, (ctypes._Pointer, ctypes._CFuncPtr, ctypes.Array)):
            b = ctypes.cast(b, ctypes.c_void_p)
        if isinstance(b, ctypes.c_wchar):
            return ord(b.value)
        if isinstance(b, (ctypes.c_void_p, ctypes._SimpleCData)):
            b = b.value
            # NULL pointer (.value of c_void_p(None)) -> 0
            if b is None and isinstance(b, type(None)):
                b = 0
        if b is None:
            # ctypes returns None for NULL pointer values; treat as 0
            b = 0
        return b

    def assignGeneric(self, a, bValue):
        self._checkAborted()
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

    def augAssign(self, a, op, bValue):
        self._checkAborted()
        if self.interpreter.debug_log_assign:
            print("LOG: augAssign %r %s %r" % (a, op, bValue))
        if isinstance(a, (ctypes.c_void_p, ctypes._SimpleCData)):
            a.value = OpBinFuncs[op](a.value, bValue)
        else:
            assert False, "augAssign: not handled: %r of type %r" % (a, type(a))
        return a

    def augAssignPtr(self, a, op, bValue):
        self._checkAborted()
        if self.interpreter.debug_log_assign:
            print("LOG: augAssignPtr %r %s %r" % (a, op, bValue))
        # `a` is itself a pointer.
        assert op in ("+=","-=")
        func = OpBinFuncs[op]
        bValue *= ctypes.sizeof(a._type_)
        # Should be safe as long as `a` already contains all the refs.
        aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(ctypes.c_void_p))
        # NULL pointer arithmetic: in C, ``ptr + 0`` is valid even when
        # ``ptr`` is NULL.  ctypes represents a NULL ``c_void_p`` as
        # ``.value == None``; coerce to 0 so ``None + b`` doesn't raise.
        cur = aPtr.contents.value
        if cur is None:
            cur = 0
        aPtr.contents.value = func(cur, bValue)
        a = self.interpreter._storePtr(a, offset=func(0, bValue))
        return a

    def ptrArithmetic(self, a, op, bValue):
        self._checkAborted()
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
            if isinstance(func.C_funcPtr, funcCType):
                return func.C_funcPtr
            return ctypes.cast(func.C_funcPtr, funcCType)
        # Wrap the Python function with its *actual* CFUNCTYPE signature, not the cast target.
        # The ctypes callback is generated from the CFUNCTYPE's argtypes.
        canonical = funcCType
        cfunc = getattr(func, "C_cFunc", None)
        if cfunc is not None:
            stateStruct = self.interpreter._cStateWrapper
            restype = self.fixReturnType(
                getCType(cfunc.type, stateStruct) if cfunc.type is not None else None)
            argtypes = [getCType(a, stateStruct) for a in cfunc.args]
            canonical = get_cfunctype(restype, *argtypes)
        # We store the pointer in the func itself
        # so that it don't get out of scope (because of casts).
        func.C_funcPtr = canonical(func)
        func.C_funcPtrStorage = PointerStorage(ptr=func.C_funcPtr, value=func)
        self.interpreter._storePtr(func.C_funcPtr, value=func.C_funcPtrStorage)
        if isinstance(func.C_funcPtr, funcCType):
            return func.C_funcPtr
        return ctypes.cast(func.C_funcPtr, funcCType)

    def checkedFuncPtrCall(self, f, *args):
        addr = _ctype_ptr_get_value(f)
        if addr == 0:
            raise Exception("checkedFuncPtrCall: tried to call NULL ptr")
        # Normalize args: wrap plain Python ints/None as c_void_p so that
        # ctypes.cast() inside the callee doesn't receive a non-ctypes object.
        def _normalize_arg(arg):
            if arg is None or isinstance(arg, int):
                return ctypes.c_void_p(arg or 0)
            return arg
        args = tuple(_normalize_arg(a) for a in args)
        for arg in args:
            # We might need to store some pointers to local vars here.
            if isinstance(arg, (ctypes.c_void_p, ctypes._Pointer)):
                self.interpreter._storePtr(arg)
        # Short-circuit: if `f` points at one of *our own* Python
        # functions (wrapped earlier by `makeFuncPtr`), call the Python
        # function directly rather than going through the ctypes
        # CFUNCTYPE callback.  Two reasons:
        #  - Exceptions raised inside the Python function propagate to
        #    the caller.  Calling via ctypes prints
        #    "Exception ignored on calling ctypes callback function"
        #    and silently returns NULL/0, hiding real interpreter bugs.
        #  - It avoids the ctypes arg-marshalling round-trip.
        # If the pointer is anything else (real libc, an unregistered
        # address, etc.), fall back to the normal ctypes call.
        obj = self.interpreter.pointerStorage.get(addr)
        if isinstance(obj, PointerStorage):
            py_func = obj.valueRef()
            if py_func is not None and inspect.isfunction(py_func):
                # Truncate `args` to the Python function's actual declared
                # argument count.  Real C ignores extra args via the
                # calling convention (e.g. METH_NOARGS calls a 1-arg
                # `dictitems_new(PyObject*)` as `meth(self, NULL)`), and
                # we must do the same -- otherwise the Python function
                # raises ``TypeError: takes N positional arguments but M
                # were given``.
                py_argtypes = getattr(py_func, "C_argTypes", None)
                if py_argtypes is not None and len(args) > len(py_argtypes):
                    args = args[:len(py_argtypes)]
                result = py_func(*args)
                # The ctypes callback path would have wrapped the Python
                # return value in the CFUNCTYPE's `restype`, so callers
                # uniformly read `.value` on the result.  Match that
                # behaviour for the direct call: wrap a raw Python
                # int/float in `restype` if it isn't already a ctype.
                restype = getattr(type(f), "_restype_", None)
                if restype is not None and not isinstance(result, restype):
                    if result is None:
                        result = restype()
                    else:
                        result = restype(result)
                return result
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

        ``ref`` is optional so we can build a "null" PyRef when C code
        passes `NULL`/`0` where a `va_list *` is expected (e.g.
        CPython's ``skipitem(&format, NULL, 0)`` in getargs.c).

        **Limitation:** A PyRef is purely a Python-level wrapper around
        a :class:`Helpers.VarArgs` instance.  Forwarding it through
        helper chains works as long as each step carries the same
        PyRef object (the AST builder unwraps ``.ref`` when copying a
        PyRef-typed value into another PyRef-typed slot).  But if C
        code stows ``&va_list`` somewhere we cannot trace (e.g. into a
        struct field of pointer-to-something type, then later
        reconstructs a fresh pointer from the raw address), there is
        no way to recover the originating :class:`VarArgs` -- a fresh
        ctypes ``void*`` has no link back to the Python-side wrapper.
        We do not currently need this case for CPython's startup path,
        so it is unsupported.  If a future failure surfaces it, the
        symptom is easy to identify: an :class:`AttributeError` for
        ``.ref`` on a non-PyRef object, or a PyRef appearing where a
        normal ctypes pointer is expected.
        We can rewrite this to use a proper C struct for va_list typedef.
        """
        def __init__(self, ref=None):
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
    assert len(stmnt_args) >= len(required_arg_types), "requires %i args (%r) but got %i args (%r)" % (
        len(required_arg_types), required_arg_types, len(stmnt_args), stmnt_args)
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
        # Field name renamed via ``py_safe_identifier`` to match the
        # ctypes ``_fields_`` definition (which also goes through the
        # rename).  Python reserved words get a trailing underscore.
        a.attr = py_safe_identifier(stmnt.name)
        while isinstance(t, CTypedef):
            t = t.type
        assert isinstance(t, (CStruct,CUnion))
        attrDecl = t.findAttrib(funcEnv.globalScope.stateStruct, stmnt.name)
        assert attrDecl is not None, "attrib %r not found in %r" % (stmnt.name, t)
        if hasattr(attrDecl, "bitsize"):
            return a, CBitfieldType(attrDecl.type)
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
        if isinstance(stmnt.content, float):
            t = CBuiltinType(("double",))
            return getAstNode_newTypeInstance(funcEnv, t, ast.Num(n=stmnt.content)), t
        # Pick the literal type per C99 §6.4.4.1 (suffix + base aware).
        # E.g. ``2147483648`` (decimal, no suffix) is ``int64_t`` --
        # NOT ``uint32_t`` -- so unary-minus stays in signed range and
        # ``INT_MIN`` defined as the literal ``-2147483648`` works.
        t = cIntTypeForLiteral(stmnt.content, stmnt.rawstr)
        if t is None: t = "int64_t" # genuine overflow; just take the largest
        t = CStdIntType(t)
        return getAstNode_newTypeInstance(funcEnv, t, ast.Num(n=stmnt.content)), t
    elif isinstance(stmnt, CEnumConst):
        t = stmnt.parent
        assert isinstance(t, CEnum)
        return getAstNode_newTypeInstance(funcEnv, t, ast.Num(n=stmnt.value)), t
    elif isinstance(stmnt, CWideStr):
        s = str(stmnt.content)
        l = len(s) + 1
        ta = CArrayType(arrayOf=CStdIntType("wchar_t"), arrayLen=CNumber(l))
        ss = makeAstNodeCall(getAstNodeAttrib("intp", "_make_wchar_string"), ast.Str(s=s))
        return ss, ta
    elif isinstance(stmnt, CFuncName):
        # __func__ expands to the name of the enclosing function
        func_name = funcEnv.func.name if (funcEnv and funcEnv.func and funcEnv.func.name) else ""
        s = func_name
        l = len(s) + 1
        ta = CArrayType(arrayOf=CBuiltinType(("char",)), arrayLen=CNumber(l))
        ss = makeAstNodeCall(getAstNodeAttrib("intp", "_make_string"), ast.Str(s=s))
        return ss, ta
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
                # C ``sizeof(expr)`` does NOT actually evaluate ``expr``
                # at runtime -- it yields the *type's* size at compile
                # time.  Special-case the two common pointer-dereference
                # forms ``sizeof(*p)`` and ``sizeof(p[0])``: the generic
                # translation actually dereferences ``p`` and calls
                # ``ctypes.sizeof`` on the result, which raises ``NULL
                # pointer access`` when ``p`` is still NULL (typical
                # for ``p = malloc(sizeof(*p))`` or the bound check
                # ``nargs > PY_SSIZE_T_MAX / sizeof(stack[0]) - ...``
                # in Objects/call.c::_PyStack_UnpackDict).  Detect
                # both forms and resolve via the pointee type.
                deref_operand = None
                # Form 1: ``sizeof(*p)`` -- prefix-`*` expression.
                if (a._op is not None and a._op.content == "*"
                        and a._leftexpr is None
                        and a._rightexpr is not None):
                    deref_operand = a._rightexpr
                # Form 2: ``sizeof(p[0])`` -- array-index ref.
                elif (a._op is None and a._rightexpr is None
                        and isinstance(a._leftexpr, CArrayIndexRef)):
                    deref_operand = a._leftexpr.base
                if deref_operand is not None:
                    _, operandType = astAndTypeForStatement(funcEnv, deref_operand)
                    # Unwrap CTypedef.
                    while isinstance(operandType, CTypedef):
                        operandType = operandType.type
                    pointeeType = None
                    if isinstance(operandType, CPointerType):
                        pointeeType = operandType.pointerOf
                    elif isinstance(operandType, CArrayType):
                        pointeeType = operandType.arrayOf
                    if pointeeType is not None:
                        t = getCType(pointeeType, funcEnv.globalScope.stateStruct)
                        if t is not None:
                            s = ctypes.sizeof(t)
                            sizeAst = makeAstNodeCall(
                                getAstNodeAttrib("ctypes_wrapped", "c_size_t"),
                                ast.Num(s))
                            return sizeAst, CStdIntType("size_t")
                # General case: evaluate and take ``ctypes.sizeof`` on
                # the value.  This is correct for ``sizeof(arr)`` where
                # ``arr`` is a fixed-size array variable (ctypes array
                # instance has the real array size), and for any other
                # well-defined value expression.
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
        elif isinstance(stmnt.base, COffsetofSymbol):
            assert len(stmnt.args) == 2
            base = stmnt.args[0]
            if isinstance(base, CStatement):
                assert base.isCType(), "offsetof: unknown struct type %r" % stmnt.args[0]
                base = base.asType()
            offset = 0
            for field_name in _offsetofFieldChain(stmnt.args[1]):
                while isinstance(base, CTypedef):
                    base = base.type
                assert isinstance(base, (CStruct, CUnion)), "offsetof: %r is not a struct/union" % base
                struct_t = getCType(base, funcEnv.globalScope.stateStruct)
                assert struct_t is not None, "offsetof: unknown struct type %r" % base
                # ``py_safe_identifier`` renames Python keywords/soft-
                # keywords (e.g. ``type`` -> ``type_``) on the ctypes
                # struct side; apply the same mapping for the lookup.
                py_field_name = py_safe_identifier(field_name)
                field_desc = getattr(struct_t, py_field_name, None)
                assert field_desc is not None, "offsetof: field %r not found in %r" % (field_name, struct_t)
                offset += field_desc.offset
                sub = base.findAttrib(funcEnv.globalScope.stateStruct, field_name)
                assert isinstance(sub, CVarDecl), "offsetof: field %r not found in %r" % (field_name, base)
                base = sub.type
            offsetAst = makeAstNodeCall(getAstNodeAttrib("ctypes_wrapped", "c_size_t"), ast.Num(offset))
            return offsetAst, CStdIntType("size_t")
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
            if isinstance(resolveTypedef(aType), CFuncPointerDecl) and len(stmnt.args) == 1:
                stmnt.args = [_stripFuncPtrCastArtifact(stmnt.args[0])]
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
            if isinstance(pType, CWrapFuncType):
                # CWrapFuncType is produced for plain CFunc references,
                # including a ternary like `cond ? funcA : funcB` whose branches are both CFuncs.
                # Generate plain Python call rather than going through checkedFuncPtrCall.
                a = ast.Call(keywords=[], starargs=None, kwargs=None)
                a.func = pAst
                a.args = autoCastArgs(funcEnv, [f_arg.type for f_arg in pType.func.args], stmnt.args)
                rettype = pType.func.type
                if rettype in (CBuiltinType(("void",)), CVoidType()):
                    return a, rettype
                return getAstNode_newTypeInstance(funcEnv, rettype, a), rettype
            if not isinstance(pType, CFuncPointerDecl):
                raise Exception("Func ptr call: base %r is not a func ptr, got %r" % (stmnt.base, pType))
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
        # Unwrap CTypedef so e.g. ``bitset`` (typedef for ``char *``)
        # is recognized as a pointer here -- otherwise subscripting a
        # value of typedef'd pointer type was being mis-classified as
        # the type-array form (``T[N]``).
        _aType_resolved = aType
        while isinstance(_aType_resolved, CTypedef):
            _aType_resolved = _aType_resolved.type
        if isinstance(_aType_resolved, (CPointerType, CArrayType)) and not isType(stmnt.base):
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
        elif isType(aType):
            assert len(stmnt.args) == 1
            resType = CArrayType(arrayOf=aType, arrayLen=stmnt.args[0])
            return getAstNodeForVarType(funcEnv, resType), resType
        else:
            assert False, "invalid array access to type %r" % aType
    elif isinstance(stmnt, CWrapValue):
        v = getAstForWrapValue(funcEnv.globalScope.interpreter, stmnt)
        # Keep in sync with getAstNode_valueFromObj().
        return getAstNodeAttrib(v, "value"), stmnt.getType()
    elif isinstance(stmnt, CCurlyArrayArgs):
        elts = [astAndTypeForStatement(funcEnv, s) for s in stmnt.args]
        a = ast.Tuple(elts=tuple([e[0] for e in elts]), ctx=ast.Load())
        # Return a list of (designators, type)
        return a, [(getattr(s, "designators", []), e[1]) for s, e in zip(stmnt.args, elts)]
    elif isinstance(stmnt, (CType, CTypedef)):
        return getAstNodeForVarType(funcEnv, stmnt), stmnt
    else:
        assert False, "cannot handle " + str(stmnt)

def getAstNode_assign(stateStruct, aAst, aType, bAst, bType):
    if isPointerType(bType):
        bAst = makeAstNodeCall(getAstNodeAttrib("intp", "_storePtr"), bAst)
    bValueAst = getAstNode_valueFromObj(stateStruct, bAst, bType, isPartOfCOp=True)
    if isinstance(aType, CBitfieldType):
        # Bitfields must go through a helper because ctypes does not
        # support taking a pointer to a bitfield (which helpers.assign
        # needs).  Use an EXPRESSION form -- ``helpers.assignBitfield(
        # obj, attr, value)`` -- so chained assignments like
        # ``a->bf1 = a->bf2 = 1;`` translate as a nested call rather
        # than an ``ast.Assign`` statement (which is not a valid
        # expression and trips a SyntaxError in our translator).
        assert isinstance(aAst, ast.Attribute), \
            "bitfield target must be an Attribute access, got %r" % aAst
        return makeAstNodeCall(
            getAstNodeAttrib("helpers", "assignBitfield"),
            aAst.value, ast.Str(s=aAst.attr), bValueAst)
    if isPointerType(aType, alsoFuncPtr=True):
        return makeAstNodeCall(Helpers.assignPtr, aAst, bValueAst)
    return makeAstNodeCall(Helpers.assign, aAst, bValueAst)

def getAstNode_augAssign(stateStruct, aAst, aType, opStr, bAst, bType):
    opAst = ast.Str(opStr)
    if isPointerType(bType):
        bAst = makeAstNodeCall(getAstNodeAttrib("intp", "_storePtr"), bAst)
    bValueAst = getAstNode_valueFromObj(stateStruct, bAst, bType)
    if isinstance(aType, CBitfieldType):
        assert isinstance(aAst, ast.Attribute)
        return makeAstNodeCall(getAstNodeAttrib("helpers", "augAssignBitfield"), aAst.value, ast.Str(s=aAst.attr), opAst, bValueAst)
    if isPointerType(aType):
        return makeAstNodeCall(Helpers.augAssignPtr, aAst, opAst, bValueAst)
    return makeAstNodeCall(Helpers.augAssign, aAst, opAst, bValueAst)

def getAstNode_prefixInc(aAst, aType):
    if isinstance(aType, CBitfieldType):
        assert isinstance(aAst, ast.Attribute)
        return makeAstNodeCall(getAstNodeAttrib("helpers", "prefixIncBitfield"), aAst.value, ast.Str(s=aAst.attr))
    if isPointerType(aType):
        return makeAstNodeCall(Helpers.prefixIncPtr, aAst)
    return makeAstNodeCall(Helpers.prefixInc, aAst)

def getAstNode_prefixDec(aAst, aType):
    if isinstance(aType, CBitfieldType):
        assert isinstance(aAst, ast.Attribute)
        return makeAstNodeCall(getAstNodeAttrib("helpers", "prefixDecBitfield"), aAst.value, ast.Str(s=aAst.attr))
    if isPointerType(aType):
        return makeAstNodeCall(Helpers.prefixDecPtr, aAst)
    return makeAstNodeCall(Helpers.prefixDec, aAst)

def getAstNode_postfixInc(aAst, aType):
    if isinstance(aType, CBitfieldType):
        # Tricky in AST, but usually s->a++ is rare.
        # We'll use a lambda wrapper if needed, but for now let's just support it via a helper
        # that takes the object and the attribute name.
        # But aAst is already an Attribute node.
        assert isinstance(aAst, ast.Attribute)
        return makeAstNodeCall(getAstNodeAttrib("helpers", "postfixIncBitfield"), aAst.value, ast.Str(s=aAst.attr))
    if isPointerType(aType):
        return makeAstNodeCall(Helpers.postfixIncPtr, aAst)
    return makeAstNodeCall(Helpers.postfixInc, aAst)

def getAstNode_postfixDec(aAst, aType):
    if isinstance(aType, CBitfieldType):
        assert isinstance(aAst, ast.Attribute)
        return makeAstNodeCall(getAstNodeAttrib("helpers", "postfixDecBitfield"), aAst.value, ast.Str(s=aAst.attr))
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
        # Field is renamed via ``py_safe_identifier`` on the ctypes
        # side (e.g. ``type`` -> ``type_`` because of the Python soft
        # keyword); apply the same mapping for the lookup.
        field = getattr(c_type, py_safe_identifier(k))
        offset += field.offset
        sub = base.findAttrib(stateStruct, k)
        assert isinstance(sub, CVarDecl)
        base = sub.type
    return offset

def _offsetofFieldChain(field_node):
    field_node = _resolveSingleStatement(field_node)
    chain = []
    while isinstance(field_node, CAttribAccessRef):
        chain = [field_node.name] + chain
        field_node = _resolveSingleStatement(field_node.base)
    if hasattr(field_node, "name"):
        chain = [field_node.name] + chain
    elif hasattr(field_node, "content"):
        chain = [field_node.content] + chain
    else:
        chain = [str(field_node)] + chain
    return chain

def makeFuncPtrValue(argAst, argType):
    assert isinstance(argType, CWrapFuncType)
    v = getAstNode_newTypeInstance(argType.funcEnv, CBuiltinType(("void", "*")), argAst, argType)
    astValue = getAstNodeAttrib(v, "value")
    return ast.BoolOp(op=ast.Or(), values=[astValue, ast.Num(0)])

def _stripFuncPtrCastArtifact(stmnt):
    """Unwrap parser artifacts from casts such as ``(wrapperfunc)(void(*)(void))f``."""
    if isinstance(stmnt, CStatement):
        stripped = _stripFuncPtrCastArtifact(stmnt._leftexpr)
        if stripped is not stmnt._leftexpr:
            s = CStatement()
            s._leftexpr = stripped
            return s
        return stmnt
    if isinstance(stmnt, CFuncCall) and len(stmnt.args) == 1:
        return _stripFuncPtrCastArtifact(stmnt.args[0])
    return stmnt

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
            ptrAst = makeAstNodeCall(getAstNodeAttrib("ctypes", "pointer"), rightAstNode)
            return makeAstNodeCall(getAstNodeAttrib("intp", "_storePtr"), ptrAst), CPointerType(rightType)
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
            if stmnt._op.content == "!":
                resType = ctypes.c_int
            else:
                resType = rightType
            return getAstNode_newTypeInstance(funcEnv, resType, a), resType
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
        # C ``&&`` / ``||`` always yield ``int`` (0 or 1); Python's
        # ``and`` / ``or`` short-circuit and yield the *value* of the
        # last evaluated operand.  For floats: ``v.value and c_int(...)``
        # returns the float ``v.value`` when falsy, which then fails to
        # wrap in ``c_int``.  Coerce each operand to ``bool`` so the
        # BoolOp result is always a Python bool (True/False), which
        # ``ctypes.c_int(...)`` accepts as 1/0.
        a = ast.BoolOp()
        a.op = OpBinBool[stmnt._op.content]()
        a.values = [
            makeAstNodeCall(
                ast.Name(id="bool", ctx=ast.Load()),
                getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, leftAstNode, leftType, isPartOfCOp=True)),
            makeAstNodeCall(
                ast.Name(id="bool", ctx=ast.Load()),
                getAstNode_valueFromObj(funcEnv.globalScope.stateStruct, rightAstNode, rightType, isPartOfCOp=True))]
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
    elif isPointerType(leftType) and stmnt._op.content in ("+", "-"):
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
    _pushLoopContext(funcEnv, ("loop",))
    if stmnt.body is not None:
        cCodeToPyAstList(funcEnv, stmnt.body)
    if not whileAst.body: whileAst.body.append(ast.Pass())
    _popLoopContext(funcEnv)
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
        init = stmnt.args[0]
        # Multi-declarator for-init -- ``for (T a = 0, b = 1; ...)`` --
        # arrives as a list bundled by cpre3_parse_statements_in_brackets.
        # Unpack and emit each declarator separately.
        if isinstance(init, list):
            for sub in init:
                cStatementToPyAst(funcEnv, sub)
        else:
            cStatementToPyAst(funcEnv, init)

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
    _pushLoopContext(funcEnv, ("loop",))
    if stmnt.body is not None:
        cCodeToPyAstList(funcEnv, stmnt.body)
    _popLoopContext(funcEnv)
    funcEnv.popScope() # whileAst / main for-body

    funcEnv.popScope() # ifAst
    return ifAst

class _DoWhileFlowRewriter(ast.NodeTransformer):
    """Rewrite top-level C `continue` / `break` inside a do-while body
    so they cooperate with the surrounding `while True: for _ in (0,): ...`
    translation (see :func:`astForCDoWhile`):

    - Python `continue` (= C `continue`) inside the body must fall through
      to the condition test at the bottom of the outer `while True:`.
      Wrapping the body in a single-iteration `for _ in (0,):` makes a
      plain Python `continue` exit the for naturally and fall through to
      the condition test, so no rewrite is needed for `continue` here --
      it works because the `continue` now targets the innermost (inner)
      loop.
    - Python `break` (= C `break`) must exit the outer `while True:`
      entirely, not just the inner `for`.  We rewrite top-level breaks
      to set a flag and break the inner for; the outer while then checks
      the flag and breaks too.

    Both rewrites must NOT descend into nested loops -- breaks/continues
    inside nested for/while target those loops, not the do-while.
    """
    def __init__(self, flag_name):
        self.flag_name = flag_name
    def visit_For(self, node):
        return node  # do not descend
    def visit_While(self, node):
        return node  # do not descend
    def visit_AsyncFor(self, node):
        return node  # do not descend
    def visit_Break(self, node):
        return [
            ast.Assign(
                targets=[ast.Name(id=self.flag_name, ctx=ast.Store())],
                value=ast.Name(id="True", ctx=ast.Load())),
            ast.Break(),
        ]


def astForCDoWhile(funcEnv, stmnt):
    assert isinstance(stmnt, CDoStatement)
    assert isinstance(stmnt.whilePart, CWhileStatement)
    assert stmnt.whilePart.body is None
    assert len(stmnt.args) == 0
    assert len(stmnt.whilePart.args) == 1
    assert isinstance(stmnt.whilePart.args[0], CStatement)

    # In C, `continue` inside a do-while jumps to the condition test --
    # which may have side effects (e.g. `(++p)->offset == offset`).
    # A naive `while True: <body>; if cond: continue else: break` makes
    # a C-continue (= Python continue) jump to the top of `while True:`,
    # skipping the condition test entirely.  Wrap the body in a
    # single-iteration inner `for _ in (0,):` so Python continue exits
    # the for and falls through to the condition test.  Top-level
    # C-break must still exit the outer while, so we rewrite it via a
    # flag.
    flag_name = funcEnv.registerNewUnscopedVarName("dw_break", initNone=False)

    body_block = []
    funcEnv.pushScope(body_block)
    _pushLoopContext(funcEnv, ("loop",))
    if stmnt.body is not None:
        cCodeToPyAstList(funcEnv, stmnt.body)
    _popLoopContext(funcEnv)
    funcEnv.popScope()

    rewriter = _DoWhileFlowRewriter(flag_name)
    body_block = [rewriter.visit(stmt) for stmt in body_block]
    # NodeTransformer may return a list; flatten.
    flat_body = []
    for stmt in body_block:
        if isinstance(stmt, list):
            flat_body.extend(stmt)
        else:
            flat_body.append(stmt)

    innerLoop = ast.For(
        target=ast.Name(id="_dowhile_once", ctx=ast.Store()),
        iter=ast.Tuple(elts=[ast.Num(n=0)], ctx=ast.Load()),
        body=flat_body or [ast.Pass()],
        orelse=[])

    whileAst = ast.While(body=[], orelse=[], test=ast.Name(id="True", ctx=ast.Load()))
    whileAst.body.append(
        ast.Assign(
            targets=[ast.Name(id=flag_name, ctx=ast.Store())],
            value=ast.Name(id="False", ctx=ast.Load())))
    whileAst.body.append(innerLoop)
    whileAst.body.append(
        ast.If(
            test=ast.Name(id=flag_name, ctx=ast.Load()),
            body=[ast.Break()],
            orelse=[]))

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

def _pushLoopContext(funcEnv, entry):
    """Track enclosing C control structures (loops and switches) so that
    ``CContinueStatement`` knows whether to emit a plain Python
    ``continue`` (real loop on top) or a marker-set + break (switch on
    top, because Python ``continue`` would re-iterate the switch's
    inner ``while True``).

    Entry is either ``("loop",)`` or ``("switch", marker_var_name)``."""
    if not hasattr(funcEnv, "_cLoopStack"):
        funcEnv._cLoopStack = []
    funcEnv._cLoopStack.append(entry)


def _popLoopContext(funcEnv):
    funcEnv._cLoopStack.pop()


def _topLoopContext(funcEnv):
    stack = getattr(funcEnv, "_cLoopStack", None)
    return stack[-1] if stack else None


def _astForCContinue(funcEnv):
    """Return the list of AST statements implementing a C ``continue``
    at the current loop/switch context.

    - Real loop on top of the context stack: plain Python ``continue``.
    - Switch on top: set the switch's marker var and ``break`` out of
      the switch's inner ``while True``; the post-switch code emits
      ``if marker: <continue-for-the-outer-context>`` to propagate.
    - Empty stack (continue outside any loop -- illegal in C, but the
      parser may still produce it): empty list, no-op.
    """
    top = _topLoopContext(funcEnv)
    if top is None:
        return []
    if top[0] == "loop":
        return [ast.Continue()]
    if top[0] == "switch":
        marker = top[1]
        return [
            ast.Assign(
                targets=[ast.Name(id=marker, ctx=ast.Store())],
                value=ast.Name(id="True", ctx=ast.Load())),
            ast.Break(),
        ]
    raise ValueError("unknown loop context: %r" % (top,))


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

    # Marker for "C ``continue`` inside this switch body wants to skip
    # to the next iteration of the *outer* loop", not re-iterate the
    # switch's internal ``while True``.  Initialised to False; case
    # bodies that contain a C ``continue`` set it to True and break
    # out of the inner while.  After the inner while we check the
    # marker and emit a real Python ``continue`` so the outer loop
    # advances.
    continueMarkerName = funcEnv.registerNewVar("_switch_continue_outer")
    a = ast.Assign()
    a.targets = [ast.Name(id=continueMarkerName, ctx=ast.Store())]
    a.value = ast.Name(id="False", ctx=ast.Load())
    funcEnv.getBody().append(a)

    # use 'while' AST so that we can just use 'break' as intended
    whileAst = ast.While(body=[], orelse=[], test=ast.Name(id="True", ctx=ast.Load()))
    funcEnv.getBody().append(whileAst)
    funcEnv.pushScope(whileAst.body)
    _pushLoopContext(funcEnv, ("switch", continueMarkerName))

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
    _popLoopContext(funcEnv)
    funcEnv.popScope()

    # If a case body set the marker (= executed a C ``continue``),
    # propagate it according to the *now-current* loop context: the
    # enclosing real loop gets a Python ``continue``; an enclosing
    # switch gets its own marker+break; no enclosing loop gets a no-op
    # (C would have rejected such a ``continue`` anyway).
    propagateBody = _astForCContinue(funcEnv)
    if propagateBody:
        funcEnv.getBody().append(ast.If(
            test=ast.Name(id=continueMarkerName, ctx=ast.Load()),
            body=propagateBody,
            orelse=[]))

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
        # C function-local `static` variables (e.g. `_Py_IDENTIFIER(__eq__)`
        # which expands to `static _Py_Identifier PyId___eq__ = ...` inside
        # a function body) have function scope but program lifetime -- their
        # storage must persist across calls, not be re-created on every
        # entry.  We promote them to global storage with a unique mangled
        # name (`<funcname>__<varname>`) so the same ctypes object is
        # materialised once on first use and re-used thereafter.  Without
        # this, a function-local static would be initialised fresh on every
        # call; in CPython source, the static-strings linked list inside
        # `_PyUnicode_FromId` then ends up pointing at the *previous*
        # call's temporary identifier (now GC'd), and subsequent lookups
        # see a dangling pointer.
        if (isinstance(c, CVarDecl)
                and "static" in getattr(c, "attribs", ())
                and id(c) not in funcEnv.globalScope.names):
            mangled = "%s__%s" % (funcEnv.get_name(), c.name)
            funcEnv.globalScope.identifiers[mangled] = c
            funcEnv.globalScope.names[id(c)] = mangled
            # The CVarDecl is now visible as a global; references inside the
            # function body resolve through getAstNodeForVarDecl ->
            # findName -> "g.<mangled>".  No local-variable assignment.
        else:
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
        body.extend(_astForCContinue(funcEnv))
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
    elif isinstance(c, (CStruct, CUnion, CEnum)):
        funcEnv.registerLocalType(c)
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
    from .py_demo_unparse import Unparser
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

def _ctype_collect_objects(obj, include_objects_dict=True, target_addr=None):
    """Collect ctypes that ``obj`` keeps alive, transitively.

    :param ctypes._CData obj: ctypes obj.
    :param bool include_objects_dict: if False, walk only the
        ``_b_base_`` chain (cheap; covers struct-field / array-index /
        typed-cast sub-views).  If True (default), also descend into
        ``_objects`` -- needed to find the buffer behind a
        ``cast(x, T)`` whose ``_b_base_`` is detached from x.  Callers
        that only care about "which buffer does this ctype's memory
        live in" can use False as a fast path and fall back to True
        if no match is found.
    :param int|None target_addr: if given, ctype entries reached
        through an ``_objects`` dict are filtered: only entries whose
        own memory range
        ``[addressof(e), addressof(e) + sizeof(e)]``
        contains ``target_addr`` are kept (the ``cast(x, T)`` case
        -- cast result and source share the same target address;
        the caller is searching for that address).  Entries reached
        through ``_b_base_`` are always kept (sub-views share memory
        with their base by definition; the caller checks the range
        on the collected object anyway).  This avoids materializing
        the many unrelated keep-alive entries that ``_objects`` can
        accumulate (eg. ``c_char_p`` field buffers).

    Notes on ``_CData`` attribs:
    ``_b_base_`` is a counted-ref to a base ``_CData`` that **shares
    memory** with ``obj`` -- e.g. ``obj`` is a field/element of
    ``_b_base_``.

    ``_objects`` is a dict of counted-refs to external objects
    ``obj`` depends on -- e.g. the source of a ``cast(x, T)``
    (which may share memory with the cast result), or a string
    whose buffer is referenced by a ``c_char_p`` field (which does
    NOT share memory with the struct holding the field).  So
    ``_objects`` is *mostly* used to keep cast sources alive (the
    memory-sharing case ``_b_base_`` cannot model) and to keep
    external buffers alive (no memory sharing).  Counted-ref as
    opposed to weak-ref, i.e. as long as ``obj`` lives, all the
    referenced objects live too.
    """
    d = OrderedDict()  # id(o) -> o
    seen_generic = set()
    def in_target_range(o):
        if target_addr is None:
            return True
        # Only ctype objects have a meaningful address+size.
        # ``_CData`` is the common base of all ctypes objects but is
        # only exposed via the MRO, not as a public ``ctypes`` attr.
        # Guard with a duck-type check so non-ctype entries
        # (eg. ``CThunkObject``) pass through unchanged.
        if not hasattr(o, "_b_base_") or not hasattr(o, "_objects"):
            return True
        # Pointer objects: their own ``addressof`` is the pointer cell
        # (Python heap), not the pointed-to data.  Can't usefully
        # range-check those without dereferencing.  Always keep so we
        # can traverse onward via their ``_b_base_`` / ``_objects``
        # chain to reach the memory-sharing buffer behind them
        # (eg. ``cast(arr, POINTER(c_char))`` chains).
        if isinstance(o, (ctypes._Pointer, ctypes._CFuncPtr)):
            return True
        # Walk the ``_b_base_`` chain (memory-sharing ancestors).  If
        # ``o`` or any ancestor contains ``target_addr``, keep the
        # entry.  Without this, a small sub-view like ``a[0]`` (size 4)
        # would be pruned even though traversing through its
        # ``_b_base_`` would reach the parent array ``a`` whose range
        # covers ``target_addr``.
        cur = o
        while cur is not None:
            cur_addr = ctypes.addressof(cur)
            cur_size = ctypes.sizeof(cur)
            if cur_addr <= target_addr <= cur_addr + cur_size:
                return True
            cur = getattr(cur, "_b_base_", None)
        return False
    def collect(o, filter_range):
        if o is None: return
        if id(o) in d: return
        if not hasattr(o, "_objects"): return
        if filter_range and not in_target_range(o):
            return
        d[id(o)] = o
        visit_c(o)
    def visit_generic(o):
        # Generic walk of an ``_objects`` value (could be a ctype, a
        # dict of nested keep-alives, a tuple, a string, etc.).  Leaf
        # ctype entries reached here are filtered by ``target_addr``.
        if o is None:
            return
        obj_id = id(o)
        if obj_id in seen_generic:
            return
        seen_generic.add(obj_id)
        if isinstance(o, dict):
            for s in o.values():
                visit_generic(s)
        elif isinstance(o, (tuple, list, set, frozenset)):
            for s in o:
                visit_generic(s)
        elif isinstance(o, str):
            pass
        else:
            collect(o, filter_range=True)
    def visit_c(b):
        # Usually, we get a ctypes object with _objects and _b_base_ here.
        # However, sometimes get ctypes.CThunkObject here which does not have these attribs.
        if include_objects_dict:
            visit_generic(b._objects)
        # ``_b_base_`` shares memory with ``b`` by definition, so the
        # range filter (if any) is implicitly satisfied -- skip it.
        collect(b._b_base_, filter_range=False)
    # The root ``obj`` itself is always included (the caller passed it
    # in and will inspect it).
    collect(obj, filter_range=False)
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


def _build_ctypes_int_ranges():
    names = (
        "c_byte", "c_ubyte", "c_short", "c_ushort", "c_int", "c_uint",
        "c_long", "c_ulong", "c_longlong", "c_ulonglong",
        "c_int8", "c_int16", "c_int32", "c_int64",
        "c_uint8", "c_uint16", "c_uint32", "c_uint64",
        "c_size_t", "c_ssize_t",
    )
    result = {}
    for n in names:
        t = getattr(ctypes, n, None)
        if t is None:
            continue
        bits = ctypes.sizeof(t) * 8
        if t(-1).value == -1:
            result[n] = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1)
        else:
            result[n] = (0, (1 << bits) - 1)
    return result


_CTYPES_INT_RANGES = _build_ctypes_int_ranges()
_CTYPES_INT_TYPE_NAMES = frozenset(_CTYPES_INT_RANGES)


def _is_int_literal_num(node):
    """``ast.Num(n=int)`` or ``ast.Constant(value=int)``."""
    if isinstance(node, ast.Num) and isinstance(node.n, int):
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, int) \
            and not isinstance(node.value, bool):
        return True
    return False


def _num_value(node):
    if isinstance(node, ast.Num):
        return node.n
    return node.value


def _is_ctypes_int_wrap_call(node):
    """Match ``ctypes_wrapped.c_<int-type>(<arg>)``.

    Returns ``(type_name, arg_ast)`` if matched, else ``None``.
    """
    if not (isinstance(node, ast.Call)
            and len(node.args) == 1
            and not node.keywords):
        return None
    f = node.func
    if not (isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "ctypes_wrapped"
            and f.attr in _CTYPES_INT_TYPE_NAMES):
        return None
    return f.attr, node.args[0]


def _is_int_call(node):
    """Match ``int(<arg>)``.  Returns the arg or None."""
    if not (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and len(node.args) == 1
            and not node.keywords):
        return None
    return node.args[0]


class _PeepholeOptimizer(ast.NodeTransformer):
    """Collapse the most common verbose patterns the generic translator
    produces.

    Generated code wraps and re-extracts ctypes-int values everywhere::

        ctypes_wrapped.c_int(int(<x>)).value

    For literal ``<x>`` this is pure overhead -- a per-evaluation
    allocation of a ctype instance just to read ``.value`` back out.
    This pass collapses the obvious cases.

    Implemented patterns (applied bottom-up via ``ast.NodeTransformer``):

    1. ``int(N)`` where ``N`` is an int literal -> ``N``.
    2. ``int(int(X))`` -> ``int(X)``.
    3. ``ctypes_wrapped.c_T(N).value`` where ``N`` is an int literal
       that fits in ``c_T``'s value range -> ``N``.
    4. ``ctypes_wrapped.c_T(c_T(X).value).value`` (same ``T``) ->
       ``c_T(X).value`` (idempotent wrap).

    Crucially we do *not* drop the wrap when the inner value's range
    is unknown -- ``c_uint16(...)`` truncates and that is observable.
    """

    def visit_Call(self, node):
        self.generic_visit(node)
        # int(<int-literal>) -> <int-literal>
        arg = _is_int_call(node)
        if arg is not None:
            if _is_int_literal_num(arg):
                return arg
            # int(int(X)) -> int(X)
            inner = _is_int_call(arg)
            if inner is not None:
                node.args[0] = inner
                return node
            # int(c_T(...).value) -> c_T(...).value (already an int).
            if isinstance(arg, ast.Attribute) and arg.attr == "value":
                if _is_ctypes_int_wrap_call(arg.value) is not None:
                    return arg
        # c_T(c_T(X).value) -> c_T(X)  (same T; the inner wrap+.value
        # already produced a value already-truncated to T's range, so
        # wrapping it again in c_T is the identity).
        outer = _is_ctypes_int_wrap_call(node)
        if outer is not None:
            outer_t, outer_arg = outer
            if isinstance(outer_arg, ast.Attribute) and outer_arg.attr == "value":
                inner = _is_ctypes_int_wrap_call(outer_arg.value)
                if inner is not None and inner[0] == outer_t:
                    return outer_arg.value
        return node

    def visit_Attribute(self, node):
        self.generic_visit(node)
        # ctypes_wrapped.c_<int>(<arg>).value -> simplified form.
        if node.attr != "value":
            return node
        matched = _is_ctypes_int_wrap_call(node.value)
        if matched is None:
            return node
        type_name, inner_arg = matched
        lo, hi = _CTYPES_INT_RANGES[type_name]
        # Literal that fits exactly in T -> the literal.
        if _is_int_literal_num(inner_arg):
            v = _num_value(inner_arg)
            if lo <= v <= hi:
                return inner_arg
            return node
        # int(<int-literal-that-fits>) -> literal directly (no-op wrap).
        int_call_arg = _is_int_call(inner_arg)
        if int_call_arg is not None and _is_int_literal_num(int_call_arg):
            v = _num_value(int_call_arg)
            if lo <= v <= hi:
                return int_call_arg
        # ``c_T(c_T(X).value).value`` -> ``c_T(X).value`` (same T only).
        if isinstance(inner_arg, ast.Attribute) and inner_arg.attr == "value":
            inner_match = _is_ctypes_int_wrap_call(inner_arg.value)
            if inner_match is not None and inner_match[0] == type_name:
                return inner_arg
        return node


_peephole_optimizer = _PeepholeOptimizer()


class _CtypesWrappedHoister(ast.NodeTransformer):
    """For each ``ast.FunctionDef`` body, replace repeated
    ``ctypes_wrapped.<name>`` attribute loads with a single up-front
    local binding.

    The generated translator emits ``ctypes_wrapped.c_int(...)`` and
    similar all over a function body.  Each occurrence is an
    attribute lookup on the ``ctypes_wrapped`` global.  Binding it
    once to a local at function entry turns subsequent uses into the
    cheapest possible name lookup (``LOAD_FAST``).
    """

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        # Collect names used as ``ctypes_wrapped.<name>`` (Load only).
        used = {}  # ordered: name -> local_alias
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Attribute)
                    and isinstance(sub.ctx, ast.Load)
                    and isinstance(sub.value, ast.Name)
                    and sub.value.id == "ctypes_wrapped"
                    and isinstance(sub.attr, str)
                    and sub.attr.isidentifier()):
                if sub.attr not in used:
                    used[sub.attr] = "__cw_" + sub.attr
        if not used:
            return node
        # Rewrite Attribute loads -> Name loads.
        alias = used
        class _Repl(ast.NodeTransformer):
            def visit_Attribute(self, n):
                self.generic_visit(n)
                if (isinstance(n.ctx, ast.Load)
                        and isinstance(n.value, ast.Name)
                        and n.value.id == "ctypes_wrapped"
                        and n.attr in alias):
                    return ast.Name(id=alias[n.attr], ctx=ast.Load())
                return n
        node.body = [_Repl().visit(s) for s in node.body]
        # Prepend bindings.
        bindings = [
            ast.Assign(
                targets=[ast.Name(id=local, ctx=ast.Store())],
                value=ast.Attribute(
                    value=ast.Name(id="ctypes_wrapped", ctx=ast.Load()),
                    attr=cname, ctx=ast.Load()))
            for cname, local in used.items()
        ]
        node.body = bindings + node.body
        return node


_ctypes_wrapped_hoister = _CtypesWrappedHoister()


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
        # Non-overlapping (start, size) tuples.
        self.pointerStorageRanges = SortedSet()  # (ptr-addr,size) tuples
        # `pointerStorage` may hold multiple keys mapping into the same
        # allocation: the base address plus interior offsets (e.g.
        # `&struct->field`).  When `_free` runs we need to purge every
        # such key without scanning the whole `pointerStorage` (which
        # has many thousand entries in real programs).  This dict
        # tracks, per malloc base address, the set of interior keys
        # registered for it.  Updated whenever `_storePtr`/`_getPtr`
        # register an interior pointer, read by `_free`.
        self.pointerStorageInteriorKeysByBase = {}  # base addr -> set[int]
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
            "intp": self,
            "get_cfunctype": get_cfunctype,
            "get_pointer_type": get_pointer_type,
        }
        self.debug_print_getFunc = False
        self.debug_print_getVar = False
        self.debug_log_assign = False
        self.aborted = False

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
        return getCType(obj, wrappedStateStruct)

    def _abort(self):
        print("C abort() call.")
        raise CAbortException("C abort()")

    def _exit(self, i):
        print("C exit(%i) call." % i)
        sys.exit(i)

    def _make_wchar_string(self, s):
        """
        :param str s:
        :rtype: ctypes array of wrapped c_wchar
        """
        key = ("wchar", s)
        if key in self.constStrings:
            return self.constStrings[key]
        if s is None:
            return self._getPtr(0, ctypes.POINTER(self.ctypes_wrapped.c_wchar))
        t = self.ctypes_wrapped.c_wchar * (len(s) + 1)
        buf = t(*s)
        self.constStrings[key] = buf
        self._storePtr(buf)
        return buf

    def _make_string(self, s):
        """
        :param str s:
        :rtype: ctypes.Array
        """
        if s is None:
            return self._getPtr(0, ctypes.POINTER(ctypes.c_byte))
        if PY3 and isinstance(s, str):
            # C string literals are byte sequences, not Unicode.  An
            # octal/hex escape like ``\340`` is parsed as Python
            # ``'\xE0'`` (codepoint 0xE0) and must be stored as the
            # single byte ``0xE0`` -- not UTF-8 encoded to ``c3 a0``,
            # which would corrupt e.g. ``_PyParser_Grammar``'s
            # ``d_first`` bitsets that pack 8 bits per byte.  Use
            # latin-1 which is a 1:1 codepoint<->byte mapping for
            # 0-255.  C source containing literal UTF-8 multibyte
            # chars is already a sequence of latin-1 chars after the
            # input decode, so this still round-trips correctly.
            s = s.encode("latin-1")
        if s in self.constStrings:
            return self.constStrings[s]
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
            # The existing buffer is big enough -- keep it.
            # We popped it from `mallocs` above; we must re-add it.
            self.mallocs[ptr_addr] = buf
            return ctypes.cast(buf, wrapCTypeClass(ctypes.c_void_p))
        ptr = self._malloc(size)
        ctypes.memmove(ptr, ctypes.cast(buf, wrapCTypeClass(ctypes.c_void_p)), ctypes.c_size_t(buf._length_))
        return ptr

    def _rootAddrOf(self, obj):
        """Walk ``obj._b_base_`` chain to the root ctype and return
        its ``addressof``.  Always returns a concrete address (the
        root's, or obj's own if it is the root).  Callers compare
        against the addr they already have to decide whether interior
        tracking is needed.

        ``obj`` must be a ctype object (one whose chain ends in a
        ctype) -- the obj-loop in ``_storePtr`` only matches ctypes,
        so the precondition always holds at call sites.
        """
        assert hasattr(obj, "_b_base_"), \
            "_rootAddrOf requires a ctype object, got %r" % type(obj)
        root = obj
        while True:
            base = getattr(root, "_b_base_", None)
            if base is None:
                break
            root = base
        return _ctype_get_ptr_addr(root)

    def _registerInteriorPtrKey(self, base_addr, interior_addr):
        """Record that ``pointerStorage[interior_addr]`` references the
        allocation whose base address is ``base_addr``.  Used by
        ``_free`` to purge all interior keys in O(K) on free, instead
        of scanning the entire ``pointerStorage`` dict.  No-op when
        the key is the base itself or when the base hasn't been seen
        before (e.g. registered before any malloc -- harmless, the
        base will simply not have an entry in this map).
        """
        if interior_addr == base_addr:
            return
        s = self.pointerStorageInteriorKeysByBase.get(base_addr)
        if s is None:
            s = set()
            self.pointerStorageInteriorKeysByBase[base_addr] = s
        s.add(interior_addr)

    def _addPointerStorageRange(self, start, size):
        """Insert ``(start, size)`` into ``pointerStorageRanges`` while
        keeping the set non-overlapping.

        Stale entries (whose ``pointerStorage`` weakref is dead --
        the obj has been GC'd) are pruned first.
        After pruning, three real cases remain:

        * **New is contained in an existing range** (``s_pred <= start``,
          ``e_pred >= end``) -- drop new; the outer range already
          covers the same memory.
        * **New strictly contains existing ranges** -- remove the
          contained smaller entries, then add new.
        * **Partial overlap** (edges cross without containment) --
          this is a *bug* (the underlying object layout is
          inconsistent with what we've seen before).

        :param int start: starting address of the new range.
        :param int size: byte length of the new range.
        """
        end = start + size

        # Step 1: prune stale predecessors whose range reaches into
        # the new range.  Loop because removing one may expose another.
        while True:
            i = self.pointerStorageRanges.bisect_right((start + 1, 0))
            if i == 0:
                break
            s, sz = self.pointerStorageRanges[i - 1]
            if s + sz <= start:
                break  # predecessor doesn't reach into new
            if s in self.pointerStorage:
                break  # alive; stop pruning
            self.pointerStorageRanges.remove((s, sz))

        # Step 2: prune stale successors starting in [start, end).
        stale = [
            (s, sz) for s, sz in self.pointerStorageRanges.irange(
                minimum=(start, 0), maximum=(end, 0), inclusive=(True, False))
            if s not in self.pointerStorage
        ]
        for r in stale:
            self.pointerStorageRanges.remove(r)

        # Step 3: containment / overlap logic on the surviving (alive)
        # entries.  Predecessor first.
        i = self.pointerStorageRanges.bisect_right((start + 1, 0))
        if i > 0:
            pred_start, pred_size = self.pointerStorageRanges[i - 1]
            pred_end = pred_start + pred_size
            # ``i - 1`` is the largest entry with first element ``<= start``.
            if pred_end >= end:
                # ``pred_start <= start`` (from bisect_right) and
                # ``pred_end >= end`` => new is fully inside (or equal
                # to) predecessor.  Drop.
                return
            # Strict left partial overlap (predecessor ends inside
            # the new range) is a real bug: the caller is registering
            # a range that disagrees with an alive earlier
            # registration on memory layout.  Assert.
            if pred_end > start > pred_start:
                pred_obj = self.pointerStorage.get(pred_start)
                pred_obj_repr = "%s" % type(pred_obj).__name__ if pred_obj is not None else "<dead>"
                raise AssertionError(
                    "_addPointerStorageRange: partial left overlap; "
                    "new=[0x%x, 0x%x) (size=%d), existing=[0x%x, 0x%x) "
                    "(size=%d, type=%s, overlap=%d bytes).  Both "
                    "ranges' pointerStorage entries are alive -- "
                    "their underlying objs disagree on memory layout." % (
                        start, end, size,
                        pred_start, pred_end, pred_size,
                        pred_obj_repr, pred_end - start))
            # else: predecessor doesn't reach into new, OR same start
            # with smaller end (handled in Step 4 below).

        # Step 4: successors starting in [start, end) -- either fully
        # contained (remove, subsumed by new) or partial right overlap
        # (assert).
        contained_to_remove = []
        for s, sz in self.pointerStorageRanges.irange(
                minimum=(start, 0), maximum=(end, 0), inclusive=(True, False)):
            assert s + sz <= end, (
                "_addPointerStorageRange: partial right overlap; "
                "new=[0x%x, 0x%x) (size=%d), existing=[0x%x, 0x%x) "
                "(size=%d).  Both ranges' pointerStorage entries "
                "are alive -- their underlying objs disagree on "
                "memory layout." % (
                    start, end, size, s, s + sz, sz))
            contained_to_remove.append((s, sz))
        for r in contained_to_remove:
            self.pointerStorageRanges.remove(r)
        self.pointerStorageRanges.add((start, size))

    def _lookupPointerStorageRange(self, addr):
        """Find the ctype object whose ``pointerStorageRanges`` entry
        covers ``addr``, or ``None`` if no such entry exists.

        With the non-overlap invariant maintained by
        ``_addPointerStorageRange``, at most one entry can cover any
        given address: the predecessor (largest start ``<= addr``).
        A single ``bisect_right`` lookup answers the question -- no
        iteration is needed.

        Dead weakrefs at the predecessor are recovered from
        ``mallocs`` when possible (the underlying buffer is still
        alive); otherwise the stale range entry is pruned and the
        function reports no match (no covering range exists -- by
        non-overlap, the predecessor would have been the only
        candidate, and it's gone).

        :param int addr: address to look up.
        :rtype: ctype object | None
        """
        i = self.pointerStorageRanges.bisect_right((addr + 1, 0))
        if i == 0:
            return None
        obj_ptr_addr, obj_size = self.pointerStorageRanges[i - 1]
        # Cover check: inclusive upper bound for the one-past-the-end
        # C pointer (``arr + len`` is a valid pointer for arithmetic).
        if obj_ptr_addr + obj_size < addr:
            return None
        obj = self.pointerStorage.get(obj_ptr_addr, None)
        if obj is None:
            if obj_ptr_addr in self.mallocs:
                obj = self.mallocs[obj_ptr_addr]
                self.pointerStorage[obj_ptr_addr] = obj
            else:
                # Stale: prune the entry; non-overlap means no other
                # range can cover ``addr`` either.
                self.pointerStorageRanges.remove((obj_ptr_addr, obj_size))
                return None
        self._registerInteriorPtrKey(obj_ptr_addr, addr)
        return obj

    def _free(self, ptr_addr):
        """
        :param int ptr_addr:
        """
        if not ptr_addr:
            return  # free(NULL) is a no-op in C
        if ptr_addr not in self.mallocs:
            raise Exception("_free: address 0x%x was not allocated by us" % ptr_addr)
        buf = self.mallocs.pop(ptr_addr)
        # Proactively remove from ranges and storage to avoid leaks.
        # `_storePtr`/`_getPtr` may have registered this buffer at
        # multiple keys in `pointerStorage` -- the base address plus
        # every interior offset they were queried at (e.g.
        # `buf + offsetof(field)`).  We track those interior keys per
        # base in `pointerStorageInteriorKeysByBase`.
        obj_size = ctypes.sizeof(buf)
        self.pointerStorageRanges.discard((ptr_addr, obj_size))
        self.pointerStorage.pop(ptr_addr, None)
        interior_keys = self.pointerStorageInteriorKeysByBase.pop(ptr_addr, ())
        for k in interior_keys:
            self.pointerStorage.pop(k, None)

    def _storePtr(self, ptr, offset=0, value=None):
        """
        We store pointers in ``pointerStorage``.
        We need those because:

        - :func:`_getPtr` reverse lookup, needed for pointer arithmetic
        - Function pointer cells

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
            base_obj = self.pointerStorage[ptr_addr - offset]
            self.pointerStorage[ptr_addr] = base_obj
            # Track the new interior key under the ROOT of `base_obj`,
            # not under `ptr_addr - offset` (which is itself an
            # interior address whose `_free` is never called -- the
            # root's free is what triggers purge).
            if isinstance(base_obj, PointerStorage):
                # Function-pointer cell -- no interior tracking
                # needed (the pointed-to function never gets _free'd).
                pass
            else:
                root_addr = self._rootAddrOf(base_obj)
                if root_addr != ptr_addr:
                    self._registerInteriorPtrKey(root_addr, ptr_addr)
            return ptr
        # Single-pass obj-loop with range check.  Walks `_b_base_` chain
        # and `_objects` (the latter catches `cast(x, T)` style where
        # the source is referenced via the keep-alive dict rather than
        # `_b_base_`).
        # Pass ``target_addr=ptr_addr`` so the ``_objects`` walk is
        # pruned to entries that could plausibly contain ``ptr_addr``
        # (the ``cast(x, T)`` case).  Unrelated keep-alives (eg.
        # ``c_char_p`` buffers held by a struct field) are skipped.
        objs = _ctype_collect_objects(ptr, target_addr=ptr_addr)
        # Later collected objects are more likely the ones we want.
        # So go over in reverse order.
        for obj in reversed(objs):
            obj_ptr_addr = _ctype_get_ptr_addr(obj)
            obj_size = ctypes.sizeof(obj)
            # Range check: ptr is "in" obj iff ptr_addr falls inside
            # `[obj_ptr_addr, obj_ptr_addr + obj_size]`.  Note the
            # inclusive upper bound: C allows "one-past-the-end"
            # pointers (`arr + len(arr)`) as a valid -- if not
            # dereferenceable -- pointer.  This is more lenient than
            # the historical exact equality
            # (`ptr_addr == obj_ptr_addr + offset`) and catches
            # interior pointers we'd otherwise punt to the
            # `pointerStorageRanges` fallback.
            if not (obj_ptr_addr <= ptr_addr <= obj_ptr_addr + obj_size):
                continue
            # Don't overwrite an existing ``pointerStorage`` entry at
            # ``obj_ptr_addr`` with the obj we just walked to.  The
            # side-branch write here is for caching: if a stable entry
            # already lives there (eg. a malloc'd ``c_byte`` buf), a
            # subsequent ``_storePtr`` for a transient struct view at
            # the same address would otherwise replace the stable buf
            # with the view -- which dies shortly after, leaving the
            # entry dead even though ``mallocs`` still holds the
            # underlying memory.  See
            # test_storeptr_obj_loop_does_not_overwrite_malloc_entry.
            if obj_ptr_addr not in self.pointerStorage:
                self.pointerStorage[obj_ptr_addr] = obj
            if obj_ptr_addr != ptr_addr:
                self.pointerStorage[ptr_addr] = obj
            # Track every interior pointerStorage key under the
            # ROOT's address (walking obj's `_b_base_` chain), so
            # that `_free(root_addr)` purges all of them in one
            # pass.  If obj IS the root, this just registers under
            # obj_ptr_addr itself.
            root_addr = self._rootAddrOf(obj)
            if root_addr != obj_ptr_addr:
                self._registerInteriorPtrKey(root_addr, obj_ptr_addr)
            if obj_ptr_addr != ptr_addr:
                self._registerInteriorPtrKey(root_addr, ptr_addr)
            # Only register the range entry if `obj` is a *root* ctype (no `_b_base_`).
            # Sub-views of an existing root are already covered by the root's range,
            # which was added when the root was first stored (eg. by _malloc).
            # We might have not registered it yet (on stack, or static or global; not via _malloc).
            # ``_addPointerStorageRange`` enforces non-overlap: a fresh root
            # whose address lies inside an existing malloc range
            # (eg. a ``from_address`` view into a malloc'd buffer) is
            # dropped -- the outer range already covers it.
            if getattr(obj, "_b_base_", None) is None:
                self._addPointerStorageRange(obj_ptr_addr, obj_size)
            return ptr

        # Range-fallback: with the non-overlap invariant maintained
        # by ``_addPointerStorageRange``, at most one range can
        # possibly cover ``ptr_addr`` -- the predecessor (largest
        # start ``<= ptr_addr``).  A single ``bisect_right`` lookup
        # is enough; no iteration / termination condition needed.
        obj = self._lookupPointerStorageRange(ptr_addr)
        if obj is not None:
            self.pointerStorage[ptr_addr] = obj
            return ptr
        # Last-resort: external pointer (allocated outside our interp,
        # eg. a host CPython PyObject* returned by a host C function
        # the interp dispatched into).  Wrap the unrecognized address
        # in a ``c_byte`` view via ``from_address`` (doesn't take
        # ownership of the underlying memory) and register it in
        # ``pointerStorage`` only (NOT in ``mallocs`` or as a
        # ``pointerStorageRange`` -- those imply we own the buffer
        # and have a known size, neither of which is true for an
        # external address).  Future ``_storePtr`` calls at interior
        # offsets will create their own pointerStorage entries; this
        # is OK because external addresses are typically dereferenced
        # only at specific known offsets.
        placeholder = (ctypes.c_byte * 16).from_address(ptr_addr)
        self.pointerStorage[ptr_addr] = placeholder
        return ptr

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
        if addr in self.pointerStorage:
            obj = self.pointerStorage[addr]
        else:
            # Not found directly; try range-based lookup for interior pointers
            # (e.g. alignment-derived addresses like _Py_ALIGN_DOWN results).
            # See ``_storePtr`` range fallback comment: a single
            # predecessor lookup is enough given the non-overlap
            # invariant on ``pointerStorageRanges``.
            obj = self._lookupPointerStorageRange(addr)
            if obj is not None:
                self.pointerStorage[addr] = obj  # cache for future lookups
            if obj is None:
                # Diagnostic: dump the nearest registered ranges + storage
                # entries so we can see WHY ``addr`` isn't covered.
                ranges = list(self.pointerStorageRanges)
                near = [
                    (s, sz, s + sz)
                    for (s, sz) in ranges
                    if abs(s - addr) < 65536 or abs(s + sz - addr) < 65536
                ]
                near.sort()
                msg = ["invalid pointer access to address 0x%x of type %r"
                       % (addr, ptr_type),
                       "  nearby pointerStorageRanges (within 64KiB):"]
                for s, sz, e in near[:20]:
                    cur = self.pointerStorage.get(s)
                    msg.append("    [0x%x, 0x%x) size=%d obj=%s"
                               % (s, e, sz,
                                  type(cur).__name__ if cur is not None
                                  else "<gone>"))
                raise Exception("\n".join(msg))
        if isinstance(obj, PointerStorage):
            res = obj.ptr
        else:
            ptr = ctypes.pointer(obj)
            ptr_addr = _ctype_ptr_get_value(ptr)
            if ptr_addr != addr:  # might be different if we had an offset in _setPtr
                _ctype_ptr_set_value(ptr, addr)
            res = ptr
        if ptr_type:
            return ctypes.cast(res, ptr_type)
        return res

    def _translateFuncToPyAst(self, func, noBodyMode="warn-empty"):
        assert isinstance(func, CFunc)
        base = FuncEnv(globalScope=self.globalScope)
        assert func.name is not None
        base.func = func
        # ``def`` lines in Python can't use reserved-word names.  If
        # a C function is named e.g. ``lambda`` we'd generate
        # ``def lambda(...):`` which is a SyntaxError.  Rename
        # consistently with ``getAstNodeForVarDecl`` and other access
        # sites.
        base.astNode.name = py_safe_identifier(func.name)
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
        # Apply peephole optimisations to the AST.  The generic
        # translator emits ``ctypes_wrapped.c_int(int(<x>)).value``
        # everywhere -- per-evaluation ctype allocations whose values
        # are immediately discarded.  Collapsing these makes both
        # translation (smaller source) and execution (fewer
        # attribute lookups, allocations) measurably faster.
        _peephole_optimizer.visit(pyAst)
        _ctypes_wrapped_hoister.visit(pyAst)
        ast.fix_missing_locations(pyAst)
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
        :param CStatement|cparser.CControlStructureBase statement:
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
                ptr_of = typ.pointerOf
                while isinstance(ptr_of, CTypedef):
                    ptr_of = ptr_of.type
                if isinstance(ptr_of, CStdIntType) and ptr_of.name == 'wchar_t':
                    return self._make_wchar_string(arg)
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
        timeout = kwargs.pop("timeout", None)
        kwargs = self._runFunc_kwargs_resolve(**kwargs)
        f = self.getFunc(funcname)
        assert len(args) == len(f.C_argTypes)
        args = [self._castArgToCType(arg,typ) for (arg, typ) in zip(args,f.C_argTypes)]
        if timeout is not None and timeout > 0:
            import threading
            _result = [None]
            _exc = [None]
            def _run():
                try:
                    _result[0] = f(*args)
                except (InterruptedError, Exception) as e:
                    _exc[0] = e
            t = threading.Thread(target=_run, daemon=False)
            t.start()
            try:
                t.join(timeout)
            except KeyboardInterrupt:
                self.aborted = True
                t.join()
                raise
            if t.is_alive():
                self.aborted = True
                t.join()
                raise TimeoutError("runFunc %r timed out after %s seconds" % (funcname, timeout))
            if _exc[0] is not None:
                raise _exc[0]
            res = _result[0]
        else:
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


class CAbortException(Exception):
    pass
