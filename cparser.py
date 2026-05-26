#!/usr/bin/env python3

"""
PyCParser main file
by Albert Zeyer, 2011
code under BSD 2-Clause License
"""

from __future__ import print_function
import typing
import ctypes
import _ctypes
from inspect import isclass
from .cparser_utils import unicode, long, unichr, py_safe_identifier

if typing.TYPE_CHECKING:
    from . import globalincludewrappers

SpaceChars = " \t\x0b\x0c"  # space, tab, vertical-tab, form-feed (C99 §5.1.1.2 white space)
LowercaseLetterChars = "abcdefghijklmnopqrstuvwxyz"
LetterChars = LowercaseLetterChars + LowercaseLetterChars.upper()
NumberChars = "0123456789"
OpChars = "&|=!+-*/%<>^~?:,."
LongOps = [c+"=" for c in  "&|=+-*/%<>^~!"] + ["--","++","->","<<",">>","&&","||","<<=",">>=","::",".*","->*"]
OpeningBrackets = "[({"
ClosingBrackets = "})]"

# NOTE: most of the C++ stuff is not really supported yet
OpPrecedences = {
    "::": 1,
    "++": 2,  # as postfix; 3 as prefix
    "--": 2,  # as postfix; 3 as prefix
    ".": 2,
    "->": 2,
    "typeid": 2,
    "const_cast": 2,
    "dynamic_cast": 2,
    "reinterpret_cast": 2,
    "static_cast": 2,
    "!": 3,
    "~": 3,
    "sizeof": 3,
    "new": 3,
    "delete": 3,
    ".*": 4,
    "->*": 4,
    "*": 5, # as bin op; 3 as prefix
    "/": 5,
    "%": 5,
    "+": 6, # as bin op; 3 as prefix
    "-": 6, # as bin op; 3 as prefix
    "<<": 7,
    ">>": 7,
    "<": 8,
    "<=": 8,
    ">": 8,
    ">=": 8,
    "==": 9,
    "!=": 9,
    "&": 10, # as bin op; 3 as prefix
    "^": 11,
    "|": 12,
    "&&": 13,
    "||": 14,
    "?": 15, # a ? b : c
    "?:": 15, # this is the internal op representation when we have got all three sub nodes
    "=": 16,
    "+=": 16,
    "-=": 16,
    "*=": 16,
    "/=": 16,
    "%=": 16,
    "<<=": 16,
    ">>=": 16,
    "&=": 16,
    "^=": 16,
    "|=": 16,
    "throw": 17,
    ",": 18
}

OpsRightToLeft = {"?", "?:", "=", "+=", "-=", "*=", "/=", "%=", "<<=", ">>=", "&=", "^=", "|="}

OpPrefixFuncs = {
    "+": (lambda x: +x),
    "-": (lambda x: -x),
    "&": (lambda x: ctypes.pointer(x)),
    "*": (lambda x: x.content),
    "++": (lambda x: ++x),
    "--": (lambda x: --x),
    "!": (lambda x: not x),
    "~": (lambda x: ~x),
}

OpPostfixFuncs = {
    "++", "--"
}

OpBinFuncs = {
    "+": (lambda a,b: a + b),
    "-": (lambda a,b: a - b),
    "*": (lambda a,b: a * b),
    "/": (lambda a,b: a // b),
    "%": (lambda a,b: a % b),
    "<<": (lambda a,b: a << b),
    ">>": (lambda a,b: a >> b),
    "<": (lambda a,b: a < b),
    "<=": (lambda a,b: a <= b),
    ">": (lambda a,b: a > b),
    ">=": (lambda a,b: a >= b),
    "==": (lambda a,b: a == b),
    "!=": (lambda a,b: a != b),
    "&": (lambda a,b: a & b),
    "^": (lambda a,b: a ^ b),
    "|": (lambda a,b: a | b),
    "&&": (lambda a,b: a and b),
    "||": (lambda a,b: a or b),
    ",": (lambda a,b: b),
    # NOTE: These assignment ops don't really behave like maybe expected
    # but they return the somewhat expected.
    "=": (lambda a,b: b),
    "+=": (lambda a,b: a + b),
    "-=": (lambda a,b: a - b),
    "*=": (lambda a,b: a * b),
    "/=": (lambda a,b: a // b),
    "%=": (lambda a,b: a % b),
    "<<=": (lambda a,b: a << b),
    ">>=": (lambda a,b: a >> b),
    "&=": (lambda a,b: a & b),
    "^=": (lambda a,b: a ^ b),
    "|=": (lambda a,b: a | b),
}

# WARNING: this isn't really complete
def simple_escape_char(c):
    if c == "n": return "\n"
    elif c == "t": return "\t"
    elif c == "a": return "\a"
    elif c == "b": return "\b"
    elif c == "f": return "\f"
    elif c == "r": return "\r"
    elif c == "v": return "\v"
    elif c == "0": return "\0"
    elif c == "\n": return ""
    elif c == '"': return '"'
    elif c == "'": return "'"
    elif c == "\\": return "\\"
    elif c in "1234567":  # octal escape (partial: only single-digit here)
        return chr(int(c, 8))
    else:
        # Just to be sure so that users don't run into trouble.
        assert False, "simple_escape_char: cannot handle " + repr(c) + " yet"


_HexChars = frozenset("0123456789abcdefABCDEF")


def _read_hex_escape(input_stream):
    """Read hex digits from *input_stream* (a _Pre2ParseStream) and return the character.

    Called after ``\\x`` has been consumed.  Reads as many hex digits as
    available, puts the first non-hex character back into the stream, and
    returns the decoded character (or '\\x00' if no digits were found).
    """
    hexstr = ""
    while True:
        nc = input_stream.next_char()
        if nc is None or nc not in _HexChars:
            # Put the non-hex character back so the outer loop sees it next.
            if nc is not None:
                input_stream.putback_char(nc)
            break
        hexstr += nc
    return chr(int(hexstr, 16)) if hexstr else "\x00"


_OctalChars = frozenset("01234567")


def _read_octal_escape(input_stream, first_digit):
    """Read up to 3 octal digits for a ``\\NNN`` escape.

    Called when the first digit ``first_digit`` (0-7) was already
    consumed by the dispatcher (state 21 / 26).  Reads up to 2 more
    octal digits from *input_stream* (C limits octal escapes to 3
    digits total), puts back the first non-octal character, and
    returns the decoded character.
    """
    octstr = first_digit
    for _ in range(2):  # already have 1, take up to 2 more
        nc = input_stream.next_char()
        if nc is None or nc not in _OctalChars:
            if nc is not None:
                input_stream.putback_char(nc)
            break
        octstr += nc
    return chr(int(octstr, 8))


def _read_fixed_hex_escape(input_stream, n_digits):
    """Read exactly *n_digits* hex digits for a ``\\uXXXX`` or ``\\UXXXXXXXX`` escape."""
    hexstr = ""
    for _ in range(n_digits):
        nc = input_stream.next_char()
        if nc is None or nc not in _HexChars:
            if nc is not None:
                input_stream.putback_char(nc)
            break
        hexstr += nc
    return chr(int(hexstr, 16)) if hexstr else "\x00"


def escape_cstr(s):
    return s.replace('"', '\\"')


def escape_cchar(c):
    """Escape a single character for safe use inside a C char literal '...'."""
    assert len(c) == 1
    if c == "'":
        return "\\'"
    if c == "\\":
        return "\\\\"
    return c


def parse_macro_def_rightside(stateStruct, argnames, input):
    assert input is not None
    if stateStruct is None:
        class Dummy:
            def error(self, s): pass
        stateStruct = Dummy()

    def f(*args):
        assert len(args) == len(argnames or ())
        args = {k: v for (k, v) in zip(argnames or (), args)}

        ret = ""
        state = 0
        lastidentifier = ""
        for c in input:
            if state == 0:
                if c in SpaceChars: ret += c
                elif c in LetterChars + "_":
                    state = 1
                    lastidentifier = c
                elif c in NumberChars:
                    state = 2
                    ret += c
                elif c == '"':
                    state = 4
                    ret += c
                elif c == "#": state = 6
                else: ret += c
            elif state == 1: # identifier
                if c in LetterChars + NumberChars + "_":
                    lastidentifier += c
                elif c == "#":
                    if lastidentifier in args:
                        ret += args[lastidentifier]
                    else:
                        ret += lastidentifier
                    lastidentifier = ""
                    state = 9
                else:
                    if lastidentifier in args:
                        ret += args[lastidentifier]
                    else:
                        ret += lastidentifier
                    lastidentifier = ""
                    ret += c
                    state = 0
            elif state == 2: # number
                ret += c
                if c in NumberChars: pass
                elif c == "x": state = 3
                elif c in LetterChars + "_": pass # even if invalid, stay in this state
                else: state = 0
            elif state == 3: # hex number
                ret += c
                if c in NumberChars + LetterChars + "_": pass # also ignore invalids
                else: state = 0
            elif state == 4: # str
                ret += c
                if c == "\\": state = 5
                elif c == '"': state = 0
                else: pass
            elif state == 5: # escape in str
                state = 4
                ret += simple_escape_char(c)
            elif state == 6: # after "#"
                if c in SpaceChars + LetterChars + "_":
                    lastidentifier = c.strip()
                    state = 7
                elif c == "#":
                    ret = ret.rstrip()
                    state = 8
                else:
                    # unexpected, just recover
                    stateStruct.error("unfold macro: unexpected char '" + c + "' after #")
                    state = 0
            elif state == 7: # after single "#"	with identifier
                if c in LetterChars + NumberChars + "_":
                    lastidentifier += c
                else:
                    if lastidentifier not in args:
                        stateStruct.error("unfold macro: cannot stringify " + lastidentifier + ": not found")
                    else:
                        ret += '"' + escape_cstr(args[lastidentifier]) + '"'
                    lastidentifier = ""
                    state = 0
                    ret += c
            elif state == 8: # after "##"
                if c in SpaceChars: pass
                else:
                    lastidentifier = c
                    state = 1
            elif state == 9: # after identifier + "#"
                if c == "#": state = 10
                else:
                    stateStruct.error("unfold macro: unexpected char %r after in state %i" % (c, state))
                    state = 0  # recover
            elif state == 10: # after identifier + "##"
                if c in LetterChars + "_":
                    lastidentifier = c
                    state = 1
                else:
                    stateStruct.error("unfold macro: unexpected char %r after in state %i" % (c, state))
                    state = 0  # recover
            else:
                stateStruct.error("unfold macro: internal error, char %r, in state %i" % (c, state))
                state = 0  # recover
        # Final check.
        if state == 1:
            if lastidentifier in args:
                ret += args[lastidentifier]
            else:
                ret += lastidentifier

        return ret

    return f


class Macro(object):
    def __init__(self, state=None, macroname=None, args=None, rightside=None):
        self.name = macroname
        self.args = args
        self.rightside = rightside if (rightside is not None) else ""
        self.defPos = state.curPosAsStr() if state else "<unknown>"
        self._tokens = None
    def __str__(self):
        if self.args is not None:
            return "(" + ", ".join(self.args) + ") -> " + self.rightside
        else:
            return "_ -> " + self.rightside
    def __repr__(self):
        return "<Macro: " + str(self) + ">"
    def eval(self, state, args):
        if len(args) != len(self.args or ()): raise TypeError("invalid number of args (" + str(args) + ") for " + repr(self))
        func = parse_macro_def_rightside(state, self.args, self.rightside)
        return func(*args)
    def __call__(self, *args):
        return self.eval(None, args)
    def __eq__(self, other):
        if not isinstance(other, Macro): return False
        return self.args == other.args and self.rightside == other.rightside
    def __ne__(self, other): return not self == other
    def _parseTokens(self, stateStruct):
        assert self.args is None
        if self._tokens is not None: return
        preprocessed = stateStruct.preprocess(self.rightside, None, repr(self))
        self._tokens = list(cpre2_parse(stateStruct, preprocessed))
    def getSingleIdentifer(self, stateStruct):
        assert self._tokens is not None
        if len(self._tokens) == 1 and isinstance(self._tokens[0], CIdentifier):
            return self._tokens[0].content
        return None
    def getCValue(self, stateStruct):
        tokens = self._tokens
        assert tokens is not None

        if all([isinstance(t, (CIdentifier,COp)) for t in tokens]):
            t = tuple([t.content for t in tokens])
            if t in stateStruct.CBuiltinTypes:
                return stateStruct.CBuiltinTypes[t].getCType(stateStruct)

        valueStmnt = CStatement()
        input_iter = iter(tokens)
        for token in input_iter:
            if isinstance(token, COpeningBracket):
                valueStmnt._cpre3_parse_brackets(stateStruct, token, input_iter)
            else:
                valueStmnt._cpre3_handle_token(stateStruct, token)
        valueStmnt.finalize(stateStruct)

        return valueStmnt.getConstValue(stateStruct)


# either some basic type, another typedef or some complex like CStruct/CUnion/...
class CType(object):
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
    def __repr__(self):
        return self.__class__.__name__ + " " + str(self.__dict__)
    def __eq__(self, other):
        if not hasattr(other, "__class__"): return False
        return self.__class__ is other.__class__ and self.__dict__ == other.__dict__
    def __ne__(self, other): return not self == other
    def __hash__(self): return hash(self.__class__) + 31 * hash(tuple(sorted(self.__dict__.items())))
    def getCType(self, stateStruct):
        raise NotImplementedError(str(self) + " getCType is not implemented")
    def asCCode(self, indent=""):
        raise NotImplementedError(str(self) + " asCCode not implemented")


class CUnknownType(CType):
    def asCCode(self, indent=""):
        return indent + "/* unknown */ int"


class CVoidType(CType):
    def __repr__(self): return "void"
    def getCType(self, stateStruct): return None
    def asCCode(self, indent=""): return indent + "void"


class CVariadicArgsType(CType):
    def getCType(self, stateStruct): return None
    def asCCode(self, indent=""): return indent + "..."


class CPointerType(CType):
    def __init__(self, ptr):
        super(CPointerType, self).__init__()
        self.pointerOf = ptr

    def getCType(self, stateStruct):
        try:
            target = self.pointerOf
            while isinstance(target, CTypedef):
                target = target.type
            if isinstance(target, CFunc):
                return target.getCType(stateStruct)
            
            t = getCType(self.pointerOf, stateStruct)
            if t is None:
                ptrType = getCType(ctypes.c_void_p, stateStruct)
            else:
                ptrType = get_pointer_type(t)
            return ptrType
        except CTypeConstructionException as e:
            stateStruct.error("getCType " + str(self) + ": error getting type (" + str(e) + "), falling back to void-ptr")
        return getCType(ctypes.c_void_p, stateStruct)
    def asCCode(self, indent=""): return indent + asCCode(self.pointerOf) + "*"


class CBuiltinType(CType):
    def __init__(self, builtinType):
        super(CBuiltinType, self).__init__()
        assert isinstance(builtinType, tuple)
        self.builtinType = builtinType
    def getCType(self, stateStruct):
        t = stateStruct.CBuiltinTypes[self.builtinType]
        return getCType(t, stateStruct)
    def asCCode(self, indent=""): return indent + " ".join(self.builtinType)


class CStdIntType(CType):
    def __init__(self, name):
        super(CStdIntType, self).__init__()
        self.name = name
    def getCType(self, stateStruct):
        t = stateStruct.StdIntTypes[self.name]
        return getCType(t, stateStruct)
    def asCCode(self, indent=""): return indent + self.name


class CBitfieldType(CType):
    def __init__(self, type):
        super(CBitfieldType, self).__init__()
        self.type = type
    def getCType(self, stateStruct):
        return getCType(self.type, stateStruct)
    def asCCode(self, indent=""): return self.type.asCCode(indent)


class CArrayType(CType):
    def __init__(self, arrayOf, arrayLen):
        super(CArrayType, self).__init__()
        self.arrayOf = arrayOf
        self.arrayLen = arrayLen
    def getCType(self, stateStruct):
        try:
            t = getCType(self.arrayOf, stateStruct)
        except Exception as e:
            stateStruct.error(str(self) + ": error getting type (" + str(e) + "), falling back to int")
            t = ctypes.c_int
            if stateStruct.IndirectSimpleCTypes:
                t = wrapCTypeClassIfNeeded(t)
        if not self.arrayLen:
            return ctypes.POINTER(t)
        l = getConstValue(stateStruct, self.arrayLen)
        if l is None:
            stateStruct.error("%s: error getting array len, falling back to 1" % self)
            l = 1
        return t * l
    def asCCode(self, indent=""): return "%s%s[%s]" % (indent, asCCode(self.arrayOf), asCCode(self.arrayLen))


def getCType(t, stateStruct):
    """
    :type stateStruct: State
    """
    assert not isinstance(t, CUnknownType)
    try:
        if issubclass(t, (_ctypes._SimpleCData,ctypes._Pointer,ctypes._CFuncPtr)):
            if stateStruct.IndirectSimpleCTypes:
                return wrapCTypeClassIfNeeded(t)
            return t
        if issubclass(t, ctypes.Array):
            if t.__name__.startswith("wrapCTypeClass_"):
                return t.__bases__[0]
            return t
    except Exception: pass # e.g. typeerror or so
    if isinstance(t, (CStruct,CUnion,CEnum)):
        if t.body is None:
            # it probably is the pre-declaration. but we might find the real-one
            if isinstance(t, CStruct): D = "structs"
            elif isinstance(t, CUnion): D = "unions"
            elif isinstance(t, CEnum): D = "enums"
            
            t = getattr(stateStruct, D).get(t.name, t)
            
            if t.body is None and t.name:
                p = t.parent
                while p:
                    if hasattr(p, "body") and isinstance(p.body, CBody):
                        if t.name in getattr(p.body, D):
                            t = getattr(p.body, D)[t.name]
                            if t.body is not None: break
                    p = p.parent
        return t.getCType(stateStruct)
    if isinstance(t, _CBaseWithOptBody):
        return t.getCType(stateStruct)
    if isinstance(t, CType):
        return t.getCType(stateStruct)
    raise Exception(str(t) + " cannot be converted to a C type")


def getCTypeWrapped(t, stateStruct):
    """
    :type stateStruct: State
    """
    t = getCType(t, stateStruct)
    assert issubclass(t, (_ctypes._SimpleCData, ctypes._Pointer, ctypes._CFuncPtr,
                          ctypes.Structure, ctypes.Union))
    return wrapCTypeClassIfNeeded(t)


def isSameType(stateStruct, type1, type2):
    ctype1 = getCType(type1, stateStruct)
    ctype2 = getCType(type2, stateStruct)
    return ctype1 == ctype2


def isType(t):
    if isinstance(t, CType) and not isinstance(t, CWrapValue): return True
    if isinstance(t, CStatement):
        return t.isCType()
    try:
        if issubclass(t, _ctypes._SimpleCData): return True
    except Exception: pass # e.g. typeerror or so
    if isinstance(t, (CStruct,CUnion,CEnum,CTypedef)): return True
    # ``CFuncPointerDecl`` is a function-pointer type-name (e.g.
    # ``int (*)(int)`` after parser normalisation -- see
    # ``CStatement.finalize`` and ``_is_funcptr_typename_misparse``).
    # Used as a cast target in ``((int (*)(int))p)(x)``.
    if isinstance(t, CFuncPointerDecl): return True
    return False


def _is_funcptr_typename_misparse(node):
    """Recognise the parser's intermediate shape of a function-
    pointer type-name and return True.

    Background: C's grammar requires unbounded lookahead to tell
    ``int (`` apart as the start of a function call vs. a function-
    pointer type-name ``int (*) (args)`` (used e.g. in
    ``((int (*)(PyObject *))slot->value)(module)`` in
    ``Objects/moduleobject.c::PyModule_ExecDef``).

    Our pre-3 statement parser commits to the call interpretation
    while consuming tokens.  The ``*`` between ``( )`` is then a
    prefix-op with no operand and falls out, leaving the
    intermediate shape

        CFuncCall(
            base = CFuncCall(base = ReturnType, args = []),  # "T()"
            args = [CStatement(P1), CStatement(P2), ...],    # "(args)"
        )

    ``CStatement.finalize`` normalises this to a proper
    ``CFuncPointerDecl`` via ``_funcptr_typename_misparse_to_decl``
    -- the buggy shape never escapes the parser.  This helper is
    the detector used by that normalisation.
    """
    if not isinstance(node, CFuncCall):
        return False
    inner = node.base
    if not isinstance(inner, CFuncCall):
        return False
    if inner.args:
        # ``T(x)(y)`` -- inner has args, not the ``T()`` empty-call
        # produced by the dropped ``*``.
        return False
    if not isType(inner.base):
        return False
    # Every outer arg must itself be a type (the function
    # pointer's parameter types).
    for a in node.args:
        if not isType(a):
            return False
    return True


def _funcptr_typename_misparse_to_decl(node):
    """Convert the intermediate parser shape of a function-pointer
    type-name (see ``_is_funcptr_typename_misparse``) to a proper
    ``CFuncPointerDecl``.
    """
    assert _is_funcptr_typename_misparse(node)
    inner = node.base
    return_type = inner.base
    if isinstance(return_type, CStatement):
        return_type = return_type.asType()
    fp = CFuncPointerDecl()
    fp._type_tokens = [return_type]
    fp.type = return_type
    fp.args = []
    for a in node.args:
        if isinstance(a, CStatement):
            t = a.asType()
        else:
            t = a
        arg = CFuncArgDecl()
        arg.type = t
        fp.args.append(arg)
    return fp


def getSizeOf(t, stateStruct):
    t = getCType(t, stateStruct)
    return ctypes.sizeof(t)


class State(object):
    # See _getCTypeStruct for details.
    IndirectSimpleCTypes = False

    EmptyMacro = Macro(None, None, (), "")
    CBuiltinTypes = {
        ("void",): CVoidType(),
        ("void", "*"): ctypes.c_void_p,
        ("char",): ctypes.c_byte,
        ("signed", "char"): ctypes.c_byte,
        ("unsigned", "char"): ctypes.c_ubyte,
        ("short",): ctypes.c_short,
        ("short", "int"): ctypes.c_short,
        ("signed", "short"): ctypes.c_short,
        ("unsigned", "short"): ctypes.c_ushort,
        ("int",): ctypes.c_int,
        ("signed",): ctypes.c_int,
        ("signed", "int"): ctypes.c_int,
        ("unsigned", "int"): ctypes.c_uint,
        ("unsigned",): ctypes.c_uint,
        ("long",): ctypes.c_long,
        ("signed", "long"): ctypes.c_long,
        ("unsigned", "long"): ctypes.c_ulong,
        ("long", "long"): ctypes.c_longlong,
        ("long", "long", "int"): ctypes.c_longlong,
        ("signed", "long", "long"): ctypes.c_longlong,
        ("unsigned", "long", "long"): ctypes.c_ulonglong,
        ("float",): ctypes.c_float,
        ("double",): ctypes.c_double,
        ("long", "double"): ctypes.c_longdouble,
    }
    StdIntTypes = {
        "uint8_t": ctypes.c_uint8,
        "uint16_t": ctypes.c_uint16,
        "uint32_t": ctypes.c_uint32,
        "uint64_t": ctypes.c_uint64,
        "int8_t": ctypes.c_int8,
        "int16_t": ctypes.c_int16,
        "int32_t": ctypes.c_int32,
        "int64_t": ctypes.c_int64,
        # Note: we intentionally do not register "byte" as a built-in type
        # name -- it is not a C standard type, and treating it as one means
        # any function that has a `char *byte` parameter (and CPython's
        # Objects/bytes_methods.c does) fails to parse with `type tokens
        # not handled: ['char', '*', 'byte']`.  Code that wants the alias
        # can still do `typedef unsigned char byte;` explicitly.
        "wchar_t": ctypes.c_wchar,
        "wint_t": ctypes.c_int,
        "size_t": ctypes.c_size_t,
        "ptrdiff_t": ctypes.c_long,
        "intptr_t": ctypes.c_long,
        "uintptr_t": ctypes.c_ulong,
        # _Bool is the C99 underlying boolean type.  `<stdbool.h>` aliases
        # it as `bool` via a macro, but CPython source uses `_Bool` directly
        # in a few places (e.g. Objects/memoryobject.c).  Map to c_bool.
        "_Bool": ctypes.c_bool,
        "FILE": ctypes.c_int, # NOTE: not really correct but shouldn't matter unless we directly access it
    }
    Attribs = frozenset((
        "const",
        "extern",
        "static",
        "register",
        "volatile",
        "__inline__",
        "inline",
    ))

    def __init__(self):
        self.parent = None
        self.encoding = "utf-8" # Encoding used to open files
        self.macros = {} # name -> Macro
        self.typedefs = {} # name -> type
        self.structs = {} # name -> CStruct
        self.unions = {} # name -> CUnion
        self.enums = {} # name -> CEnum
        self.funcs = {} # name -> CFunc
        self.vars = {} # name -> CVarDecl
        self.enumconsts = {} # name -> CEnumConst
        self.contentlist = []
        self._preprocessIfLevels = []
        self._preprocessIgnoreCurrent = False
        # 0->didnt got true yet, 1->in true part, 2->after true part. and that as a stack
        self._preprocessIncludeLevel = []
        self._errors = []
        self._global_include_wrapper = None  # type: typing.Optional[globalincludewrappers.Wrapper]
        self._global_include_list = []
        self._construct_struct_type_stack = []  # via _getCTypeStruct

    @classmethod
    def getDictNameForType(cls, objType):
        if issubclass(objType, Macro): return "macros"
        if issubclass(objType, CTypedef): return "typedef"  # not really consistent
        if issubclass(objType, CStruct): return "structs"
        if issubclass(objType, CUnion): return "unions"
        if issubclass(objType, CEnum): return "enums"
        if issubclass(objType, CFunc): return "funcs"
        if issubclass(objType, CVarDecl): return "vars"
        if issubclass(objType, CEnumConst): return "enumconsts"
        assert False, "unknown type %r" % objType

    def getResolvedDecl(self, obj):
        attrib = self.getDictNameForType(type(obj))
        d = getattr(self, attrib)
        return d.get(obj.name, obj)

    def autoSetupSystemMacros(self, system_specific=False):
        import sys
        # L"..." wchar string literals are handled directly in the tokenizer (cpre2_parse)
        self.macros["__attribute__"] = Macro(args=("x",), rightside="")
        self.macros["__GNUC__"] = Macro(rightside="4") # most headers just behave more sane with this :)
        self.macros["__GNUC_MINOR__"] = Macro(rightside="2")
        #self.macros["UINT64_C"] = Macro(args=("C"), rightside= "C##ui64") # or move to stdint.h handler?
        if system_specific and sys.platform == "darwin":
            self.macros["__APPLE__"] = self.EmptyMacro
            self.macros["__MACH__"] = self.EmptyMacro
            self.macros["__MACOSX__"] = self.EmptyMacro
            self.macros["i386"] = self.EmptyMacro
            self.macros["MAC_OS_X_VERSION_MIN_REQUIRED"] = Macro(rightside="1030")

    def autoSetupGlobalIncludeWrappers(self):
        if self._global_include_wrapper: return
        from .globalincludewrappers import Wrapper
        self._global_include_wrapper = Wrapper(self)
        self._global_include_wrapper.install()

    def incIncludeLineChar(self, fullfilename=None, inc=None, line=None, char=None, charMod=None):
        CharStartIndex = 0
        LineStartIndex = 1
        if inc is not None:
            self._preprocessIncludeLevel += [[fullfilename, inc, LineStartIndex, CharStartIndex]]
        if len(self._preprocessIncludeLevel) == 0:
            self._preprocessIncludeLevel += [[None, "<input>", LineStartIndex, CharStartIndex]]
        if line is not None:
            self._preprocessIncludeLevel[-1][2] += line
            self._preprocessIncludeLevel[-1][3] = CharStartIndex
        if char is not None:
            c = self._preprocessIncludeLevel[-1][3]
            c += char
            if charMod is not None:
                c = c - (c - CharStartIndex) % charMod + CharStartIndex
            self._preprocessIncludeLevel[-1][3] = c

    def curPosAsStr(self):
        if len(self._preprocessIncludeLevel) == 0: return "<out-of-scope>"
        l = self._preprocessIncludeLevel[-1]
        return ":".join([l[1], str(l[2]), str(l[3])])

    def curFile(self):
        if not self._preprocessIncludeLevel: return "<out-of-scope>"
        return self._preprocessIncludeLevel[-1][1]

    def curLine(self):
        if not self._preprocessIncludeLevel: return -1
        return self._preprocessIncludeLevel[-1][2]

    def error(self, s):
        self._errors.append(self.curPosAsStr() + ": " + s)

    def log(self, *args):
        print(self.curPosAsStr() + ": " + " ".join(map(str, args)))

    def findIncludeFullFilename(self, filename, local):
        if local:
            dir = ""
            if filename[0] != "/":
                if self._preprocessIncludeLevel and self._preprocessIncludeLevel[-1][0]:
                    import os.path
                    dir = os.path.dirname(self._preprocessIncludeLevel[-1][0])
                if not dir: dir = "."
                dir += "/"
        else:
            dir = ""

        fullfilename = dir + filename
        return fullfilename

    def readLocalInclude(self, filename):
        """
        :param str filename:
        :rtype: (typing.Iterable[str],str)
        """
        fullfilename = self.findIncludeFullFilename(filename, True)

        try:
            import codecs
            f = codecs.open(fullfilename, "r", self.encoding)
        except Exception as e:
            self.error("cannot open local include-file '" + filename + "': " + str(e))
            return "", None

        def reader():
            while True:
                c = f.read(1)
                if len(c) == 0: break
                yield c
        reader = reader()

        return reader, fullfilename

    def readGlobalInclude(self, filename):
        """
        :param str filename:
        :rtype: (str,None)
        """
        if filename == "inttypes.h": return "", None # we define those types as builtin-types
        elif filename == "stdint.h": return "", None
        else:
            self.error("no handler for global include-file '" + filename + "'")
            return "", None

    def preprocess_file(self, filename, local):
        """
        :param str filename:
        :param bool local:
        :return: yields chars
        :rtype: typing.Generator[str]
        """
        if local:
            reader, fullfilename = self.readLocalInclude(filename)
        else:
            reader, fullfilename = self.readGlobalInclude(filename)

        for c in self.preprocess(reader, fullfilename, filename):
            yield c

    def preprocess_source_code(self, source_code, dummy_filename="<input>"):
        """
        :param str source_code:
        :param str dummy_filename:
        :return: yields chars
        :rtype: typing.Generator[str]
        """
        for c in self.preprocess(source_code, dummy_filename, dummy_filename):
            yield c

    def preprocess(self, reader, fullfilename, filename):
        """
        :param reader:
        :param str|None fullfilename:
        :param str filename:
        :return: yields chars
        :rtype: typing.Generator[str]
        """
        self.incIncludeLineChar(fullfilename=fullfilename, inc=filename)
        for c in cpreprocess_parse(self, reader):
            yield c
        self._preprocessIncludeLevel = self._preprocessIncludeLevel[:-1]

    def depth(self): return 0


def is_valid_defname(defname):
    if not defname: return False
    gotValidPrefix = False
    for c in defname:
        if c in LetterChars + "_":
            gotValidPrefix = True
        elif c in NumberChars:
            if not gotValidPrefix: return False
        else:
            return False
    return True


def cpreprocess_evaluate_ifdef(state, arg):
    arg = arg.strip()
    if not is_valid_defname(arg):
        state.error("preprocessor: '" + arg + "' is not a valid macro name")
        return False
    if arg in ("__FILE__", "__LINE__"): return True
    return arg in state.macros


def cpreprocess_evaluate_single(state, arg):
    if arg == "": return None
    # Strip trailing integer-type suffixes (u, U, l, L and combinations like UL, LU, ULL …)
    # before trying numeric conversion so that e.g. `0xFFu` or `100UL` parse correctly.
    stripped = arg.rstrip("uUlL")
    try: return int(stripped) # is integer?
    except ValueError: pass
    try: return long(stripped) # is long?
    except ValueError: pass
    try: return int(stripped, 16) # is hex (0x…)?
    except ValueError: pass
    if len(arg) >= 2 and arg[0] == '"' and arg[-1] == '"': return arg[1:-1] # is string?

    if not is_valid_defname(arg):
        state.error("preprocessor eval single: '" + arg + "' is not a valid macro name")
        return 0
    if arg not in state.macros:
        # This is not an error.
        return 0
    try:
        resolved = state.macros[arg]()
    except Exception as e:
        state.error("preprocessor eval single error on '" + arg + "': " + str(e))
        return 0
    return cpreprocess_evaluate_cond(state, resolved)


def cpreprocess_evaluate_cond(stateStruct, condstr):
    state = 0
    bracketLevel = 0
    substr = ""
    laststr = ""
    lasteval = None
    op = None
    prefixOp = None
    opstr = ""
    args = []
    i = 0
    while i < len(condstr):
        c = condstr[i]
        i += 1
        breakLoop = False
        while not breakLoop:
            breakLoop = True

            if state == 0:
                if c == "(":
                    if laststr == "":
                        state = 1
                        bracketLevel = 1
                    else:
                        state = 10
                        breakLoop = False
                elif c == ")":
                    stateStruct.error("preprocessor: runaway ')' in " + repr(condstr))
                    return
                elif c in SpaceChars:
                    if laststr == "defined": state = 5
                    elif laststr != "": state = 10
                    else: pass
                elif c in OpChars:
                    state = 10
                    breakLoop = False
                elif c == '"':
                    if laststr == "":
                        state = 20
                    else:
                        stateStruct.error("preprocessor: '\"' not expected")
                        return
                elif c == "'":
                    if laststr in ("", "L", "u", "U"):
                        # Accept bare or wide/unicode-prefixed char literals:
                        # L'x', u'x', U'x' — the prefix has no effect on the
                        # integer value in a preprocessor #if context.
                        laststr = ""
                        state = 22
                    else:
                        stateStruct.error("preprocessor: \"'\" not expected")
                        return
                else:
                    laststr += c
            elif state == 1: # in bracket
                if c == "(":
                    bracketLevel += 1
                if c == ")":
                    bracketLevel -= 1
                    if bracketLevel == 0:
                        neweval = cpreprocess_evaluate_cond(stateStruct, substr)
                        state = 18
                        if prefixOp is not None:
                            neweval = prefixOp(neweval)
                            prefixOp = None
                        if op is not None: lasteval = op(lasteval, neweval)
                        else: lasteval = neweval
                        substr = ""
                    else: # bracketLevel > 0
                        substr += c
                elif c == '"':
                    state = 2
                    substr += c
                else:
                    substr += c
            elif state == 2: # in str in bracket
                substr += c
                if c == "\\": state = 3
                elif c == '"': state = 1
                else: pass
            elif state == 3: # in escape in str in bracket
                substr += c
                state = 2
            elif state == 5: # after "defined" without brackets (yet)
                if c in SpaceChars: pass
                elif c == "(":
                    state = 10
                    breakLoop = False
                elif c == ")":
                    stateStruct.error("preprocessor eval: 'defined' invalid in '" + condstr + "'")
                    return
                else:
                    laststr = c
                    state = 6
            elif state == 6: # chars after "defined"
                if c in LetterChars + "_" + NumberChars:
                    laststr += c
                else:
                    macroname = laststr
                    if not is_valid_defname(macroname):
                        stateStruct.error("preprocessor eval defined-check: '" + macroname + "' is not a valid macro name")
                        return
                    neweval = macroname in stateStruct.macros
                    if prefixOp is not None:
                        neweval = prefixOp(neweval)
                        prefixOp = None
                    oldlast = lasteval
                    if op is not None: lasteval = op(lasteval, neweval)
                    else: lasteval = neweval
                    opstr = ""
                    laststr = ""
                    state = 18
                    breakLoop = False
            elif state == 10: # after identifier
                if c in SpaceChars: pass
                elif c in OpChars:
                    if laststr != "":
                        neweval = cpreprocess_evaluate_single(stateStruct, laststr)
                        if prefixOp is not None:
                            neweval = prefixOp(neweval)
                            prefixOp = None
                        if op is not None: lasteval = op(lasteval, neweval)
                        else: lasteval = neweval
                        laststr = ""
                    opstr = ""
                    state = 18
                    breakLoop = False
                elif c == "(":
                    state = 11
                    bracketLevel = 1
                    args = []
                else:
                    stateStruct.error("preprocessor eval: '" + c + "' not expected after '" + laststr + "' in state 10 with '" + condstr + "'")
                    return
            elif state == 11: # after "(" after identifier
                if c == "(":
                    if len(args) == 0: args = [""]
                    args[-1] += c
                    bracketLevel += 1
                    state = 12
                elif c == ")":
                    macroname = laststr
                    if macroname == "defined":
                        if len(args) != 1:
                            stateStruct.error("preprocessor eval defined-check args invalid: " + str(args))
                            return
                        else:
                            macroname = args[0]
                            if not is_valid_defname(macroname):
                                stateStruct.error("preprocessor eval defined-check: '" + macroname + "' is not a valid macro name")
                                return
                            neweval = macroname in stateStruct.macros
                    else:
                        if not is_valid_defname(macroname):
                            stateStruct.error("preprocessor eval call: '" + macroname + "' is not a valid macro name in " + repr(condstr))
                            return
                        if macroname not in stateStruct.macros:
                            stateStruct.error("preprocessor eval call: '" + macroname + "' is unknown")
                            return
                        macro = stateStruct.macros[macroname]
                        try:
                            resolved = macro.eval(stateStruct, args)
                        except Exception as e:
                            stateStruct.error("preprocessor eval call on '" + macroname + "': error " + str(e))
                            return
                        neweval = cpreprocess_evaluate_cond(stateStruct, resolved)

                    if prefixOp is not None:
                        neweval = prefixOp(neweval)
                        prefixOp = None
                    oldlast = lasteval
                    if op is not None: lasteval = op(lasteval, neweval)
                    else: lasteval = neweval
                    #print "after ):", laststr, args, neweval, op.func_code.co_firstlineno if op else "no-op", oldlast, "->", lasteval
                    laststr = ""
                    opstr = ""
                    state = 18
                elif c == '"':
                    if len(args) == 0: args = [""]
                    args[-1] += c
                    state = 13
                elif c == ",": args += [""]
                else:
                    if len(args) == 0: args = [""]
                    args[-1] += c
            elif state == 12: # in additional "(" after "(" after identifier
                args[-1] += c
                if c == "(": bracketLevel += 1
                elif c == ")":
                    bracketLevel -= 1
                    if bracketLevel == 1: state = 11
                elif c == '"': state = 13
                else: pass
            elif state == 13: # in str after "(" after identifier
                args[-1] += c
                if c == "\\": state = 14
                elif c == '"':
                    if bracketLevel > 1: state = 12
                    else: state = 11
                else: pass
            elif state == 14: # in escape in str after "(" after identifier
                args[-1] += c
                state = 13
            elif state == 18: # op after identifier/expression
                if c in OpChars: opstr += c
                else:
                    if opstr == "":
                        if c in SpaceChars: pass
                        else:
                            stateStruct.error("preprocessor eval: expected op but got '" + c + "' in '" + condstr + "' in state 18")
                            return
                    else:
                        if opstr == "&&":
                            op = lambda x,y: x and y
                            # short path check
                            if not lasteval: return lasteval
                        elif opstr == "||":
                            op = lambda x,y: x or y
                            # short path check
                            if lasteval: return lasteval
                        elif opstr in OpBinFuncs:
                            op = OpBinFuncs[opstr]
                            # HACK: add "()" in some way...
                            j = i
                            while j < len(condstr):
                                if condstr[j] == "'":
                                    j += 1
                                    while j < len(condstr):
                                        if condstr[j] == "'": break
                                        if condstr[j] == "\\": j += 1
                                        j += 1
                                    continue
                                if condstr[j] == '"':
                                    j += 1
                                    while j < len(condstr):
                                        if condstr[j] == '"': break
                                        if condstr[j] == "\\": j += 1
                                        j += 1
                                    continue
                                if condstr[j] in OpChars:
                                    nextopstr = ""
                                    while j < len(condstr) and condstr[j] in OpChars:
                                        nextopstr += condstr[j]
                                        j += 1
                                    if nextopstr in OpBinFuncs:
                                        if OpPrecedences[opstr] > OpPrecedences[nextopstr]:
                                            condstr = condstr[:i] + "(" + condstr[i:] + ")"
                                    #if j < len(condstr):
                                    #	condstr = condstr[:j] + "(" + condstr[j:] + ")"
                                    break
                                j += 1
                        elif opstr in OpPrefixFuncs:
                            newprefixop = OpPrefixFuncs[opstr]
                            if prefixOp: prefixOp = lambda x: prefixOp(newprefixop(x))
                            else: prefixOp = newprefixop
                        else:
                            stateStruct.error("invalid op '" + opstr + "' with '" + c + "' following in '" + condstr + "'")
                            return
                        opstr = ""
                        laststr = ""
                        state = 0
                        breakLoop = False
            elif state == 20: # in str
                if c == "\\": state = 21
                elif c == '"':
                    state = 0
                    neweval = laststr
                    laststr = ""
                    if prefixOp is not None:
                        neweval = prefixOp(neweval)
                        prefixOp = None
                    if op is not None: lasteval = op(lasteval, neweval)
                    else: lasteval = neweval
                else: laststr += c
            elif state == 21: # in escape in str
                laststr += simple_escape_char(c)
                state = 20
            elif state == 22: # in char
                if c == "\\": state = 23
                elif c == "'":
                    state = 0
                    # Convert single-character content to its code point so that
                    # comparisons like `SEP == '\\'` or `SEP == L'/'` work
                    # correctly (comparing integers, not strings).
                    neweval = ord(laststr) if len(laststr) == 1 else laststr
                    laststr = ""
                    if prefixOp is not None:
                        neweval = prefixOp(neweval)
                        prefixOp = None
                    if op is not None: lasteval = op(lasteval, neweval)
                    else: lasteval = neweval
                else: laststr += c
            elif state == 23: # in escape in char
                laststr += simple_escape_char(c)
                state = 22
            else:
                stateStruct.error("internal error in preprocessor evaluation: state " + str(state))
                return

    if state in (0,10):
        if laststr != "":
            neweval = cpreprocess_evaluate_single(stateStruct, laststr)
            if prefixOp is not None:
                neweval = prefixOp(neweval)
                prefixOp = None
            if op is not None: lasteval = op(lasteval, neweval)
            else: lasteval = neweval
    elif state == 6:
        macroname = laststr
        if not is_valid_defname(macroname):
            stateStruct.error("preprocessor eval defined-check: '" + macroname + "' is not a valid macro name")
            return
        neweval = macroname in stateStruct.macros
        if prefixOp is not None:
            neweval = prefixOp(neweval)
            prefixOp = None
        oldlast = lasteval
        if op is not None: lasteval = op(lasteval, neweval)
        else: lasteval = neweval
    elif state == 18: # expected op
        if opstr != "":
            stateStruct.error("preprocessor eval: unfinished op: '" + opstr + "'")
        else: pass
    else:
        stateStruct.error("preprocessor eval: invalid argument: '" + condstr + "'. unfinished state " + str(state))

    #print "eval:", condstr, "->", lasteval
    return lasteval

def cpreprocess_handle_include(state, arg):
    arg = arg.strip()
    if len(arg) < 2:
        state.error("invalid include argument: '" + arg + "'")
        return
    if arg[0] == '"' and arg[-1] == '"':
        local = True
        filename = arg[1:-1]
    elif arg[0] == "<" and arg[-1] == ">":
        local = False
        filename = arg[1:-1]
    else:
        state.error("invalid include argument: '" + arg + "'")
        return
    for c in state.preprocess_file(filename=filename, local=local): yield c

def cpreprocess_handle_def(stateStruct, arg):
    state = 0
    macroname = ""
    args = None
    rightside = ""
    for c in arg:
        if state == 0:
            if c in SpaceChars:
                if macroname != "": state = 3
            elif c == "(":
                state = 2
                args = []
            else: macroname += c
        elif state == 2: # after "("
            if c in SpaceChars: pass
            elif c == ",": args += [""]
            elif c == ")": state = 3
            else:
                if not args: args = [""]
                args[-1] += c
        elif state == 3: # rightside
            rightside += c

    if not is_valid_defname(macroname):
        stateStruct.error("preprocessor define: '" + macroname + "' is not a valid macro name")
        return

    macro = Macro(stateStruct, macroname, args, rightside)
    if macroname in stateStruct.macros:
        if stateStruct.macros[macroname] == macro:
            return stateStruct.macros[macroname]
        stateStruct.error("preprocessor define: '" + macroname + "' already defined." +
                          " previously defined at " + stateStruct.macros[macroname].defPos)
        # pass through to use new definition

    stateStruct.macros[macroname] = macro
    return macro


def cpreprocess_handle_undef(state, arg):
    arg = arg.strip()
    if not is_valid_defname(arg):
        state.error("preprocessor: '" + arg + "' is not a valid macro name")
        return
    if not arg in state.macros:
        # This is not an error. Just ignore.
        return
    state.macros.pop(arg)


def handle_cpreprocess_cmd(state, cmd, arg):
    #if not state._preprocessIgnoreCurrent:
    #	print "cmd", cmd, arg

    if cmd == "ifdef":
        state._preprocessIfLevels += [0]
        if any(map(lambda x: x != 1, state._preprocessIfLevels[:-1])): return # we don't really care
        check = cpreprocess_evaluate_ifdef(state, arg)
        if check: state._preprocessIfLevels[-1] = 1

    elif cmd == "ifndef":
        state._preprocessIfLevels += [0]
        if any(map(lambda x: x != 1, state._preprocessIfLevels[:-1])): return # we don't really care
        check = not cpreprocess_evaluate_ifdef(state, arg)
        if check: state._preprocessIfLevels[-1] = 1

    elif cmd == "if":
        state._preprocessIfLevels += [0]
        if any(map(lambda x: x != 1, state._preprocessIfLevels[:-1])): return # we don't really care
        check = cpreprocess_evaluate_cond(state, arg)
        if check: state._preprocessIfLevels[-1] = 1

    elif cmd == "elif":
        if any(map(lambda x: x != 1, state._preprocessIfLevels[:-1])): return # we don't really care
        if len(state._preprocessIfLevels) == 0:
            state.error("preprocessor: elif without if")
            return
        if state._preprocessIfLevels[-1] >= 1:
            state._preprocessIfLevels[-1] = 2 # we already had True
        else:
            check = cpreprocess_evaluate_cond(state, arg)
            if check: state._preprocessIfLevels[-1] = 1

    elif cmd == "else":
        if any(map(lambda x: x != 1, state._preprocessIfLevels[:-1])): return # we don't really care
        if len(state._preprocessIfLevels) == 0:
            state.error("preprocessor: else without if")
            return
        if state._preprocessIfLevels[-1] >= 1:
            state._preprocessIfLevels[-1] = 2 # we already had True
        else:
            state._preprocessIfLevels[-1] = 1

    elif cmd == "endif":
        if len(state._preprocessIfLevels) == 0:
            state.error("preprocessor: endif without if")
            return
        state._preprocessIfLevels = state._preprocessIfLevels[0:-1]

    elif cmd == "include":
        if state._preprocessIgnoreCurrent: return
        for c in cpreprocess_handle_include(state, arg): yield c

    elif cmd == "define":
        if state._preprocessIgnoreCurrent: return
        cpreprocess_handle_def(state, arg)

    elif cmd == "undef":
        if state._preprocessIgnoreCurrent: return
        cpreprocess_handle_undef(state, arg)

    elif cmd == "pragma":
        pass # ignore at all right now

    elif cmd == "error":
        if state._preprocessIgnoreCurrent: return # we don't really care
        state.error("preprocessor error command: " + arg)

    elif cmd == "warning":
        if state._preprocessIgnoreCurrent: return # we don't really care
        state.error("preprocessor warning command: " + arg)

    else:
        if state._preprocessIgnoreCurrent: return # we don't really care
        state.error("preprocessor command " + cmd + " unknown")

    state._preprocessIgnoreCurrent = any(map(lambda x: x != 1, state._preprocessIfLevels))


def cpreprocess_parse(stateStruct, input):
    """
    :param State stateStruct:
    :param str|typing.Iterable[str] input: not-yet preprocessed C code (str or iterable over chars)
    :returns preprocessed C code, iterator of chars
    This removes comments and can skip over parts, which is controlled by
    the C preprocessor commands (`#if 0` parts or so).
    We will not do C preprocessor macro substitutions here.
    The next func which gets this output is cpre2_parse().
    :rtype: typing.Generator[str]
    """
    cmd = ""
    arg = ""
    state = 0
    statebeforecomment = None
    for c in input:
        breakLoop = False
        while not breakLoop:
            breakLoop = True

            if state == 0:
                if c == "#":
                    cmd = ""
                    arg = None
                    state = 1
                elif c == "/":
                    statebeforecomment = 0
                    state = 20
                elif c == '"':
                    if not stateStruct._preprocessIgnoreCurrent: yield c
                    state = 10
                elif c == "'":
                    if not stateStruct._preprocessIgnoreCurrent: yield c
                    state = 12
                else:
                    if not stateStruct._preprocessIgnoreCurrent: yield c
            elif state == 1: # start of preprocessor command
                if c in SpaceChars: pass
                elif c == "\n": state = 0
                else:
                    cmd = c
                    state = 2
            elif state == 2: # in the middle of the preprocessor command
                if c in SpaceChars:
                    if arg is None: arg = ""
                    else: arg += c
                elif c == "(":
                    if arg is None: arg = c
                    else: arg += c
                elif c == "/":
                    state = 20
                    statebeforecomment = 2
                elif c == '"':
                    state = 3
                    if arg is None: arg = ""
                    arg += c
                elif c == "'":
                    state = 4
                    if arg is None: arg = ""
                    arg += c
                elif c == "\\": state = 5 # escape next
                elif c == "\n":
                    for c in handle_cpreprocess_cmd(stateStruct, cmd, arg): yield c
                    state = 0
                else:
                    if arg is None: cmd += c
                    else: arg += c
            elif state == 3: # in '"' in arg in command
                arg += c
                if c == "\n":
                    stateStruct.error("preproc parse: unfinished str")
                    state = 0
                elif c == "\\": state = 35
                elif c == '"': state = 2
            elif state == 35: # in esp in '"' in arg in command
                arg += c
                state = 3
            elif state == 4: # in "'" in arg in command
                arg += c
                if c == "\n":
                    stateStruct.error("preproc parse: unfinished char str")
                    state = 0
                elif c == "\\": state = 45
                elif c == "'": state = 2
            elif state == 45: # in esp in "'" in arg in command
                arg += c
                state = 4
            elif state == 5: # after escape in arg in command
                if c == "\n": state = 2
                else: pass # ignore everything, wait for newline
            elif state == 10: # after '"'
                if not stateStruct._preprocessIgnoreCurrent: yield c
                if c == "\\": state = 11
                elif c == '"': state = 0
                else: pass
            elif state == 11: # escape in "str
                if not stateStruct._preprocessIgnoreCurrent: yield c
                state = 10
            elif state == 12: # after "'"
                if not stateStruct._preprocessIgnoreCurrent: yield c
                if c == "\\": state = 13
                elif c == "'": state = 0
                else: pass
            elif state == 13: # escape in 'str
                if not stateStruct._preprocessIgnoreCurrent: yield c
                state = 12
            elif state == 20: # after "/", possible start of comment
                if c == "*": state = 21 # C-style comment
                elif c == "/": state = 25 # C++-style comment
                else:
                    state = statebeforecomment
                    statebeforecomment = None
                    if state == 0:
                        if not stateStruct._preprocessIgnoreCurrent:
                            yield "/"
                            yield c
                    elif state == 2:
                        if arg is None: arg = ""
                        arg += "/" + c
                    else:
                        stateStruct.error("preproc parse: internal error after possible comment. didn't expect state " + str(state))
                        state = 0 # best we can do
            elif state == 21: # C-style comment
                if c == "*": state = 22
                else: pass
            elif state == 22: # C-style comment after "*"
                if c == "/":
                    state = statebeforecomment
                    statebeforecomment = None
                elif c == "*": pass
                else: state = 21
            elif state == 25: # C++-style comment
                if c == "\n":
                    state = statebeforecomment
                    statebeforecomment = None
                    breakLoop = False # rehandle return
                else: pass
            else:
                stateStruct.error("internal error: invalid state " + str(state))
                state = 0 # reset. it's the best we can do

        if c == "\n": stateStruct.incIncludeLineChar(line=1)
        elif c == "\t": stateStruct.incIncludeLineChar(char=4, charMod=4)
        else: stateStruct.incIncludeLineChar(char=1)

    # yield dummy additional new-line at end
    yield "\n"


class _CBase(object):
    def __init__(self, content=None, rawstr=None, **kwargs):
        self.content = content
        self.rawstr = rawstr
        for k,v in kwargs.items():
            setattr(self, k, v)
    def __repr__(self):
        if self.content is None: return "<" + self.__class__.__name__ + ">"
        return "<" + self.__class__.__name__ + " " + repr(self.content) + ">"
    def __eq__(self, other):
        return self.__class__ is other.__class__ and self.content == other.content
    def __ne__(self, other):
        return not self == other
    def __hash__(self): return hash(self.__class__) + 31 * hash(self.content)
    def asCCode(self, indent=""): return indent + self.content


class CStr(_CBase):
    def __repr__(self): return "<" + self.__class__.__name__ + " " + repr(self.content) + ">"
    def asCCode(self, indent=""): return indent + '"' + escape_cstr(self.content) + '"'


class CWideStr(CStr):
    """wchar_t string literal (L"...")"""
    def asCCode(self, indent=""): return indent + 'L"' + escape_cstr(self.content) + '"'


class CFuncName(CStr):
    """Sentinel for __func__: replaced with the enclosing function name at interpretation time."""
    def asCCode(self, indent=""): return indent + "__func__"


class CChar(_CBase):
    def __init__(self, content=None, rawstr=None, **kwargs):
        if isinstance(content, (unicode,str)): content = ord(content)
        assert isinstance(content, int), "CChar expects int, got " + repr(content)
        assert 0 <= content <= 255, "CChar expects number in range 0-255, got " + str(content)
        _CBase.__init__(self, content, rawstr, **kwargs)
    def __repr__(self): return "<" + self.__class__.__name__ + " " + repr(self.content) + ">"
    def asCCode(self, indent=""):
        assert isinstance(self.content, int)
        return indent + "'" + escape_cchar(chr(self.content)) + "'"


class CNumber(_CBase):
    typeSpec = None  # prefix like "f", "i" or so, or None
    def asCCode(self, indent=""): return indent + self.rawstr


class CIdentifier(_CBase): pass


class COp(_CBase): pass


class CSemicolon(_CBase):
    def asCCode(self, indent=""): return indent + ";"


class COpeningBracket(_CBase): pass


class CClosingBracket(_CBase): pass


_C_NUM_SUFFIX_CHARS = "uUlLfF"


def _combine_float_parts(left, right):
    """Combine `<int> . <int-or-float>` into a single C float literal.

    The cpre2 tokenizer deliberately doesn't assemble float literals -- it
    emits `0.0e0` as the token sequence [CNumber(0,"0"), COp("."),
    CNumber(0.0,"0e0")] -- and leaves it to the expression parser to glue
    the pieces back together.  Returns a (value, rawstr) pair suitable for
    constructing a new CNumber.  C numeric suffixes (f/F/l/L/u/U) on the
    right-hand lexeme are stripped before float conversion but preserved in
    the returned rawstr so round-tripping back to C source still works.

    :param CNumber left: token representing the integer part before the "."
    :param CNumber right: token representing the fractional/exponent part
    :rtype: tuple[float, str]
    """
    def _lexeme(num):
        return num.rawstr if num.rawstr is not None else str(num.content)
    raw = "%s.%s" % (_lexeme(left), _lexeme(right))
    raw_for_float = raw.rstrip(_C_NUM_SUFFIX_CHARS)
    return float(raw_for_float), raw


def cpre2_parse_number(stateStruct, s):
    if len(s) > 1 and s[0] == "0" and s[1] in NumberChars:
        try:
            s = s.rstrip("ULul")
            return long(s, 8)
        except Exception as e:
            stateStruct.error("cpre2_parse_number: " + s + " looks like octal but got error " + str(e))
            return 0
    if len(s) > 1 and s[0] == "0" and s[1] in "xX":
        try:
            s = s.rstrip("ULul")
            return long(s, 16)
        except Exception as e:
            stateStruct.error("cpre2_parse_number: " + s + " looks like hex but got error " + str(e))
            return 0
    try:
        s_stripped = s.rstrip("ULulfF")
        if 'e' in s_stripped.lower() or '.' in s_stripped:
            return float(s_stripped)
        return long(s_stripped)
    except Exception as e:
        stateStruct.error("cpre2_parse_number: " + s + " cannot be parsed: " + str(e))
        return 0


def _cpre2_parse_args(stateStruct, input, brackets, separator=COp(",")):
    """
    :type stateStruct: State
    :param iterable[char] input: like cpre2_parse
    :param list[str] brackets: opening brackets stack
    :param sep_type: the separator type, e.g. CSemicolon or COp
    :returns list of args, where each arg is a list of tokens from cpre2_parse.
    :rtype: list[list[token]]
    """
    initial_bracket_len = len(brackets)
    args = []
    for s in cpre2_parse(stateStruct, input, brackets=brackets):
        if len(brackets) < initial_bracket_len:
            # We got the final closing bracket. We have finished parsing the args.
            assert isinstance(s, CClosingBracket)
            assert len(brackets) == initial_bracket_len - 1
            return args
        if len(brackets) == initial_bracket_len and s == separator:
            args.append("")
        else:
            if not args: args.append("")
            if args[-1]: args[-1] += " "
            args[-1] += s.asCCode()
    stateStruct.error("cpre2 parse args: runaway")
    return args


class _Pre2ParseStream:
    def __init__(self, input):
        """
        :param str|typing.Iterable[str] input:
        """
        if isinstance(input, str):
            input = iter(input)
        self.input = input
        self.macro_blacklist = set()
        # Each frame: [macroname_or_None, buffer_str, pos].
        # We track ``pos`` as an index into ``buffer_str`` instead of
        # repeatedly slicing the string off its head -- that was
        # quadratic during large macro expansions.
        self.buffer_stack = [[None, "", 0]]
        # LIFO queue of chars that were read but need to be re-emitted
        # on the next ``next_char`` call (used by escape readers to
        # "put back" a non-matching char).
        self._putback = []

    def next_char(self):
        pb = self._putback
        if pb:
            return pb.pop()
        stack = self.buffer_stack
        # Fast path: no macro expansion in flight.  ``add_macro`` may
        # have stashed leftover chars into frame 0, so we still need to
        # honour that, but we avoid the full reverse loop.
        if len(stack) == 1:
            frame = stack[0]
            pos = frame[2]
            buf = frame[1]
            if pos < len(buf):
                frame[2] = pos + 1
                return buf[pos]
            try:
                return next(self.input)
            except StopIteration:
                return None
        for i in range(len(stack) - 1, -1, -1):
            frame = stack[i]
            pos = frame[2]
            buf = frame[1]
            if pos < len(buf):
                frame[2] = pos + 1
                return buf[pos]
        try:
            return next(self.input)
        except StopIteration:
            return None

    def putback_char(self, c):
        """Push *c* back so the next ``next_char()`` returns it."""
        self._putback.append(c)

    def add_macro(self, macroname, resolved, c):
        self.buffer_stack.append([macroname, resolved, 0])
        self.macro_blacklist.add(macroname)
        # Re-inject ``c`` so it's read *after* ``resolved`` is fully
        # consumed.  ``c`` is the char that followed the macro name and
        # must be reprocessed by the outer tokenizer.  We rebuild the
        # below frame's tail with ``c`` prepended; one-time cost per
        # macro expansion.
        below = self.buffer_stack[-2]
        below[1] = c + below[1][below[2]:]
        below[2] = 0

    def finalize_char(self, laststr):
        # Finalize buffer_stack here. Here because the macro_blacklist needs to be active
        # in the code above.
        # Pop ALL exhausted macro buffers in one go.  When macros expand to other macros
        # (e.g. SST → SIZEOF_SIZE_T → 8) both inner buffers may become empty before the
        # next token is started, so a single-level pop is not enough.
        stack = self.buffer_stack
        # Fast path: no macro frames to consider.
        if len(stack) == 1:
            return
        if not laststr and not self._putback:
            while len(stack) > 1 and stack[-1][2] >= len(stack[-1][1]):
                self.macro_blacklist.remove(stack[-1][0])
                stack.pop()


def cpre2_parse(stateStruct, input, brackets=None):
    """
    :param State stateStruct:
    :param str|typing.Iterable[str]|_Pre2ParseStream input: chars of preprocessed C code.
        except of macro substitution. usually via cpreprocess_parse().
    :param list[str]|None brackets: opening brackets stack
    :returns token iterator. this will also substitute macros
    The input comes more or less from cpreprocess_parse().
    This output will be handled by cpre3_parse().
    """
    state = 0
    if brackets is None: brackets = []
    if not isinstance(input, _Pre2ParseStream):
        input = _Pre2ParseStream(input)
    laststr = ""
    macroname = ""
    macroargs = []
    while True:
        c = input.next_char()
        if c is None:
            break
        breakLoop = False
        while not breakLoop:
            breakLoop = True
            if state == 0:
                if c in SpaceChars + "\n": pass
                elif c in NumberChars:
                    laststr = c
                    state = 10
                elif c == '"':
                    laststr = ""
                    state = 20
                elif c == "'":
                    laststr = ""
                    state = 25
                elif c in LetterChars + "_":
                    laststr = c
                    state = 30
                elif c in OpeningBrackets:
                    yield COpeningBracket(c, brackets=list(brackets))
                    brackets.append(c)
                elif c in ClosingBrackets:
                    if len(brackets) == 0 or ClosingBrackets[len(OpeningBrackets) - OpeningBrackets.index(brackets[-1]) - 1] != c:
                        stateStruct.error("cpre2 parse: got '" + c + "' but bracket level was " + str(brackets))
                    else:
                        brackets[:] = brackets[:-1]
                        yield CClosingBracket(c, brackets=list(brackets))
                elif c in OpChars:
                    laststr = ""
                    state = 40
                    breakLoop = False
                elif c == ";": yield CSemicolon()
                elif c == "\\": state = 1
                else:
                    stateStruct.error("cpre2 parse: didn't expected char %r in state %i" % (c, state))
            elif state == 1: # escape without context
                if c != "\n":
                    stateStruct.error("cpre2 parse: didn't expected char %r in state %i" % (c, state))
                # Just ignore it in any case.
                state = 0
            elif state == 10: # number (no correct float handling, will be [number, op("."), number])
                if c in NumberChars: laststr += c
                elif c in LetterChars + "_": laststr += c # error handling will be in number parsing, not here
                elif c in "+-" and laststr and laststr[-1] in "eE":
                    # Scientific notation exponent sign: 1e-6, 1E+3, etc.
                    laststr += c
                else:
                    yield CNumber(cpre2_parse_number(stateStruct, laststr), laststr)
                    laststr = ""
                    state = 0
                    breakLoop = False
            elif state == 20: # "str
                if c == '"':
                    yield CStr(laststr)
                    laststr = ""
                    state = 0
                elif c == "\\": state = 21
                else: laststr += c
            elif state == 21: # escape in "str
                if c == "x":
                    laststr += _read_hex_escape(input)
                elif c == "u":
                    laststr += _read_fixed_hex_escape(input, 4)
                elif c == "U":
                    laststr += _read_fixed_hex_escape(input, 8)
                elif c in _OctalChars:
                    # Multi-digit octal escape (1-3 digits).  C standard.
                    laststr += _read_octal_escape(input, c)
                else:
                    laststr += simple_escape_char(c)
                state = 20
            elif state == 25: # 'str
                if c == "'":
                    if len(laststr) > 1 and laststr[0] == '\0':  # hacky check for '\0abc'-like strings.
                        yield CChar(int(laststr[1:], 8))
                    else:
                        yield CChar(laststr)
                    laststr = ""
                    state = 0
                elif c == "\\": state = 26
                else: laststr += c
            elif state == 26: # escape in 'str
                if c == "x":
                    laststr += _read_hex_escape(input)
                elif c == "u":
                    laststr += _read_fixed_hex_escape(input, 4)
                elif c == "U":
                    laststr += _read_fixed_hex_escape(input, 8)
                elif c in _OctalChars:
                    # Multi-digit octal escape (1-3 digits).  C standard.
                    laststr += _read_octal_escape(input, c)
                else:
                    laststr += simple_escape_char(c)
                state = 25
            elif state == 22: # wchar "str (L"...")
                if c == '"':
                    yield CWideStr(laststr)
                    laststr = ""
                    state = 0
                elif c == "\\": state = 23
                else: laststr += c
            elif state == 23: # escape in wchar "str
                if c == "x":
                    laststr += _read_hex_escape(input)
                elif c == "u":
                    laststr += _read_fixed_hex_escape(input, 4)
                elif c == "U":
                    laststr += _read_fixed_hex_escape(input, 8)
                elif c in _OctalChars:
                    # Multi-digit octal escape (1-3 digits).  C standard.
                    laststr += _read_octal_escape(input, c)
                else:
                    laststr += simple_escape_char(c)
                state = 22
            elif state == 27: # wchar 'char' (L'...')
                if c == "'":
                    if len(laststr) == 1:
                        yield CChar(laststr)
                    else:
                        yield CChar(laststr)
                    laststr = ""
                    state = 0
                elif c == "\\": state = 28
                else: laststr += c
            elif state == 28: # escape in wchar 'char'
                if c == "x":
                    laststr += _read_hex_escape(input)
                elif c == "u":
                    laststr += _read_fixed_hex_escape(input, 4)
                elif c == "U":
                    laststr += _read_fixed_hex_escape(input, 8)
                elif c in _OctalChars:
                    # Multi-digit octal escape (1-3 digits).  C standard.
                    laststr += _read_octal_escape(input, c)
                else:
                    laststr += simple_escape_char(c)
                state = 27
            elif state == 30: # identifier
                if c in NumberChars + LetterChars + "_": laststr += c
                else:
                    if laststr in stateStruct.macros and laststr not in input.macro_blacklist:
                        macroname = laststr
                        macroargs = []
                        state = 31
                        if stateStruct.macros[macroname].args is None:
                            state = 32 # finalize macro directly. there can't be any args
                        breakLoop = False
                        laststr = ""
                    else:
                        if laststr == "__FILE__":
                            yield CStr(stateStruct.curFile())
                        elif laststr == "__LINE__":
                            yield CNumber(stateStruct.curLine())
                        elif laststr == "__func__":
                            yield CFuncName("")
                        elif laststr == "L" and c == '"':
                            laststr = ""
                            state = 22  # wchar string literal
                            continue  # consumed the '"'
                        elif laststr == "L" and c == "'":
                            laststr = ""
                            state = 27  # wchar char literal (treat like regular char)
                            continue  # consumed the "'"
                        else:
                            yield CIdentifier(laststr)
                        laststr = ""
                        state = 0
                        breakLoop = False
            elif state == 31: # after macro identifier
                if c in SpaceChars + "\n": pass
                elif c == "(":
                    macroargs = _cpre2_parse_args(stateStruct, input, brackets=brackets + [c])
                    state = 32
                    # break loop, we consumed this char
                else:
                    # C standard: a function-like macro (one with args) is only expanded
                    # when the name is followed by '('.  If we see any other character,
                    # do NOT expand — emit the name as a plain identifier.
                    if stateStruct.macros[macroname].args is not None:
                        yield CIdentifier(macroname)
                        macroname = ""
                        macroargs = []
                        state = 0
                        breakLoop = False
                    else:
                        # Object-like macro: expand immediately (no args needed).
                        state = 32
                        breakLoop = False
            elif state == 32: # finalize macro
                try:
                    resolved = stateStruct.macros[macroname].eval(stateStruct, macroargs)
                except Exception as e:
                    stateStruct.error("cpre2 parse unfold macro " + macroname + " error: " + repr(e))
                    resolved = ""
                input.add_macro(macroname, resolved, c)
                state = 0
            elif state == 40: # op
                if c in OpChars:
                    if laststr != "" and laststr + c not in LongOps:
                        yield COp(laststr)
                        laststr = ""
                    laststr += c
                else:
                    yield COp(laststr)
                    laststr = ""
                    state = 0
                    breakLoop = False
            else:
                stateStruct.error("cpre2 parse: internal error. didn't expected state " + str(state))
        input.finalize_char(laststr)


def cpre2_tokenstream_asCCode(input):
    needspace = False
    wantnewline = False
    indentLevel = ""
    needindent = False

    for token in input:
        if wantnewline:
            if isinstance(token, CSemicolon): pass
            else:
                yield "\n"
                needindent = True
            wantnewline = False
            needspace = False
        elif needspace:
            if isinstance(token, CSemicolon): pass
            elif token == COpeningBracket("("): pass
            elif token == CClosingBracket(")"): pass
            elif token == COpeningBracket("["): pass
            elif token == CClosingBracket("]"): pass
            elif token in [COp("++"), COp("--"), COp(",")]: pass
            else:
                yield " "
            needspace = False

        if token == CClosingBracket("}"): indentLevel = indentLevel[:-1]
        if needindent:
            yield indentLevel
            needindent = False

        yield token.asCCode()

        if token == COpeningBracket("{"): indentLevel += "\t"

        if token == CSemicolon(): wantnewline = True
        elif token == COpeningBracket("{"): wantnewline = True
        elif token == CClosingBracket("}"): wantnewline = True
        elif isinstance(token, COpeningBracket): pass
        elif isinstance(token, CClosingBracket): pass
        else: needspace = True


class CBody(object):
    def __init__(self, parent):
        self.parent = parent
        self._bracketlevel = []
        self.typedefs = {}
        self.structs = {}
        self.unions = {}
        self.enums = {}
        self.funcs = {}
        self.vars = {}
        self.enumconsts = {}
        self.contentlist = []  # type: typing.List[_CBaseWithOptBody]
    def __str__(self): return "CBody %s" % self.contentlist
    def __repr__(self): return "<%s>" % self
    def asCCode(self, indent=""):
        s = indent + "{\n"
        for c in self.contentlist:
            s += asCCode(c, indent + "\t", fullDecl=True) + ";\n"
        s += indent + "}"
        return s

class CEnumBody(CBody):
    def asCCode(self, indent=""):
        s = indent + "{\n"
        for c in self.contentlist:
            s += asCCode(c, indent + "\t") + ",\n"
        s += indent + "}"
        return s

def findIdentifierInBody(body, name):
    if name in body.enumconsts:
        return body.enumconsts[name]
    if body.parent is not None:
        return findIdentifierInBody(body.parent, name)
    return None

_TAGGED_BODY_DICTS = {
    "CStruct": "structs",
    "CUnion": "unions",
    "CEnum": "enums",
}


def make_type_from_typetokens(stateStruct, curCObj, type_tokens):
    if not type_tokens:
        return None
    if len(type_tokens) == 1 and isinstance(type_tokens[0], _CBaseWithOptBody):
        t = type_tokens[0]
        # ``cpre3_parse_funcargs`` creates a fresh bodyless ``CEnum`` /
        # ``CStruct`` / ``CUnion`` placeholder for tokens like
        # ``enum NAME``.  If the surrounding scope already has a
        # full-body declaration with the same tag, use that instead --
        # downstream code (e.g. ``CEnum.getNumRange``) needs the body.
        # The placeholder itself is still registered separately by its
        # own finalize for forward-decl correctness; we just resolve
        # the *use site* here.
        if (getattr(t, "body", None) is None and t.name is not None):
            dict_name = _TAGGED_BODY_DICTS.get(type(t).__name__)
            if dict_name is not None:
                resolved = findCObjTypeInNamespace(
                    stateStruct, curCObj, dict_name, t.name)
                if resolved is not None and getattr(resolved, "body", None) is not None:
                    t = resolved
    elif tuple(type_tokens) in stateStruct.CBuiltinTypes:
        t = CBuiltinType(tuple(type_tokens))
    elif len(type_tokens) > 1 and type_tokens[-1] == "*":
        t = CPointerType(make_type_from_typetokens(stateStruct, curCObj, type_tokens[:-1]))
    elif len(type_tokens) == 1:
        if not isinstance(type_tokens[0], (str, unicode)):
            stateStruct.error("type token is not expected str but %r" % (type_tokens[0],))
            t = None
        else:
            t = findObjInNamespace(stateStruct, curCObj, type_tokens[0])
            if not isType(t):
                stateStruct.error("type token is not a type: %s" % t)
                t = None
    elif type_tokens == [".", ".", "."]:
        t = CVariadicArgsType()
    else:
        stateStruct.error("make_type_from_typetokens: type tokens not handled: %s. curCObj: %s" % (type_tokens, curCObj))
        t = None
    return t


def asCCode(stmnt, indent="", fullDecl=False):
    if not fullDecl:
        if isinstance(stmnt, CFunc): return indent + stmnt.name
        if isinstance(stmnt, CStruct): return indent + "struct " + stmnt.name
        if isinstance(stmnt, CUnion): return indent + "union " + stmnt.name
        if isinstance(stmnt, CEnum): return indent + "enum " + stmnt.name
    if hasattr(stmnt, "asCCode"):
        return stmnt.asCCode(indent)
    assert False, "don't know how to handle " + str(stmnt)


class _CBaseWithOptBody(object):
    NameIsRelevant = True
    AutoAddToContent = True
    AlwaysNonZero = False
    StrOutAttribList = [
        ("args", bool, None, str),
        ("arrayargs", bool, None, str),
        ("body", None, None, lambda x: "<...>"),
        ("value", None, None, str),
        ("defPos", None, "@", str),
    ]

    def __init__(self, **kwargs):
        self._type_tokens = []
        self._bracketlevel = None
        self._finalized = False
        self.defPos = None
        self.type = None
        self.attribs = []
        self.name = None
        self.args = []
        self.arrayargs = []
        self.body = None
        self.value = None
        self.parent = None
        self.designators = []
        for k,v in kwargs.items():
            setattr(self, k, v)

    @classmethod
    def overtake(cls, obj):
        obj.__class__ = cls
        # no cls.__init__ because it would overwrite all our attribs!

    def isDerived(self):
        return self.__class__ != _CBaseWithOptBody

    def __str__(self):
        if self.NameIsRelevant:
            name = ("'" + self.name + "' ") if self.name else "<noname> "
        else:
            name = ("name: '" + self.name + "' ") if self.name else ""
        t = self.type or self._type_tokens
        l = []
        if self.attribs: l += [("attribs", self.attribs)]
        if t: l += [("type", t)]
        for attrName,addCheck,displayName,displayFunc in self.StrOutAttribList:
            a = getattr(self, attrName)
            if addCheck is None: addCheck = lambda x: x is not None
            if addCheck(a):
                if displayName is None: displayName = attrName
                l += [(displayName, displayFunc(a))]
        return \
            self.__class__.__name__ + " " + \
            name + \
            ", ".join(map((lambda a: a[0] + ": " + str(a[1])), l))

    def __repr__(self): return "<" + str(self) + ">"

    def __nonzero__(self):
        return \
            self.AlwaysNonZero or \
            bool(self._type_tokens) or \
            bool(self.type) or \
            bool(self.name) or \
            bool(self.args) or \
            bool(self.arrayargs) or \
            bool(self.body)

    __bool__ = __nonzero__

    def finalize(self, stateStruct, addToContent = None):
        if self._finalized:
            stateStruct.error("internal error: " + str(self) + " finalized twice")
            return
        self._finalized = True
        if self.defPos is None:
            self.defPos = stateStruct.curPosAsStr()
        if not self: return

        if addToContent is None: addToContent = self.AutoAddToContent

        #print "finalize", self, "at", stateStruct.curPosAsStr()
        if addToContent and self.parent is not None and self.parent.body and hasattr(self.parent.body, "contentlist"):
            self.parent.body.contentlist.append(self)

    def addToBody(self, obj):
        if self.body is None:
            self.body = obj
        else:
            assert isinstance(self.body, CBody)
            self.body.contentlist.append(obj)

    def _copy(self, value, parent=None, name=None, leave_out_attribs=()):
        if isinstance(value, (int, long, float, str, unicode)) or value is None:
            return value
        elif isinstance(value, list):
            return [self._copy(v, parent=parent) for v in value]
        elif isinstance(value, tuple):
            return tuple([self._copy(v, parent=parent) for v in value])
        elif isinstance(value, dict):
            return {k: self._copy(v, parent=parent) for (k, v) in value.items()}
        elif isinstance(value, (CSizeofSymbol, COffsetofSymbol)):
            # These are simple marker sentinels with no attributes; a fresh instance suffices.
            return value.__class__()
        elif isinstance(value, (_CBase, _CBaseWithOptBody, CType, CBody)):
            new = value.__class__.__new__(value.__class__)
            for k, v in vars(value).items():
                if k in leave_out_attribs:
                    continue
                if k == "parent":
                    new.parent = parent
                else:
                    setattr(new, k, self._copy(v, parent=new, name=k))
            return new
        else:
            assert False, "dont know how to handle %r %r (%s)" % (name, value, value.__class__)

    def copy(self, leave_out_attribs=("body",)):
        return self._copy(self, parent=self.parent, leave_out_attribs=leave_out_attribs)

    def depth(self):
        if self.parent is None: return 1
        return self.parent.depth() + 1

    def getCType(self, stateStruct):
        raise Exception(str(self) + " cannot be converted to a C type")

    def findAttrib(self, stateStruct, attrib):
        if self.body is None:
            # it probably is the pre-declaration. but we might find the real-one
            if isinstance(self, CStruct): D = "structs"
            elif isinstance(self, CUnion): D = "unions"
            elif isinstance(self, CEnum): D = "enums"
            
            self = getattr(stateStruct, D).get(self.name, self)
            
            if self.body is None and self.name:
                p = self.parent
                while p:
                    if hasattr(p, "body") and isinstance(p.body, CBody):
                        if self.name in getattr(p.body, D):
                            self = getattr(p.body, D)[self.name]
                            if self.body is not None: break
                    p = p.parent

        if self.body is None: return None
        for c in self.body.contentlist:
            if not isinstance(c, CVarDecl):
                if isinstance(c, (CStruct, CUnion)) and c.name is None:
                    # Anonymous struct/union. Search recursively.
                    sub = c.findAttrib(stateStruct, attrib)
                    if sub: return sub
                continue
            if c.name == attrib: return c
        return None

    def asCCode(self, indent=""):
        raise NotImplementedError(str(self) + " asCCode not implemented")


class CTypedef(_CBaseWithOptBody):
    def finalize(self, stateStruct):
        if self._finalized:
            stateStruct.error("internal error: " + str(self) + " finalized twice")
            return

        self.type = make_type_from_typetokens(stateStruct, self, self._type_tokens)
        _CBaseWithOptBody.finalize(self, stateStruct)

        if self.type is None:
            stateStruct.error("finalize typedef " + str(self) + ": type is unknown. type tokens: " + str(self._type_tokens))
            return
        if self.name is None:
            stateStruct.error("finalize typedef " + str(self) + ": name is unset")
            return

        self.parent.body.typedefs[self.name] = self
    def getCType(self, stateStruct): return getCType(self.type, stateStruct)
    def asCCode(self, indent=""):
        return indent + "typedef\n" + asCCode(self.type, indent, fullDecl=True) + " " + self.name

def resolveTypedef(t):
    while isinstance(t, CTypedef):
        t = t.type
    return t


class CFuncPointerBase(object): pass
class CFuncPointerDecl(_CBaseWithOptBody, CFuncPointerBase):
    def finalize(self, stateStruct, addToContent=None):
        if self._finalized:
            stateStruct.error("internal error: " + str(self) + " finalized twice")
            return

        if not self.type:
            self.type = make_type_from_typetokens(stateStruct, self, self._type_tokens)
        _CBaseWithOptBody.finalize(self, stateStruct, addToContent)

        if self.type is None:
            stateStruct.error("finalize " + str(self) + ": type is unknown. type tokens: " + str(self._type_tokens))
        # Name can be unset. It depends where this is declared.
    def getCType(self, stateStruct, workaroundPtrReturn=True, wrap=True):
        # We cache locally because the type might depend on workaroundPtrReturn/wrap.
        # get_cfunctype below provides additional global caching for the resulting signature.
        cache_attr = "_ctype_cached"
        if not hasattr(self, cache_attr):
            setattr(self, cache_attr, {})
        cache = getattr(self, cache_attr)
        cache_key = (workaroundPtrReturn, wrap)
        if cache_key in cache:
            return cache[cache_key]

        if workaroundPtrReturn and isinstance(self.type, CPointerType):
            # https://bugs.python.org/issue5710
            restype = ctypes.c_void_p
        else:
            restype = getCType(self.type, stateStruct)
        if wrap: restype = wrapCTypeClassIfNeeded(restype)
        argtypes = list(map(lambda a: getCType(a, stateStruct), self.args))
        if wrap: argtypes = list(map(wrapCTypeClassIfNeeded, argtypes))
        res = get_cfunctype(restype, *argtypes)
        cache[cache_key] = res
        return res
    def asCCode(self, indent=""):
        return indent + asCCode(self.type) + "(*" + self.name + ") (" + ", ".join(map(asCCode, self.args)) + ")"


_SIBLING_DICT = {"vars": "funcs", "funcs": "vars"}


def _addToParent(obj, stateStruct, dictName=None, listName=None, allowPredec=True):
    assert dictName or listName
    assert hasattr(obj.parent, "body")
    d = getattr(obj.parent.body, dictName or listName)
    if dictName:
        if obj.name is None:
            # might be part of a typedef, so don't error
            return

        # -----------------------------------------------------
        # Cross-dict collision detection (``vars`` vs ``funcs``).
        # -----------------------------------------------------
        # When the same name appears once as a CFunc and once as a
        # CVarDecl in the same scope, our parser stores them in two
        # separate dicts on the same body (``body.vars`` and
        # ``body.funcs``).  Downstream lookup paths usually consult
        # one dict first and silently fall back to the other, so the
        # "winner" depends on lookup order -- a fragile contract that
        # has masked real bugs in the past (e.g. a file-scope ``static
        # int X`` shadowed by an earlier prototype ``int X(void)``).
        #
        # Warn at parse time so the collision can't reach the
        # interpreter unnoticed.  We only warn ONCE per name per state.
        sibling_name = _SIBLING_DICT.get(dictName)
        if sibling_name is not None:
            sibling_dict = getattr(obj.parent.body, sibling_name, None)
            if sibling_dict and obj.name in sibling_dict:
                if not hasattr(stateStruct, "_reported_crossdict_collisions"):
                    stateStruct._reported_crossdict_collisions = set()
                key = (id(obj.parent.body), obj.name)
                if key not in stateStruct._reported_crossdict_collisions:
                    stateStruct._reported_crossdict_collisions.add(key)
                    other = sibling_dict[obj.name]
                    stateStruct.error(
                        "*** WARNING: cross-dict name collision ***\n"
                        "  %r exists as a %s and as a %s in the same scope.\n"
                        "    existing %s: %s\n"
                        "    new %s: %s\n"
                        "  Lookup order decides which one wins; rename one "
                        "side via a preprocessor macro before parsing."
                        % (obj.name, sibling_name[:-1], dictName[:-1],
                           sibling_name[:-1], other,
                           dictName[:-1], obj))

        if obj.name in d:
            old_obj = d[obj.name]
            old_has_body = getattr(old_obj, "body", None) is not None
            new_has_body = getattr(obj, "body", None) is not None

            # -----------------------------------------------------
            # File-scope ``static`` collision detection.
            # -----------------------------------------------------
            # In C, a file-scope ``static`` decl has internal linkage:
            # the name is visible only within its own translation
            # unit.  Two .c files can independently declare
            # ``static T x;`` and they are SEPARATE variables.  Our
            # parser merges all parsed TUs into one ``state.vars``,
            # so without this check the second decl silently
            # overwrites the first.  If the two declarations have
            # different types (eg. ``PyMethodObject *`` vs
            # ``PyCFunctionObject *``), the resulting type confusion
            # causes memory corruption at runtime -- this was the
            # root cause of the shutdown-gc SIGSEGV in cpython.py.
            #
            # We raise an ERROR (not just a warning) so the bug class
            # cannot reach the interpreter.  Callers who legitimately
            # have a same-named static across files must use a
            # preprocessor macro to rename one side
            # (``state.macros[name] = cparser.Macro(rightside=...)``);
            # see ``CPythonState.parse_cpython`` in ``cpython.py``
            # for examples.
            #
            # Conditions: BOTH old and new have ``static``, both are
            # real definitions with bodies (skips clinic-style
            # forward decls), they're in different files, and their
            # types differ (skips same-type intentional aliases like
            # ``_Py_Identifier PyId_builtins``).
            old_is_static = "static" in getattr(old_obj, "attribs", ())
            new_is_static = "static" in getattr(obj, "attribs", ())
            if (old_is_static and new_is_static
                    and old_has_body and new_has_body):
                def _file_of(o, fallback):
                    p = getattr(o, "defPos", None) or fallback
                    if not p or p in ("<out-of-scope>", "<unknown>"):
                        return ""
                    return p.rsplit(":", 2)[0]
                cur_pos = stateStruct.curPosAsStr()
                old_file = _file_of(old_obj, "")
                new_file = _file_of(obj, cur_pos)
                # Compare types.  ``obj.type`` may not be set yet
                # at "early add" time (``=`` seen, finalize pending);
                # compute it from ``_type_tokens`` so both sides have
                # a comparable representation.  No try/except: the
                # tokens are always complete by the time of this call
                # (the declaration's type is fully parsed before
                # ``=`` triggers early-add), so resolution is reliable.
                def _resolved_type(o):
                    t = getattr(o, "type", None)
                    if t is None:
                        toks = getattr(o, "_type_tokens", None)
                        if not toks:
                            return None
                        t = make_type_from_typetokens(stateStruct, o, toks)
                    # For functions, ``.type`` is just the RETURN type;
                    # build a stringly-typed signature (return + args)
                    # so two functions with the same return but different
                    # arg lists are recognized as incompatible.
                    if isinstance(o, CFunc):
                        sig = "%s(%s)" % (
                            t,
                            ", ".join(str(getattr(a, "type", "?")) for a in (o.args or [])),
                        )
                        return sig
                    return t
                old_type = _resolved_type(old_obj)
                new_type = _resolved_type(obj)
                if old_type is None or new_type is None:
                    types_match = True  # can't compare reliably
                elif str(old_type) == str(new_type):
                    types_match = True
                elif (isinstance(old_type, CArrayType)
                        and isinstance(new_type, CArrayType)
                        and str(old_type.arrayOf) == str(new_type.arrayOf)):
                    # Arrays of the SAME element type but different
                    # lengths.  This is technically a type-mismatch per
                    # ISO C, but in practice always benign read-only
                    # data: doc strings, method tables, etc.  Both
                    # files have their own `static char doc[N] = "..."`
                    # with N varying.  No size-mismatch corruption
                    # risk because the data is just READ (printed),
                    # never written through.  Don't error on this.
                    types_match = True
                else:
                    types_match = False
                # Dedupe so the error fires at most ONCE per name.
                if not hasattr(stateStruct,
                               "_reported_static_collisions"):
                    stateStruct._reported_static_collisions = set()
                already = obj.name in stateStruct._reported_static_collisions
                if (old_file and new_file and old_file != new_file
                        and not types_match
                        and not already):
                    stateStruct._reported_static_collisions.add(obj.name)
                    stateStruct.error(
                        "*** WARNING: TYPE-CONFUSION MEMORY CORRUPTION RISK ***\n"
                        "  Two file-scope ``static`` declarations of "
                        "%r have INCOMPATIBLE TYPES across translation "
                        "units:\n"
                        "    old:  %s\n"
                        "          type=%r\n"
                        "    new:  %s\n"
                        "          type=%r\n"
                        "  Per ISO C, file-scope ``static`` has "
                        "internal linkage -- these MUST be separate "
                        "variables.  cparser merges all translation "
                        "units into one ``state.vars`` and would "
                        "silently overwrite the older entry.  Code "
                        "in the older file would then read/write the "
                        "newer file's variable through a "
                        "mismatched-type pointer; in the interpreter "
                        "this manifests as SIGSEGV / silent heap "
                        "corruption (this was the root cause of the "
                        "shutdown-gc segfault in cpython.py; see "
                        "SEGFAULT_INVESTIGATION.md).\n"
                        "  Fix: rename one side via a preprocessor "
                        "macro before parsing it, e.g.\n"
                        "    state.macros[%r] = cparser.Macro("
                        "rightside=%r)\n"
                        "    cparser.parse(<the other file>, state)"
                        % (obj.name,
                           old_file, old_type,
                           new_file, new_type,
                           obj.name, obj.name + "_2"))

            if new_has_body:
                # Always overwrite if the new one has a body.
                # In C, it is an error if both have a body, but we don't strictly enforce it here yet
                # (or we expect the earlier parsing to have caught it).
                d[obj.name] = obj
            elif not new_has_body and old_has_body:
                pass  # Redundant prototype after definition (e.g. clinic-generated forward decl). Keep existing.
            elif allowPredec and not old_has_body:
                # Both have no body. Prefer CWrapValue.
                if isinstance(old_obj, CWrapValue):
                    pass # Keep old one
                else:
                    d[obj.name] = obj
            elif "extern" in getattr(old_obj, "attribs", []):
                # Otherwise, if we explicitely use the "extern" attribute, it's also ok.
                d[obj.name] = obj
            else:
                # Otherwise however, it is an error.
                if not old_has_body and not new_has_body:
                    pass # Both are just pre-declarations, that's fine.
                else:
                    stateStruct.error("finalize " + str(obj) + ": a previous equally named declaration exists: " + str(d[obj.name]))
        else:
            d[obj.name] = obj
    else:
        assert listName is not None
        d.append(obj)


def _finalizeBasicType(obj, stateStruct, dictName=None, listName=None, addToContent=None, allowPredec=True):
    if obj._finalized:
        stateStruct.error("internal error: " + str(obj) + " finalized twice")
        return

    if addToContent is None:
        addToContent = obj.name is not None

    if obj.type is None:
        obj.type = make_type_from_typetokens(stateStruct, obj, obj._type_tokens)
    _CBaseWithOptBody.finalize(obj, stateStruct, addToContent=None)

    if addToContent and hasattr(obj.parent, "body") and not getattr(obj, "_already_added", False):
        _addToParent(obj=obj, stateStruct=stateStruct, dictName=dictName, listName=listName, allowPredec=allowPredec)


class CFunc(_CBaseWithOptBody):
    finalize = lambda *args, **kwargs: _finalizeBasicType(*args, dictName="funcs", **kwargs)
    def getCType(self, stateStruct):
        restype = getCType(self.type, stateStruct)
        argtypes = list(map(lambda a: getCType(a, stateStruct), self.args))
        return get_cfunctype(restype, *argtypes)
    def asCCode(self, indent=""):
        s = indent + asCCode(self.type) + " " + self.name + "(" + ", ".join(map(asCCode, self.args)) + ")"
        if self.body is None: return s
        s += "\n"
        s += asCCode(self.body, indent)
        return s

class CVarDecl(_CBaseWithOptBody):
    finalize = lambda *args, **kwargs: _finalizeBasicType(*args, dictName="vars", allowPredec=False, **kwargs)
    def clearDeclForNextVar(self):
        if hasattr(self, "bitsize"): delattr(self, "bitsize")
        self.type = None
        while self._type_tokens and self._type_tokens[-1] in ("*",):
            self._type_tokens.pop()
    def asCCode(self, indent=""):
        s = indent + asCCode(self.type) + " " + self.name
        if self.body is None: return s
        s += " = "
        s += asCCode(self.body)
        return s


def needWrapCTypeClass(t):
    if t is None:
        return False
    return t.__base__ is _ctypes._SimpleCData


_pointer_type_cache = {}
def get_pointer_type(t):
    """
    ctypes.POINTER(t) creates a new type class on every call.
    We need to cache it to ensure that logically identical pointer types
    have the same Python object identity, which is required by ctypes
    for type compatibility in some cases (e.g. function pointers, struct fields).
    """
    if t in _pointer_type_cache:
        return _pointer_type_cache[t]
    res = ctypes.POINTER(t)
    _pointer_type_cache[t] = res
    return res


_cfunctype_cache = {}
def get_cfunctype(restype, *argtypes):
    """
    ctypes.CFUNCTYPE(...) creates a new type class on every call.
    Global caching ensures that identical function signatures result in
    the same type instance, avoiding 'incompatible types' errors in ctypes.
    """
    key = (restype, tuple(argtypes))
    if key in _cfunctype_cache:
        return _cfunctype_cache[key]
    if _cfunctype_cache: # Only print after initialization to avoid noise
        pass # print("get_cfunctype", restype, argtypes)
    res = ctypes.CFUNCTYPE(restype, *argtypes)
    _cfunctype_cache[key] = res
    return res


def wrapCTypeClassIfNeeded(t):
    if needWrapCTypeClass(t): return wrapCTypeClass(t)
    else: return t


_wrapCTypeClassCache = {}


def wrapCTypeClass(t):
    if id(t) in _wrapCTypeClassCache:
        return _wrapCTypeClassCache[id(t)]
    class WrappedType(t):
        def __repr__(self):
            return "%s(%r)" % (t.__name__, self.value)
    WrappedType.__name__ = "wrapCTypeClass_%s" % t.__name__
    _wrapCTypeClassCache[id(t)] = WrappedType
    return WrappedType

class CTypeConstructionException(Exception): pass
class RecursiveStructConstruction(CTypeConstructionException): pass

def _getCTypeStruct(baseClass, obj, stateStruct):

    def _construct(obj):
        fields = []
        anonymous = []
        for c in obj.body.contentlist:
            if isinstance(c, (CStruct, CUnion)) and c.name is None:
                t = getCType(c, stateStruct)
                name = "__anon_" + str(len(fields))
                fields += [(name, t)]
                anonymous += [name]
                continue
            if not isinstance(c, CVarDecl): continue
            try:
                obj._construct_struct_attrib = c.type
                if isinstance(c.type, CArrayType) and not c.type.arrayLen and c is obj.body.contentlist[-1]:
                    # C flexible array member. It contributes no size to the
                    # struct header but its address is the start of trailing
                    # allocation bytes.
                    inner = getCType(c.type.arrayOf, stateStruct)
                    # ctypes converts (c_char * N) fields to Python bytes objects when
                    # accessed through a structure, which loses the struct-backed address
                    # needed for pointer arithmetic. Use c_ubyte instead so the field
                    # is returned as a ctypes Array with the correct in-struct address.
                    if inner is ctypes.c_char:
                        inner = ctypes.c_ubyte
                    t = inner * 0
                else:
                    t = getCType(c.type, stateStruct)
            finally:
                obj._construct_struct_attrib = None
            if c.arrayargs:
                if len(c.arrayargs) != 1: raise Exception(str(c) + " has too many array args")
                n = c.arrayargs[0].value
                t = t * n
            elif stateStruct.IndirectSimpleCTypes:
                # See http://stackoverflow.com/questions/6800827/python-ctypes-structure-how-to-access-attributes-as-if-they-were-ctypes-and-not/6801253#6801253
                t = wrapCTypeClassIfNeeded(t)
            # ``py_safe_identifier`` renames Python reserved words
            # (e.g. ``def`` from ``struct { PyMethodDef def; }`` in
            # codecs.c) by appending ``_``.  Applied consistently at
            # struct-field definition AND at every attribute-access
            # site, so the two sides stay in sync.
            field_name = py_safe_identifier(str(c.name))
            if hasattr(c, "bitsize"):
                # Bitfields must use unwrapped types, otherwise ctypes ignores bitsize.
                if t.__name__.startswith("wrapCTypeClass_"):
                    t = t.__bases__[0]
                fields += [(field_name, t, c.bitsize)]
            else:
                fields += [(field_name, t)]
        if obj._ctype_is_constructing:
            if anonymous:
                obj._ctype._anonymous_ = anonymous
            obj._ctype._fields_ = fields
            obj._ctype_is_constructing = False

    def construct(obj):
        try:
            stateStruct._construct_struct_type_stack += [obj]
            _construct(obj)
        finally:
            stateStruct._construct_struct_type_stack.pop()

    if getattr(obj, "_ctype_is_constructing", None):
        # If the parent referred to us as a pointer, it's fine,
        # we can return our incomplete type.
        if isPointerType(
            stateStruct._construct_struct_type_stack[-1]._construct_struct_attrib,
            alsoFuncPtr=True, alsoArray=False):
            return obj._ctype
        # Otherwise, try to construct it now.
        if obj._ctype_construct_need_now:
            raise RecursiveStructConstruction("Recursive construction of type %s" % obj)
        obj._ctype_construct_need_now = True
        construct(obj)
        return obj._ctype

    if hasattr(obj, "_ctype"):
        # Cache to ensure consistent type identity.
        return obj._ctype
    if not hasattr(obj, "body"):
        raise CTypeConstructionException("%s must have the body attrib" % obj)
    if obj.body is None:
        raise CTypeConstructionException("%s.body must not be None. maybe it was only forward-declarated?" % obj)

    class ctype(baseClass): pass
    ctype.__name__ = str(obj.name or "<anonymous-struct>")
    ctype._py = obj
    obj._ctype = ctype
    obj._ctype_is_constructing = True
    obj._ctype_construct_need_now = False
    construct(obj)
    return ctype


def _resolveForwardDecl(obj, dictName, stateStruct):
    """If *obj* is a forward declaration (body=None), try to find the real definition
    in *stateStruct*.  Returns the resolved object (or *obj* unchanged if none found).
    Also caches the result on *obj* so repeated lookups are O(1).
    """
    if obj.body is not None:
        return obj
    if not obj.name:
        return obj
    # Search the global (and parent-scope) structs/unions dict for a definition
    # with the same name that has a body.
    real = getattr(stateStruct, dictName, {}).get(obj.name)
    if real is not None and real.body is not None:
        return real
    # Also walk up through parent scopes (nested struct definitions).
    p = obj.parent
    while p:
        if hasattr(p, "body") and isinstance(p.body, CBody):
            real = getattr(p.body, dictName, {}).get(obj.name)
            if real is not None and real.body is not None:
                return real
        p = getattr(p, "parent", None)
    return obj


class CStruct(_CBaseWithOptBody):
    finalize = lambda *args, **kwargs: _finalizeBasicType(*args, dictName="structs", **kwargs)
    def getCType(self, stateStruct):
        # Some parsed "struct X" references are represented as an anonymous
        # CStruct that points to the typedef object for X. Resolve through the
        # typedef first so we don't try to construct an incomplete body=None struct.
        if self.body is None and isinstance(getattr(self, "type", None), CTypedef):
            return getCType(self.type, stateStruct)
        obj = _resolveForwardDecl(self, "structs", stateStruct)
        result = _getCTypeStruct(ctypes.Structure, obj, stateStruct)
        if obj is not self and not hasattr(self, "_ctype"):
            # Cache the resolved ctype on the forward-declaration object too,
            # so that future getCType calls on it are fast (O(1)).
            self._ctype = result
        return result
    def asCCode(self, indent=""):
        s = indent + "struct " + self.name
        if self.body is None: return s
        return s + "\n" + asCCode(self.body, indent)


class CUnion(_CBaseWithOptBody):
    finalize = lambda *args, **kwargs: _finalizeBasicType(*args, dictName="unions", **kwargs)
    def getCType(self, stateStruct):
        obj = _resolveForwardDecl(self, "unions", stateStruct)
        result = _getCTypeStruct(ctypes.Union, obj, stateStruct)
        if obj is not self and not hasattr(self, "_ctype"):
            self._ctype = result
        return result
    def asCCode(self, indent=""):
        s = indent + "union " + self.name
        if self.body is None: return s
        return s + "\n" + asCCode(self.body, indent)


def minCIntTypeForNums(a, b=None, minBits=32, maxBits=64, useUnsignedTypes=True):
    if b is None: b = a
    bits = minBits
    while bits <= maxBits:
        if a >= -(1<<(bits-1)) and b < (1<<(bits-1)): return "int" + str(bits) + "_t"
        if useUnsignedTypes and a >= 0 and b < (1<<bits): return "uint" + str(bits) + "_t"
        bits *= 2
    return None


def _parseIntLiteralSuffix(rawstr):
    """Extract C99 integer-literal suffix info from a lexeme.

    Returns ``(is_unsigned, long_count, is_hex_or_octal)`` where
    ``long_count`` is 0 for no ``L``, 1 for ``l``/``L``, 2 for ``ll``/``LL``.
    See C99 §6.4.4.1.
    """
    if not rawstr:
        return False, 0, False
    s = rawstr
    # Distinguish bases: hex starts with ``0x``/``0X``; octal starts with
    # ``0`` followed by another digit; decimal otherwise.  A bare ``0`` is
    # decimal-or-octal-equivalent (value 0); treat as decimal.
    is_hex_or_octal = False
    if len(s) >= 2 and s[0] == "0" and s[1] in "xX":
        is_hex_or_octal = True
    elif len(s) >= 2 and s[0] == "0" and s[1].isdigit():
        is_hex_or_octal = True
    # Strip suffix chars from the right.  Suffixes (any order):
    # ``u``/``U`` once; ``l``/``L`` once or twice (must be same case in C99
    # but be lenient).
    suffix_chars = ""
    while s and s[-1] in "uUlL":
        suffix_chars = s[-1] + suffix_chars
        s = s[:-1]
    lc = suffix_chars.lower()
    is_unsigned = "u" in lc
    long_count = lc.count("l")
    return is_unsigned, long_count, is_hex_or_octal


def cIntTypeForLiteral(value, rawstr):
    """Pick the C type of an integer literal per C99 §6.4.4.1.

    For a decimal literal without suffix the candidate list is
    ``int``, ``long``, ``long long`` -- only signed.  For hex/octal
    without suffix the list interleaves unsigned variants.  Suffixes
    restrict the list.

    The picked type is returned as a stdint name (``int32_t``,
    ``uint32_t``, ``int64_t``, ``uint64_t``).  Assumes 64-bit Unix
    ABI: ``int``=32, ``long``=``long long``=64.
    """
    is_unsigned, long_count, is_hex_or_octal = _parseIntLiteralSuffix(rawstr)
    # Candidate list per the standard.
    if long_count == 0 and not is_unsigned:
        if is_hex_or_octal:
            candidates = ["int32_t", "uint32_t", "int64_t", "uint64_t"]
        else:
            candidates = ["int32_t", "int64_t"]
    elif long_count == 0 and is_unsigned:
        # u/U suffix: unsigned int, unsigned long, unsigned long long.
        candidates = ["uint32_t", "uint64_t"]
    elif long_count >= 1 and not is_unsigned:
        # l/L or ll/LL suffix: at-least-long.
        if is_hex_or_octal:
            candidates = ["int64_t", "uint64_t"]
        else:
            candidates = ["int64_t"]
    else:  # long_count >= 1 and is_unsigned
        candidates = ["uint64_t"]
    for t in candidates:
        if t.startswith("uint"):
            bits = int(t[4:-2])
            if 0 <= value < (1 << bits):
                return t
        else:
            bits = int(t[3:-2])
            if -(1 << (bits - 1)) <= value < (1 << (bits - 1)):
                return t
    return None  # doesn't fit any candidate type


class CEnum(_CBaseWithOptBody):
    finalize = lambda *args, **kwargs: _finalizeBasicType(*args, dictName="enums", **kwargs)
    def getNumRange(self):
        a,b = 0,0
        for c in self.body.contentlist:
            assert isinstance(c, CEnumConst)
            if c.value < a: a = c.value
            if c.value > b: b = c.value
        return a,b
    def getMinCIntType(self):
        a,b = self.getNumRange()
        t = minCIntTypeForNums(a, b)
        return t
    def getEnumConst(self, value):
        for c in self.body.contentlist:
            if not isinstance(c, CEnumConst): continue
            if c.value == value: return c
        return None
    def getCType(self, stateStruct):
        t = self.getMinCIntType()
        if t is None:
            raise Exception(str(self) + " has a too high number range")
        t = stateStruct.StdIntTypes[t]
        return t
        # class EnumType(t):
        # 	_typeStruct = self
        # 	def __repr__(self):
        # 		v = self._typeStruct.getEnumConst(self.value)
        # 		if v is None: v = self.value
        # 		return "<EnumType " + str(v) + ">"
        # 	def __cmp__(self, other):
        # 		return cmp(self.value, other)
        # for c in self.body.contentlist:
        # 	if not c.name: continue
        # 	if hasattr(EnumType, c.name): continue
        # 	setattr(EnumType, c.name, c.value)
        # return EnumType
    def asCCode(self, indent=""):
        s = indent + "enum " + self.name
        if self.body is None: return s
        return s + "\n" + asCCode(self.body, indent)


class CEnumConst(_CBaseWithOptBody):
    def finalize(self, stateStruct, addToContent=None):
        if self._finalized:
            stateStruct.error("internal error: " + str(self) + " finalized twice")
            return

        if self.value is None:
            if self.parent.body.contentlist:
                last = self.parent.body.contentlist[-1]
                if isinstance(last.value, (str,unicode)):
                    self.value = unichr(ord(last.value) + 1)
                else:
                    self.value = last.value + 1
            else:
                self.value = 0

        _CBaseWithOptBody.finalize(self, stateStruct, addToContent)

        if self.name:
            # self.parent.parent is the parent of the enum
            self.parent.parent.body.enumconsts[self.name] = self
    def getConstValue(self, stateStruct):
        return self.value
    def asCCode(self, indent=""):
        return indent + self.name + " = " + str(self.value)


class CFuncArgDecl(_CBaseWithOptBody):
    AutoAddToContent = False
    def finalize(self, stateStruct, addToContent=False):
        if self._finalized:
            stateStruct.error("internal error: " + str(self) + " finalized twice")
            return

        if not self.type:
            self.type = make_type_from_typetokens(stateStruct, self, self._type_tokens)
        _CBaseWithOptBody.finalize(self, stateStruct, addToContent=False)

        if self.type != CBuiltinType(("void",)):
            self.parent.args += [self]
    def getCType(self, stateStruct):
        return getCType(self.type, stateStruct)
    def asCCode(self, indent=""):
        s = indent + asCCode(self.type)
        if self.name: s += " " + self.name
        return s


def _isBracketLevelOk(parentLevel, curLevel):
    if parentLevel is None: parentLevel = []
    if len(parentLevel) > len(curLevel): return False
    return curLevel[:len(parentLevel)] == parentLevel


def _body_parent_chain(stateStruct, parentCObj):
    yieldedStateStruct = False

    for cobj in _obj_parent_chain(stateStruct, parentCObj):
        body = cobj.body
        if isinstance(body, CBody):
            yieldedStateStruct |= body is stateStruct
            yield body

    if not yieldedStateStruct: yield stateStruct


def _obj_parent_chain(stateStruct, parentCObj):
    while parentCObj is not None:
        yield parentCObj
        parentCObj = parentCObj.parent


def getObjInBody(body, name):
    """
    :type body: CBody | State
    :type name: str
    :return: object, statement or type
    """
    if name in body.funcs:
        return body.funcs[name]
    elif name in body.typedefs:
        return body.typedefs[name]
    elif name in body.vars:
        return body.vars[name]
    elif name in body.enumconsts:
        return body.enumconsts[name]
    elif (name,) in getattr(body, "CBuiltinTypes", {}):
        return CBuiltinType((name,))
    elif name in getattr(body, "StdIntTypes", {}):
        return CStdIntType(name)
    return None

def findObjInNamespace(stateStruct, curCObj, name):
    for cobj in _obj_parent_chain(stateStruct, curCObj):
        if isinstance(cobj.body, (CBody,State)):
            obj = getObjInBody(cobj.body, name)
            if obj is not None: return obj
        if isinstance(cobj, CFunc):
            for arg in cobj.args:
                assert isinstance(arg, CFuncArgDecl)
                if arg.name is not None and arg.name == name:
                    return arg
            if cobj.name == name:
                return cobj
    return None


def findCObjTypeInNamespace(stateStruct, curCObj, DictName, name):
    for body in _body_parent_chain(stateStruct, curCObj):
        d = getattr(body, DictName)
        if name in d: return d[name]
    return None


class _CStatementCall(_CBaseWithOptBody):
    AutoAddToContent = False
    base = None
    def __nonzero__(self): return self.base is not None
    __bool__ = __nonzero__
    def __str__(self):
        s = self.__class__.__name__ + " " + repr(self.base)
        if self.name:
            s += " name: " + self.name
        else:
            s += " args: " + str(self.args)
        return s


class CFuncCall(_CStatementCall): # base(args) or (base)args; i.e. can also be a simple cast
    def asCCode(self, indent=""):
        return indent + asCCode(self.base) + "(" + ", ".join(map(asCCode, self.args)) + ")"


class CArrayIndexRef(_CStatementCall): # base[args]
    def asCCode(self, indent=""):
        return indent + asCCode(self.base) + "[" + ", ".join(map(asCCode, self.args)) + "]"


class CAttribAccessRef(_CStatementCall): # base.name
    def asCCode(self, indent=""):
        return indent + asCCode(self.base) + "." + self.name


class CPtrAccessRef(_CStatementCall): # base->name
    def asCCode(self, indent=""):
        return indent + asCCode(self.base) + "->" + self.name


def _create_cast_call(stateStruct, parent, base, token):
    funcCall = CFuncCall(parent=parent)
    funcCall.base = base
    arg = CStatement(parent=funcCall)
    funcCall.args = [arg]
    arg._cpre3_handle_token(stateStruct, token)
    funcCall.finalize(stateStruct)
    return funcCall


def opsDoLeftToRight(stateStruct, op1, op2, prefix1=False):
    if prefix1:
        opprec1 = 3
    else:
        try: opprec1 = OpPrecedences[op1]
        except KeyError:
            stateStruct.error("internal error: statement parsing: op1 " + repr(op1) + " unknown")
            opprec1 = 100
    try: opprec2 = OpPrecedences[op2]
    except KeyError:
        stateStruct.error("internal error: statement parsing: op2 " + repr(op2) + " unknown")
        opprec2 = 100

    if opprec1 < opprec2:
        return True
    elif opprec1 > opprec2:
        return False
    if op1 in OpsRightToLeft or prefix1:
        return False
    return True


def isCompleteType(t):
    while isinstance(t, CTypedef):
        t = t.type
    if isinstance(t, (CStruct, CUnion, CEnum)):
        return t.body is not None
    if isinstance(t, CArrayType):
        return t.arrayLen is not None
    return True


def getConstValue(stateStruct, obj):
    """
    Evaluates the obj, in case it is a expression which can be evaluated at compile time.
    """
    if hasattr(obj, "getConstValue"): return obj.getConstValue(stateStruct)
    if isinstance(obj, (CNumber,CStr,CChar)):
        return obj.content
    if isinstance(obj, CFuncCall):  # maybe a cast or sizeof
        if isinstance(obj.base, CSizeofSymbol):
            assert len(obj.args) == 1
            t = getValueType(stateStruct, obj.args[0])
            if t is None: return None
            if not isCompleteType(t): return None
            ctype = getCType(t, stateStruct)
            return ctypes.sizeof(ctype)

        t = obj.base
        while isinstance(t, CTypedef):
            t = t.type
        if isinstance(t, (CBuiltinType, CStdIntType)):  # only number types
            assert len(obj.args) == 1
            v = getConstValue(stateStruct, obj.args[0])
            if v is None: return None  # cannot handle anyway
            ctype = getCType(t, stateStruct)
            if isIntType(obj.base): v = int(v)
            if v: cv = ctype(v)
            else: cv = ctype()
            return cv.value
    return None


def getValueType(stateStruct, obj):
    if hasattr(obj, "getValueType"): return obj.getValueType(stateStruct)
    if isinstance(obj, CVarDecl):
        return obj.type
    if isinstance(obj, CFuncArgDecl):
        return obj.type
    if isinstance(obj, CAttribAccessRef):
        base_type = getValueType(stateStruct, obj.base)
        while isinstance(base_type, CTypedef):
            base_type = base_type.type
        assert isinstance(base_type, (CStruct,CUnion))
        attrib = base_type.findAttrib(stateStruct, obj.name)
        if attrib is None:
            stateStruct.error("attrib %r not found in %r" % (obj.name, base_type))
            return CBuiltinType(("int",))
        return attrib.type
    if isinstance(obj, CPtrAccessRef):
        pbase_type = getValueType(stateStruct, obj.base)
        while isinstance(pbase_type, CTypedef):
            pbase_type = pbase_type.type
        assert isinstance(pbase_type, CPointerType)
        base_type = pbase_type.pointerOf
        while isinstance(base_type, CTypedef):
            base_type = base_type.type
        assert isinstance(base_type, (CStruct,CUnion))
        attrib = base_type.findAttrib(stateStruct, obj.name)
        if attrib is None:
            stateStruct.error("attrib %r not found in %r" % (obj.name, base_type))
            return CBuiltinType(("int",))
        return attrib.type
    if isinstance(obj, CArrayIndexRef):
        t = getValueType(stateStruct, obj.base)
        while isinstance(t, CTypedef):
            t = t.type
        if isinstance(t, CArrayType):
            return t.arrayOf
        elif isinstance(t, CPointerType):
            return t.pointerOf
        assert False, "unknown attrib base type %r of obj %r" % (t, obj)
    if isinstance(obj, CFuncCall):
        if isinstance(obj.base, CWrapValue):
            return obj.base.getReturnType(stateStruct, obj.args)
        # Check for cast-like calls.
        if isinstance(obj.base, (CTypedef, CType)):
            return obj.base
        base_type = getValueType(stateStruct, obj.base)
        while isinstance(base_type, CTypedef):
            base_type = base_type.type
        assert isinstance(base_type, (CFuncPointerDecl,CFunc))
        return base_type.type  # return-type
    if isinstance(obj, CFunc):
        return obj
    if isinstance(obj, (CSizeofSymbol, COffsetofSymbol)):
        return CFunc(type=CStdIntType("size_t"))
    if isinstance(obj, CStr):
        return CArrayType(arrayOf=CBuiltinType(("char",)), arrayLen=CNumber(len(obj.content) + 1))
    if isinstance(obj, CChar):
        return CBuiltinType(("char",))
    if isinstance(obj, CNumber):
        if isinstance(obj.content, float):
            return CBuiltinType(("double",))
        # Per C99 §6.4.4.1 -- suffix + base aware.
        t = cIntTypeForLiteral(obj.content, obj.rawstr)
        if t is None:
            t = "int64_t"  # genuine overflow; just take the largest
        return CStdIntType(t)
    if isinstance(obj, CEnumConst):
        enumType = obj.parent
        assert isinstance(enumType, CEnum)
        return enumType
    if isinstance(obj, (CType, CTypedef, CStruct, CUnion, CEnum)):
        return obj
    assert False, "no type for %r" % obj


def getCommonValueType(stateStruct, t1, t2):
    while isinstance(t1, CTypedef):
        t1 = t1.type
    while isinstance(t2, CTypedef):
        t2 = t2.type
    # ``getValueType`` for ``CSizeofSymbol`` / ``COffsetofSymbol``
    # returns a synthetic ``CFunc(type=size_t)``.  Unwrap to the
    # return type so arithmetic between a pointer and ``sizeof(...)``
    # behaves like pointer + size_t (rather than tripping the
    # ``isinstance(t2, (CBuiltinType, CStdIntType))`` assert below).
    if isinstance(t1, CFunc):
        t1 = t1.type
    if isinstance(t2, CFunc):
        t2 = t2.type
    if isclass(t1) and issubclass(t1, ctypes._SimpleCData):
        t1 = getBuiltinTypeForCType(stateStruct, t1)
    if isclass(t2) and issubclass(t2, ctypes._SimpleCData):
        t2 = getBuiltinTypeForCType(stateStruct, t2)
    if t1 in (ctypes.c_void_p, CPointerType(CVoidType()), CPointerType(CBuiltinType(("void",)))):
        t1 = CBuiltinType(("void","*"))
    if t2 in (ctypes.c_void_p, CPointerType(CVoidType()), CPointerType(CBuiltinType(("void",)))):
        t2 = CBuiltinType(("void","*"))
    if t1 == CBuiltinType(("void","*")):
        if t2 == CBuiltinType(("void","*")):
            return t1
        if isinstance(t2, (CPointerType, CFuncPointerBase)):
            return t2
        if isinstance(t2, CArrayType):
            return CPointerType(t2.arrayOf)
        assert isinstance(t2, (CBuiltinType, CStdIntType))
        return t1
    if t2 == CBuiltinType(("void","*")):
        return getCommonValueType(stateStruct, t2, t1)
    if isinstance(t1, CPointerType):
        if isinstance(t2, CPointerType):
            if not isSameType(stateStruct, t1.pointerOf, t2.pointerOf):
                import sys as _sys
                print("[debug getCommonValueType pointers differ] t1.pointerOf=%r t2.pointerOf=%r"
                      % (t1.pointerOf, t2.pointerOf), file=_sys.stderr)
            assert isSameType(stateStruct, t1.pointerOf, t2.pointerOf)
            return t1
        if isinstance(t2, CArrayType):
            assert isSameType(stateStruct, t1.pointerOf, t2.arrayOf)
            return t1
        assert isinstance(t2, (CBuiltinType, CStdIntType))
        return t1
    if isinstance(t2, CPointerType):
        return getCommonValueType(stateStruct, t2, t1)
    if isinstance(t1, CArrayType) or isinstance(t2, CArrayType):
        if isinstance(t1, CArrayType) and isinstance(t2, CArrayType):
            if isSameType(stateStruct, t1, t2): return t1
        if isinstance(t1, CArrayType):
            t1 = CPointerType(t1.arrayOf)
        if isinstance(t2, CArrayType):
            t2 = CPointerType(t2.arrayOf)
        return getCommonValueType(stateStruct, t1, t2)
    if isinstance(t1, CFuncPointerBase):
        return t1  # ...
    if isinstance(t2, CFuncPointerBase):
        return t2  # ...
    # No pointers.
    if isinstance(t1, CBuiltinType) and isinstance(t2, CBuiltinType):
        tup1 = t1.builtinType
        tup2 = t2.builtinType
        if "float" in tup1 or "double" in tup1:
            if "float" in tup2 or "double" in tup2:
                # Select bigger type.
                Ts = [("float",), ("double",), ("long", "double")]
                if Ts.index(tup2) > Ts.index(tup1):
                    return t2
                return t1
            return t1  # Cast int to float.
        if "float" in tup2 or "double" in tup2:
            return t2  # Cast int to float.
        # No floats.
        Is = {("char",): 1, ("short",): 2,
              ("int",): 3, ("signed",): 3, (): 3,
              ("long",): 4, ("long", "long"): 5}
        invI = {1: ("char",), 2: ("short",), 3: ("int",),
                4: ("long",), 5: ("long", "long")}
        unsigned_t1 = "unsigned" in tup1
        unsigned_t2 = "unsigned" in tup2
        if unsigned_t1: assert tup1[0] == "unsigned"
        if unsigned_t2: assert tup2[0] == "unsigned"
        ti1 = Is[tup1[1 if unsigned_t1 else 0:]]
        ti2 = Is[tup2[1 if unsigned_t2 else 0:]]
        st_max = invI[max(ti1, ti2)]
        t_max = (("unsigned",) if (unsigned_t1 or unsigned_t2) else ()) + st_max
        return CBuiltinType(t_max)
    if isinstance(t1, CStdIntType) and isinstance(t2, CStdIntType):
        def base_wrap(name):
            if name == "byte": return "int8_t"
            if name == "wchar_t": return "int16_t"
            return name
        t1_name = base_wrap(t1.name)
        t2_name = base_wrap(t2.name)
        BuiltinWraps = {"size_t": ("unsigned", "long"),
                        "ptrdiff_t": ("long",),
                        "intptr_t": ("long",),
                        "uintptr_t": ("unsigned", "long"),
                        "intmax_t": ("long", "long"),
                        "uintmax_t": ("unsigned", "long", "long")}
        if t1_name in BuiltinWraps:
            t1 = CBuiltinType(BuiltinWraps[t1_name])
            return getCommonValueType(stateStruct, t1, t2)
        if t2_name in BuiltinWraps:
            t2 = CBuiltinType(BuiltinWraps[t2_name])
            return getCommonValueType(stateStruct, t1, t2)
        unsigned_t1 = t1_name[:1] == "u"
        unsigned_t2 = t2_name[:1] == "u"
        Is = {"int8_t": 8, "int16_t": 16, "int32_t": 32, "int64_t": 64}
        ti1 = Is[t1_name[1 if unsigned_t1 else 0:]]
        ti2 = Is[t2_name[1 if unsigned_t2 else 0:]]
        st_max = "int%s_t" % max(ti1, ti2)
        t_max = ("u" if (unsigned_t1 or unsigned_t2) else "") + st_max
        return CStdIntType(t_max)
    if isinstance(t1, CBuiltinType) and isinstance(t2, CStdIntType):
        t2 = getBuiltinTypeForStdIntType(stateStruct, t2)
        return getCommonValueType(stateStruct, t1, t2)
    if isinstance(t1, CStdIntType) and isinstance(t2, CBuiltinType):
        t1 = getBuiltinTypeForStdIntType(stateStruct, t1)
        return getCommonValueType(stateStruct, t1, t2)
    # C's "usual arithmetic conversions" promote ``enum`` to its
    # underlying integer type before combining with another arithmetic
    # operand.  The standard leaves the exact underlying type
    # implementation-defined but compatible with char / signed int /
    # unsigned int; in practice (and on the ABIs we target) it is
    # ``int``.  Substitute ``int`` and recurse so e.g. ``Py_ssize_t *
    # (enum PyUnicode_Kind)`` resolves to ``long`` instead of asserting.
    if isinstance(t1, CEnum):
        return getCommonValueType(stateStruct, CBuiltinType(("int",)), t2)
    if isinstance(t2, CEnum):
        return getCommonValueType(stateStruct, t1, CBuiltinType(("int",)))
    # Not a basic type.
    assert isSameType(stateStruct, t1, t2), \
        "getCommonValueType: incompatible non-basic types: t1=%r t2=%r" % (t1, t2)
    return t1


def _integerPromote(t):
    """Apply C99 §6.3.1.1 "integer promotions" to a type.

    Types of rank lower than ``int`` (``char``, ``short``, ``_Bool``,
    enum, bit-fields whose type is one of those) are promoted to
    ``int`` if ``int`` can represent all values of the original type,
    otherwise to ``unsigned int``.  Larger ranks (``int``, ``long``,
    ``long long``, and their unsigned variants) are unchanged.  On
    the ABIs we target (LP64), ``int`` represents all values of
    ``signed char``, ``unsigned char``, ``signed short``, ``unsigned
    short`` and ``_Bool``, so the promotion is uniformly to ``int``.

    Returns ``t`` unchanged for non-arithmetic / non-integer types.
    """
    if isinstance(t, CEnum):
        return CBuiltinType(("int",))
    if isinstance(t, CBuiltinType):
        tup = t.builtinType
        # Anything that's already (un)signed int/long/long-long stays.
        if "long" in tup:
            return t
        if tup in (("int",), ("signed",), ("signed", "int"),
                   ("unsigned",), ("unsigned", "int")):
            return t
        # Smaller integer types -> int.
        if tup in (("char",), ("signed", "char"), ("unsigned", "char"),
                   ("short",), ("signed", "short"), ("short", "int"),
                   ("signed", "short", "int"),
                   ("unsigned", "short"), ("unsigned", "short", "int"),
                   ("_Bool",), ("bool",)):
            return CBuiltinType(("int",))
        # Floats / unknown integer shapes: leave alone.
        return t
    if isinstance(t, CStdIntType):
        # int8/16 -> int, others (int32/64, uint32/64, size_t, ...) stay.
        if t.name in ("int8_t", "uint8_t", "int16_t", "uint16_t",
                      "byte", "wchar_t"):
            return CBuiltinType(("int",))
        return t
    return t


def getStdIntTypeForCType(stateStruct, c_type):
    """
    Note: This is platform dependent!
    """
    for prefix in ("", "u"):
        for postfix in ("8", "16", "32", "64"):
            k = prefix + "int" + postfix + "_t"
            stdint_c_type = stateStruct.StdIntTypes[k]
            if stdint_c_type == c_type:
                return CStdIntType(k)
    assert False, "unknown type %r" % c_type

def getStdIntTypeForBuiltinType(stateStruct, t):
    """
    Note: This is platform dependent!
    """
    assert isinstance(t, CBuiltinType)
    c_type = stateStruct.CBuiltinTypes[t.builtinType]
    return getStdIntTypeForCType(stateStruct, c_type)

def getBuiltinTypeForCType(stateStruct, c_type):
    """
    Note: This is platform dependent!
    """
    if c_type.__name__.startswith("wrapCTypeClass_"):
        c_type = c_type.__base__
    IntTypes = (("char",), ("short",), ("int",),
                ("long",), ("long", "long"))
    OtherTypes = (("float",), ("double",), ("long", "double"),
                  ("void", "*"))
    for prefix in ((), ("unsigned",)):
        types = IntTypes
        if not prefix: types = types + OtherTypes
        for postfix in types:
            k = prefix + postfix
            builtin_c_type = stateStruct.CBuiltinTypes[k]
            if builtin_c_type == c_type:
                return CBuiltinType(k)
    assert False, "unknown type %r" % c_type

def getBuiltinTypeForStdIntType(stateStruct, t):
    """
    Note: This is platform dependent!
    """
    assert isinstance(t, CStdIntType)
    stdint_c_type = stateStruct.StdIntTypes[t.name]
    return getBuiltinTypeForCType(stateStruct, stdint_c_type)

def isIntType(t):
    while isinstance(t, CTypedef):
        t = t.type
    if isinstance(t, CBuiltinType):
        if "void" in t.builtinType: return False
        if "float" in t.builtinType or "double" in t.builtinType:
            return False
        return True
    if isinstance(t, CStdIntType):
        return True
    return False


class CSizeofSymbol: pass

class COffsetofSymbol: pass


class CCurlyArrayArgs(_CBaseWithOptBody):
    # args is a list of CStatement
    NameIsRelevant = False
    def asCCode(self, indent=""):
        return indent + "{" + ", ".join(map(asCCode, self.args)) + "}"


class CStatement(_CBaseWithOptBody):
    NameIsRelevant = False
    _leftexpr = None
    _middleexpr = None
    _rightexpr = None
    _op = None
    def __nonzero__(self): return bool(self._leftexpr) or bool(self._rightexpr)
    __bool__ = __nonzero__
    def __repr__(self):
        s = self.__class__.__name__
        #s += " " + repr(self._tokens) # debug
        if self._leftexpr is not None: s += " " + repr(self._leftexpr)
        if self._op == COp("?:"):
            s += " ? " + repr(self._middleexpr)
            s += " : " + repr(self._rightexpr)
        elif self._op is not None or self._rightexpr is not None:
            s += " "
            s += str(self._op)
            if self._rightexpr is not None:
                s += " "
                s += repr(self._rightexpr)
        if self.defPos is not None: s += " @: " + self.defPos
        return "<" + s + ">"
    __str__ = __repr__
    def _initStatement(self):
        self._state = 0
        self._tokens = []
    def __init__(self, **kwargs):
        self._initStatement()
        _CBaseWithOptBody.__init__(self, **kwargs)
    @classmethod
    def overtake(cls, obj):
        obj.__class__ = cls
        obj._initStatement()
    def _is_offsetof_field_arg(self):
        """Return True if this statement is the field-name (second) argument of an offsetof() call.

        When finalize is called on the second argument, the first argument has already been
        appended to p.args (the comma separator triggers finalize+append for the first arg
        before processing continues), so len(p.args) >= 1 identifies the second-or-later arg.
        """
        p = getattr(self, "parent", None)
        if not isinstance(p, CFuncCall):
            return False
        if not isinstance(getattr(p, "base", None), COffsetofSymbol):
            return False
        # The first arg has already been appended when we finalize the second arg
        return len(p.args) >= 1

    def _handlePushedErrorForUnknown(self, stateStruct):
        if isinstance(self._leftexpr, CUnknownType):
            s = getattr(self, "_pushedErrorForUnknown", False)
            if not s:
                if not self._is_offsetof_field_arg():
                    stateStruct.error("statement parsing: identifier %r unknown in state %i in handle pushed error" % (self._leftexpr.name, self._state))
                self._pushedErrorForUnknown = True
    def finalize(self, stateStruct, addToContent=None):
        self._handlePushedErrorForUnknown(stateStruct)
        # Normalise the parser's representation of a function-pointer
        # type-name.  C's grammar requires unbounded lookahead to tell
        # ``int (`` apart as the start of a call vs. a function-pointer
        # type-name ``int (*) (args)``.  Our pre-3 statement parser
        # commits to the call interpretation and -- because the
        # ``*`` between ``( )`` is a prefix-op with no operand --
        # ends up with the shape
        #
        #     CFuncCall(base=CFuncCall(base=T, args=[]),
        #               args=[CStatement(P1), ...])
        #
        # i.e. ``T()(P1, ...)``.  At the end of statement parsing,
        # rewrite this to a proper ``CFuncPointerDecl`` so downstream
        # code (the cast-detection in ``_cpre3_parse_brackets``, the
        # interpreter's type machinery, etc.) never sees the
        # ambiguous shape.
        if _is_funcptr_typename_misparse(self._leftexpr):
            self._leftexpr = _funcptr_typename_misparse_to_decl(self._leftexpr)
        _CBaseWithOptBody.finalize(self, stateStruct, addToContent)
    def _cpre3_handle_token(self, stateStruct, token):
        """
        :type stateStruct: State
        :type token: iterator
        """
        self._tokens += [token]

        if self._state == 5 and token == COp(":"):
            if self._leftexpr.name:
                CGotoLabel.overtake(self)
                self.name = self._leftexpr.name
                self._type_tokens[:] = []
            else:
                stateStruct.error("statement parsing: got ':' after " + repr(self._leftexpr) + "; looks like a goto-label but has no name")
            self.finalize(stateStruct)
            return

        self._handlePushedErrorForUnknown(stateStruct)
        obj = None
        if self._state == 0:
            if isinstance(token, (CIdentifier,CNumber,CStr,CChar)):
                if isinstance(token, CIdentifier):
                    if token.content == "struct":
                        self._state = 1
                        return
                    elif token.content == "union":
                        self._state = 2
                        return
                    elif token.content == "enum":
                        self._state = 3
                        return
                    elif token.content == "sizeof":
                        obj = CSizeofSymbol()
                    elif token.content == "offsetof":
                        obj = COffsetofSymbol()
                    elif token.content in stateStruct.Attribs:
                        self.attribs += [token.content]
                        return
                    elif (token.content,) in stateStruct.CBuiltinTypes:
                        obj = CBuiltinType((token.content,))
                    elif token.content in stateStruct.StdIntTypes:
                        obj = CStdIntType(token.content)
                    else:
                        obj = findObjInNamespace(stateStruct, self.parent, token.content)
                        if obj is None:
                            obj = CUnknownType(name=token.content)
                            self._pushedErrorForUnknown = False
                            # we print an error later. it still could be a goto-label.
                else:
                    obj = token
                self._leftexpr = obj
                self._state = 5
            elif isinstance(token, COp):
                # prefix op
                self._op = token
                self._rightexpr = CStatement(parent=self)
                self._state = 8
            else:
                stateStruct.error("statement parsing: didn't expected token " + str(token))
        elif self._state in (1,2,3): # struct,union,enum
            TName = {1:"struct", 2:"union", 3:"enum"}[self._state]
            DictName = TName + "s"
            if isinstance(token, CIdentifier):
                obj = findCObjTypeInNamespace(stateStruct, self.parent, DictName, token.content)
                if obj is None:
                    stateStruct.error("statement parsing: " + TName + " '" + token.content + "' unknown")
                    obj = CUnknownType(name=token.content)
                self._leftexpr = obj
                self._state = 5
            else:
                stateStruct.error("statement parsing: didn't expected token " + str(token) + " after " + TName)
        elif self._state == 5: # after expr
            if token == COp("."):
                if isinstance(self._leftexpr, CNumber):
                    self._state = 10
                else:
                    self._state = 20
                    self._leftexpr = CAttribAccessRef(parent=self, base=self._leftexpr)
            elif token == COp("->"):
                self._state = 20
                self._leftexpr = CPtrAccessRef(parent=self, base=self._leftexpr)
            elif isinstance(token, COp):
                if token == COp("*") and isType(self._leftexpr):
                    self._leftexpr = CPointerType(self._leftexpr)
                elif token.content in OpPostfixFuncs:
                    subStatement = CStatement(parent=self)
                    subStatement._leftexpr = self._leftexpr
                    subStatement._op = token
                    self._leftexpr = subStatement
                elif isinstance(self._leftexpr, (CSizeofSymbol, COffsetofSymbol)):
                    # ``sizeof EXPR`` (no parens) per C99 6.5.3.4: the
                    # operand is a unary expression.  Wrap into the
                    # same CFuncCall(base=CSizeofSymbol, args=[EXPR])
                    # shape that the parenthesized ``sizeof(EXPR)``
                    # form produces -- the bare-identifier path below
                    # already does this via ``_create_cast_call``; we
                    # extend it to also handle ``sizeof *p``,
                    # ``sizeof &x``, etc.  Routes via state 40 so
                    # subsequent tokens continue parsing the unary
                    # operand inside args[0].
                    self._leftexpr = _create_cast_call(stateStruct, self, self._leftexpr, token)
                    self._state = 40
                else:
                    self._op = token
                    self._state = 6
            elif isinstance(self._leftexpr, CStr) and isinstance(token, CStr):
                self._leftexpr = CStr(self._leftexpr.content + token.content)
            else:
                if isinstance(self._leftexpr, CBuiltinType) and self._leftexpr.builtinType + (token.content,) in stateStruct.CBuiltinTypes:
                    self._leftexpr = CBuiltinType(self._leftexpr.builtinType + (token.content,))
                    # stay in same state
                else:
                    self._leftexpr = _create_cast_call(stateStruct, self, self._leftexpr, token)
                    self._state = 40
        elif self._state == 6: # after expr + op
            if isinstance(token, CIdentifier):
                if token.content == "sizeof":
                    obj = CSizeofSymbol()
                elif token.content == "offsetof":
                    obj = COffsetofSymbol()
                else:
                    obj = findObjInNamespace(stateStruct, self.parent, token.content)
                    if obj is None:
                        stateStruct.error("statement parsing: identifier %r unknown in state %i" % (token.content, self._state))
                        obj = CUnknownType(name=token.content)
                self._state = 7
            elif isinstance(token, (CNumber,CStr,CChar)):
                obj = token
                self._state = 7
            else:
                obj = CStatement(parent=self)
                obj._cpre3_handle_token(stateStruct, token) # maybe a postfix op or whatever
                self._state = 8
            self._rightexpr = obj
        elif self._state == 7: # after expr + op + expr
            if token == COp("."):
                if isinstance(self._rightexpr, CNumber):
                    self._state = 11
                else:
                    self._state = 22
                    self._rightexpr = CAttribAccessRef(parent=self, base=self._rightexpr)
            elif token == COp("->"):
                self._state = 22
                self._rightexpr = CPtrAccessRef(parent=self, base=self._rightexpr)
            elif isinstance(token, COp) and token.content in OpPostfixFuncs:
                # Postfix ++/-- on the right-hand expression, e.g. a + b++ or a = a++.
                # Mirror the analogous handling in state 5 for the left-hand expression.
                subStatement = CStatement(parent=self)
                subStatement._leftexpr = self._rightexpr
                subStatement._op = token
                self._rightexpr = subStatement
                # Stay in state 7 so the next token continues the outer expression.
            elif isinstance(token, COp):
                if token == COp(":"):
                    if self._op != COp("?"):
                        stateStruct.error("internal error: got ':' after " + repr(self) + " with " + repr(self._op))
                        # TODO: any better way to fix/recover? right now, we just assume '?' anyway
                    self._middleexpr = self._rightexpr
                    self._rightexpr = None
                    self._op = COp("?:")
                    self._state = 6
                elif opsDoLeftToRight(stateStruct, self._op.content, token.content, prefix1=self._leftexpr is None):
                    import copy
                    subStatement = copy.copy(self)
                    self._leftexpr = subStatement
                    self._rightexpr = None
                    self._op = token
                    self._state = 6
                else:
                    self._rightexpr = CStatement(parent=self, _leftexpr=self._rightexpr, _state=6)
                    self._rightexpr._op = token
                    self._state = 8
            elif isinstance(self._rightexpr, CStr) and isinstance(token, CStr):
                self._rightexpr = CStr(self._rightexpr.content + token.content)
            else:
                self._rightexpr = _create_cast_call(stateStruct, self, self._rightexpr, token)
                self._state = 45
        elif self._state == 8: # right-to-left chain, pull down
            assert isinstance(self._rightexpr, CStatement)
            self._rightexpr._cpre3_handle_token(stateStruct, token)
            if self._rightexpr._state in (5,7,9, 50, 51):
                self._state = 9
        elif self._state == 9: # right-to-left chain after op + expr
            assert isinstance(self._rightexpr, CStatement)
            if token in (COp("."),COp("->")):
                self._rightexpr._cpre3_handle_token(stateStruct, token)
                self._state = 8
            elif not isinstance(token, COp):
                self._rightexpr._cpre3_handle_token(stateStruct, token)
            else: # is COp
                if token.content == ":":
                    if self._op == COp("?"):
                        self._middleexpr = self._rightexpr
                        self._rightexpr = None
                        self._op = COp("?:")
                        self._state = 6
                    else:
                        self._rightexpr._cpre3_handle_token(stateStruct, token)
                        self._state = 8
                elif opsDoLeftToRight(stateStruct, self._op.content, token.content, prefix1=self._leftexpr is None):
                    import copy
                    subStatement = copy.copy(self)
                    self._leftexpr = subStatement
                    self._rightexpr = None
                    self._op = token
                    self._state = 6
                else:
                    self._rightexpr._cpre3_handle_token(stateStruct, token)
                    # Mirror the state-8 transition logic: once
                    # the inner expression is back in a "complete value" state
                    # (5/7/9/...), the outer wrapper must move to state 9 so
                    # subsequent operator tokens get the precedence check
                    # against our prefix op.  Without this, e.g. `*p++ & 128`
                    # would stay in state 8 after `++` and route `&` straight
                    # into the inner statement -- producing `*((p++) & 128)`
                    # instead of `(*p++) & 128`.
                    if self._rightexpr._state in (5, 7, 9, 50, 51):
                        self._state = 9
                    else:
                        self._state = 8
        elif self._state == 10: # after number + "."
            if isinstance(token, CNumber):
                # Reassemble the float from the original lexemes, not from the
                # parsed values: the tokenizer splits `0.0e0` into 3 tokens
                # [0, ., 0e0] and the right side may already be a float (with
                # exponent), so str(content) would give us "0.0.0" and choke.
                # Using rawstr ("0" + "0e0" -> "0.0e0") handles both plain
                # `3.14` and scientific cases like `0.0e0`, `1.5e-3`.
                self._leftexpr = CNumber(*_combine_float_parts(self._leftexpr, token))
                self._state = 5
            else:
                # Trailing-dot float literal: `0.` is a valid C float (== 0.0)
                # with no fractional digits.  Promote the integer leftexpr to
                # a float CNumber, then re-process the current token from
                # state 5 (after expr) so it's handled as the next operator
                # / suffix.
                self._leftexpr = CNumber(*_combine_float_parts(
                    self._leftexpr, CNumber(0, "")))
                self._state = 5
                self._cpre3_handle_token(stateStruct, token)
        elif self._state == 11: # after expr + op + number + "."
            if isinstance(token, CNumber):
                self._rightexpr = CNumber(*_combine_float_parts(self._rightexpr, token))
                self._state = 7
            else:
                # Trailing-dot float on the right side, same as state 10.
                self._rightexpr = CNumber(*_combine_float_parts(
                    self._rightexpr, CNumber(0, "")))
                self._state = 7
                self._cpre3_handle_token(stateStruct, token)
        elif self._state == 20: # after attrib/ptr access
            if isinstance(token, CIdentifier):
                assert isinstance(self._leftexpr, (CAttribAccessRef,CPtrAccessRef))
                self._leftexpr.name = token.content
                self._state = 5
            else:
                stateStruct.error("statement parsing: didn't expected token " + str(token) + " after " + str(self._leftexpr) + " in state " + str(self._state))
        elif self._state == 22: # after expr + op + expr with attrib/ptr access
            if isinstance(token, CIdentifier):
                assert isinstance(self._rightexpr, (CAttribAccessRef,CPtrAccessRef))
                self._rightexpr.name = token.content
                self._state = 7
            else:
                stateStruct.error("statement parsing: didn't expected token " + str(token) + " after " + str(self._leftexpr) + " in state " + str(self._state))
        elif self._state == 40: # after cast_call((expr) x)
            # The argument's expression is "complete" in any of the
            # value-state codes (5/7/9/50/51); state 5 alone misses the
            # state-9 case for unary-prefix expressions (e.g. ``sizeof
            # *fb`` leaves args[0] in state 9 after the operand).
            if self._leftexpr.args[0]._state not in (5, 7, 9, 50, 51):
                self._leftexpr.args[0]._cpre3_handle_token(stateStruct, token)
            elif token in (COp("."), COp("->"), COp("++"), COp("--")):
                # Postfix operators (`.`, `->`, `++`, `--`) bind to the
                # inner expression, not to the cast result.  Per the C
                # grammar `cast-expression : ( type-name ) cast-expression`
                # the postfix ops are part of the cast's operand, so
                # `(T) *p->ptr++` is `(T)(*((p->ptr)++))`, NOT
                # `((T)(*p->ptr))++`.  This affects marshal's
                # `(unsigned char) *p->ptr++` byte-reader.
                self._leftexpr.args[0]._cpre3_handle_token(stateStruct, token)
            else:
                self._leftexpr.args[0].finalize(stateStruct)
                self._state = 5
                self._cpre3_handle_token(stateStruct, token) # redo handling
        elif self._state == 45: # after expr + op + cast_call((expr) x)
            if self._rightexpr.args[0]._state not in (5, 7, 9, 50, 51):
                self._rightexpr.args[0]._cpre3_handle_token(stateStruct, token)
            elif token in (COp("."), COp("->"), COp("++"), COp("--")):
                self._rightexpr.args[0]._cpre3_handle_token(stateStruct, token)
            else:
                self._rightexpr.args[0].finalize(stateStruct)
                self._state = 7
                self._cpre3_handle_token(stateStruct, token) # redo handling
        elif self._state in (50,51): # [expr + op + ] (expr)-cast
            if self._state == 50: funcCall = self._leftexpr
            else: funcCall = self._rightexpr
            assert isinstance(funcCall, CFuncCall)
            if not funcCall.args:
                funcCall.args = [CStatement(parent=funcCall)]
            assert len(funcCall.args) == 1
            subStatement = funcCall.args[0]
            # Postfix `.`/`->`/`++`/`--` bind to the cast operand (per the C
            # grammar `cast-expression : ( type-name ) cast-expression`).
            # Without these, `(unsigned char) *p->ptr++` is mis-parsed as
            # `((unsigned char) *p->ptr) ++` and `++` becomes a no-op on
            # the cast result -- breaking marshal's byte-stream reader.
            if subStatement._state != 0 and isinstance(token, COp) and token not in (
                    COp("."), COp("->"), COp("++"), COp("--")):
                subStatement.finalize(stateStruct, addToContent=False)
                if self._state == 50: self._state = 5
                else: self._state = 7
                self._cpre3_handle_token(stateStruct, token)
            else:
                subStatement._cpre3_handle_token(stateStruct, token)
        else:
            stateStruct.error("internal error: statement parsing: token " + str(token) + " in invalid state " + str(self._state))

    def _cpre3_parse_brackets(self, stateStruct, openingBracketToken, input_iter):
        self._handlePushedErrorForUnknown(stateStruct)

        if self._state == 0 and openingBracketToken.content == "{": # array args or struct args
            arrayArgs = CCurlyArrayArgs(parent=self)
            self._leftexpr = arrayArgs
            arrayArgs._bracketlevel = list(openingBracketToken.brackets)
            cpre3_parse_statements_in_brackets(stateStruct, arrayArgs, COp(","), arrayArgs.args, input_iter)
            arrayArgs.finalize(stateStruct)
            self._state = 5
            return

        if self._state in (50,51):  # after [expr + op +] (expr)-cast
            if self._state == 50:
                funcCall = self._leftexpr
            else:
                funcCall = self._rightexpr
            assert isinstance(funcCall, CFuncCall)
            if funcCall.args:
                assert len(funcCall.args) == 1
                assert isinstance(funcCall.args[0], CStatement)
                funcCall.args[0]._cpre3_parse_brackets(stateStruct, openingBracketToken, input_iter)
            else:
                funcCall._bracketlevel = list(openingBracketToken.brackets)
                subStatement = CStatement(parent=funcCall)
                funcCall.args += [subStatement]
                subStatement._cpre3_parse_brackets(stateStruct, openingBracketToken, input_iter)
                if subStatement._state == 50: return  # another cast follows
                funcCall.finalize(stateStruct)
                # Do not directly go to state 5/7. Maybe a "->" follows.
            return

        if self._state in (5,7): # after expr or expr + op + expr
            if self._state == 5:
                ref = self._leftexpr
            else:
                ref = self._rightexpr
            if openingBracketToken.content == "(":
                funcCall = CFuncCall(parent=self)
            elif openingBracketToken.content == "[":
                funcCall = CArrayIndexRef(parent=self)
            else:
                stateStruct.error("cpre3 statement parse brackets after expr: didn't expected opening bracket '" + openingBracketToken.content + "'")
                # fallback. handle just like '('
                funcCall = CStatement(parent=self.parent)
            if self._state == 5:
                self._leftexpr = funcCall
            else:
                self._rightexpr = funcCall
            funcCall.base = ref
            funcCall._bracketlevel = list(openingBracketToken.brackets)
            cpre3_parse_statements_in_brackets(stateStruct, funcCall, COp(","), funcCall.args, input_iter)
            funcCall.finalize(stateStruct)
            return

        if self._state in (8,9): # right-to-left chain
            self._rightexpr._cpre3_parse_brackets(stateStruct, openingBracketToken, input_iter)
            if self._rightexpr._state in (5,7,9, 50, 51):
                self._state = 9
            return

        if self._state in (40,45): # after .. cast_call + expr
            if self._state == 40:
                ref = self._leftexpr
            else:
                ref = self._rightexpr
            assert isinstance(ref, CFuncCall)
            assert len(ref.args) == 1
            ref.args[0]._cpre3_parse_brackets(stateStruct, openingBracketToken, input_iter)
            return

        if openingBracketToken.content == "(":
            subStatement = CStatement(parent=self.parent)
        elif openingBracketToken.content == "[":
            subStatement = CArrayStatement(parent=self.parent)
        else:
            # fallback. handle just like '('. we error this below
            subStatement = CStatement(parent=self.parent)

        if self._state == 0:
            self._leftexpr = subStatement
            self._state = 5
        elif self._state == 6: # expr + op
            self._rightexpr = subStatement
            self._state = 7
        else:
            stateStruct.error("cpre3 statement parse brackets: didn't expected opening bracket '" + openingBracketToken.content + "' in state " + str(self._state))

        finalized = False
        for token in input_iter:
            if isinstance(token, COpeningBracket):
                subStatement._cpre3_parse_brackets(stateStruct, token, input_iter)
            elif isinstance(token, CClosingBracket):
                if token.brackets == openingBracketToken.brackets:
                    subStatement.finalize(stateStruct, addToContent=False)
                    self._tokens += [subStatement]
                    finalized = True
                    break
                else:
                    stateStruct.error("cpre3 statement parse brackets: internal error, closing brackets " + str(token.brackets) + " not expected")
            else:
                subStatement._cpre3_handle_token(stateStruct, token)
        if not finalized:
            stateStruct.error("cpre3 statement parse brackets: incomplete, missing closing bracket '" + openingBracketToken.content + "' at level " + str(openingBracketToken.brackets))
            return
        if openingBracketToken.content == "(" and subStatement.isCType():
            # This is a C-style-cast.
            funcCall = CFuncCall(parent=self)
            funcCall.base = subStatement.asType()
            if self._state == 5:
                self._leftexpr = funcCall
                self._state = 50
            elif self._state == 7:
                self._rightexpr = funcCall
                self._state = 51
            else:
                assert False, self._state

    def getConstValue(self, stateStruct):
        if not self: return None
        if self._leftexpr is None: # prefixed only
            func = OpPrefixFuncs[self._op.content]
            v = getConstValue(stateStruct, self._rightexpr)
            if v is None: return None
            return func(v)
        v1 = getConstValue(stateStruct, self._leftexpr)
        if v1 is None: return None
        if self._op is None or self._rightexpr is None:
            return v1
        v2 = getConstValue(stateStruct, self._rightexpr)
        if v2 is None: return None
        if self._op == COp("?:"):
            assert self._middleexpr is not None
            v15 = getConstValue(stateStruct, self._middleexpr)
            if v15 is None: return None
            return v15 if v1 else v2
        assert self._middleexpr is None
        func = OpBinFuncs[self._op.content]
        return func(v1, v2)

    def getValueType(self, stateStruct):
        if self._leftexpr is None: # prefixed only
            v = getValueType(stateStruct, self._rightexpr)
            assert v
            if self._op.content == "&":
                return CPointerType(v)
            elif self._op.content == "!":  # not-op
                return CBuiltinType(("char",))  # 0 or 1, not sure
            elif self._op.content == "*":
                if isinstance(v, CPointerType):
                    return v.pointerOf
                elif isinstance(v, CArrayType):
                    return v.arrayOf
                else:
                    assert False, "invalid pointer deref type %r" % v
            elif self._op.content in ("+","-","++","--","~"):  # OpPrefixFuncs
                return v
            else:
                assert False, "invalid prefix op %r" % self._op
        v1 = getValueType(stateStruct, self._leftexpr)
        assert v1
        if self._op is None or self._rightexpr is None:
            return v1
        v2 = getValueType(stateStruct, self._rightexpr)
        assert v2
        if self._op == COp("?:"):
            assert self._middleexpr is not None
            v15 = getValueType(stateStruct, self._middleexpr)
            if v15 is None: return None
            return getCommonValueType(stateStruct, v15, v2)
        assert self._middleexpr is None
        # see OpBinFuncs
        if self._op.content == ",":
            return v2
        elif self._op.content in ("==","!=","<","<=",">",">="):
            return CBuiltinType(("char",))  # 0 or 1, not sure
        elif self._op.content in ("&&","||"):
            return CBuiltinType(("char",))  # 0 or 1, not sure
        elif self._op.content in ("<<",">>"):
            # C99 §6.5.7: integer promotions are performed on each
            # operand; the result has the type of the *promoted* left
            # operand.  Without the promotion, ``(short)1 << 15`` (the
            # ``PyLong_MARSHAL_BASE`` macro in Python/marshal.c) would
            # wrap the result back to ``c_short`` and truncate 32768 to
            # -32768, breaking ``r_PyLong``'s digit-range check.
            return _integerPromote(v1)
        elif self._op.content in ("<<=", ">>="):
            # Compound assignment: result type is the (un-promoted)
            # type of the lvalue; the promotion happens for the
            # arithmetic only.  Keep v1.
            return v1
        elif self._op.content in ("=","*=","-=","+=","/=","%=","&=","^=","|="):  # assign
            return v1
        elif self._op.content in ("+","-","*","/","&","^","|","%"):
            # C special case: `ptr - ptr` yields ptrdiff_t, NOT the pointer type.
            if self._op.content == "-" and isPointerType(v1) and isPointerType(v2):
                return CStdIntType("ptrdiff_t")
            return getCommonValueType(stateStruct, v1, v2)
        else:
            assert False, "invalid bin op %r" % self._op

    def isCType(self):
        if self._leftexpr is None: return False # all prefixed stuff is not a type
        if self._rightexpr is not None: return False # same thing, prefixed stuff is not a type
        return isType(self._leftexpr)

    def asType(self):
        assert self._leftexpr is not None
        assert self._rightexpr is None
        if isinstance(self._leftexpr, CStatement):
            t = self._leftexpr.asType()
        else:
            t = self._leftexpr
        if self._op is not None:
            if self._op.content in ("*","&"):
                t = CPointerType(t)
            else:
                raise Exception("postfix op " + str(self._op) + " unknown for pointer type " + str(self._leftexpr))
        return t

    def getCType(self, stateStruct):
        return getCType(self.asType(), stateStruct)

    def asCCode(self, indent=""):
        if self._leftexpr is None: # prefixed only
            return indent + "(" + self._op.content + asCCode(self._rightexpr) + ")"
        if self._op is None or self._rightexpr is None:
            return indent + asCCode(self._leftexpr) # no brackets. we do them outside
        if self._op == COp("?:"):
            return indent + "(" + asCCode(self._leftexpr) + " ? " + asCCode(self._middleexpr) + " : " + asCCode(self._rightexpr) + ")"
        return indent + "(" + asCCode(self._leftexpr) + " " + self._op.content + " " + asCCode(self._rightexpr) + ")"

# only real difference is that this is inside of '[]'
class CArrayStatement(CStatement):
    def asCCode(self, indent=""):
        return indent + "[" + CStatement.asCCode(self) + "]"

def cpre3_parse_struct(stateStruct, curCObj, input_iter):
    curCObj.body = CBody(parent=curCObj.parent.body)
    cpre3_parse_body(stateStruct, curCObj, input_iter)
    curCObj.finalize(stateStruct)

def cpre3_parse_union(stateStruct, curCObj, input_iter):
    curCObj.body = CBody(parent=curCObj.parent.body)
    cpre3_parse_body(stateStruct, curCObj, input_iter)
    curCObj.finalize(stateStruct)

def cpre3_parse_funcbody(stateStruct, curCObj, input_iter):
    curCObj.body = CBody(parent=curCObj.parent.body)
    cpre3_parse_body(stateStruct, curCObj, input_iter)
    curCObj.finalize(stateStruct)

def cpre3_parse_funcpointername(stateStruct, curCObj, input_iter):
    bracketLevel = list(curCObj._bracketlevel)
    state = 0
    for token in input_iter:
        if isinstance(token, CClosingBracket):
            if token.brackets == bracketLevel:
                return
            if not _isBracketLevelOk(bracketLevel, token.brackets):
                stateStruct.error("cpre3 parse func pointer name: internal error: bracket level messed up with closing bracket: " + str(token.brackets))

        if state == 0:
            if token == COp("*"):
                state = 1
                CFuncPointerDecl.overtake(curCObj)
                curCObj.ptrLevel = 1
            elif isinstance(token, CIdentifier):
                CFunc.overtake(curCObj)
                curCObj.name = token.content
                state = 4
            else:
                stateStruct.error("cpre3 parse func pointer name: token " + str(token) + " not expected; expected '*'")
        elif state == 1:
            if token == COp("*"):
                curCObj.ptrLevel += 1
            elif isinstance(token, CIdentifier):
                if token.content in stateStruct.Attribs:
                    curCObj.attribs += [token.content]
                else:
                    curCObj.name = token.content
                    state = 2
            else:
                stateStruct.error("cpre3 parse func pointer name: token " + str(token) + " not expected; expected identifier")
        elif state == 2: # after identifier in func ptr
            if token == COpeningBracket("["):
                arrayBaseObj = curCObj.parent
                arrayBaseObj._bracketlevel = list(token.brackets)
                cpre3_parse_arrayargs(stateStruct, arrayBaseObj, input_iter)
                arrayBaseObj._bracketlevel = bracketLevel
            else:
                state = 3
        elif state == 4: # after identifier in func
            # we don't expect anything anymore
            state = 3

        if state == 3:
            stateStruct.error("cpre3 parse func pointer name: token " + str(token) + " not expected; expected ')'")

    stateStruct.error("cpre3 parse func pointer name: incomplete, missing ')' on level " + str(curCObj._bracketlevel))

def cpre3_parse_enum(stateStruct, parentCObj, input_iter):
    parentCObj.body = CEnumBody(parent=parentCObj.parent.body)
    curCObj = CEnumConst(parent=parentCObj)
    valueStmnt = None
    state = 0

    for token in input_iter:
        if isinstance(token, CIdentifier):
            if state == 0:
                curCObj.name = token.content
                state = 1
            elif state == 2:
                valueStmnt._cpre3_handle_token(stateStruct, token)
            else:
                stateStruct.error(
                    "cpre3 parse enum: unexpected identifier %s after %s in state %s" % (
                        token.content, curCObj, state))
        elif token == COp("="):
            if state == 1:
                valueStmnt = CStatement(parent=parentCObj)
                state = 2
            else:
                stateStruct.error("cpre3 parse enum: unexpected op '=' after " + str(curCObj) + " in state " + str(state))
        elif token == COp(","):
            if state in (1,2):
                if state == 2:
                    valueStmnt.finalize(stateStruct, addToContent=False)
                    curCObj.value = valueStmnt.getConstValue(stateStruct)
                curCObj.finalize(stateStruct)
                curCObj = CEnumConst(parent=parentCObj)
                valueStmnt = None
                state = 0
            else:
                stateStruct.error("cpre3 parse enum: unexpected op ',' after " + str(curCObj) + " in state " + str(state))
        elif isinstance(token, CClosingBracket):
            if token.brackets == parentCObj._bracketlevel:
                if curCObj:
                    if state == 2:
                        valueStmnt.finalize(stateStruct, addToContent=False)
                        curCObj.value = valueStmnt.getConstValue(stateStruct)
                    curCObj.finalize(stateStruct)
                parentCObj.finalize(stateStruct)
                return
            if not _isBracketLevelOk(parentCObj._bracketlevel, token.brackets):
                stateStruct.error("cpre3 parse enum: internal error: bracket level messed up with closing bracket: " + str(token.brackets))
        elif state == 2:
            if isinstance(token, COpeningBracket):
                valueStmnt._cpre3_parse_brackets(stateStruct, token, input_iter)
            else:
                valueStmnt._cpre3_handle_token(stateStruct, token)
        else:
            stateStruct.error("cpre3 parse enum: unexpected token " + str(token) + " in state " + str(state))
    stateStruct.error("cpre3 parse enum: incomplete, missing '}' on level " + str(parentCObj._bracketlevel))

def _cpre3_parse_skipbracketcontent(stateStruct, bracketlevel, input_iter):
    for token in input_iter:
        if isinstance(token, CClosingBracket):
            if token.brackets == bracketlevel:
                return
            if not _isBracketLevelOk(bracketlevel, token.brackets):
                stateStruct.error("cpre3 parse skip brackets: internal error: bracket level messed up with closing bracket: " + str(token.brackets))
    stateStruct.error("cpre3 parse: incomplete, missing closing bracket on level " + str(bracketlevel))

def cpre3_parse_funcargs(stateStruct, parentCObj, input_iter):
    curCObj = CFuncArgDecl(parent=parentCObj)
    typeObj = None
    for token in input_iter:
        if isinstance(token, CIdentifier):
            if token.content == "typedef":
                stateStruct.error("cpre3 parse func args: typedef not expected")
            elif token.content in stateStruct.Attribs:
                curCObj.attribs += [token.content]
            elif token.content == "struct":
                typeObj = CStruct()
                curCObj._type_tokens += [typeObj]
            elif token.content == "union":
                typeObj = CUnion()
                curCObj._type_tokens += [typeObj]
            elif token.content == "enum":
                typeObj = CEnum()
                curCObj._type_tokens += [typeObj]
            elif typeObj is not None:
                if typeObj.name is None:
                    typeObj.name = token.content
                    typeObj = None
            elif (token.content,) in stateStruct.CBuiltinTypes:
                curCObj._type_tokens += [token.content]
            elif token.content in stateStruct.StdIntTypes:
                curCObj._type_tokens += [token.content]
            elif len(curCObj._type_tokens) == 0:
                curCObj._type_tokens += [token.content]
            else:
                if curCObj.name is None:
                    curCObj.name = token.content
                else:
                    stateStruct.error("cpre3 parse func args: second identifier name " + token.content + " for " + str(curCObj))
        elif isinstance(token, COp):
            if token.content == ",":
                curCObj.finalize(stateStruct)
                curCObj = CFuncArgDecl(parent=parentCObj)
                typeObj = None
            else:
                curCObj._type_tokens += [token.content]
        elif isinstance(token, COpeningBracket):
            curCObj._bracketlevel = list(token.brackets)
            if token.content == "(":
                if len(curCObj._type_tokens) == 1 and isinstance(curCObj._type_tokens[0], CFuncPointerDecl):
                    typeObj = curCObj._type_tokens[0]
                    cpre3_parse_funcargs(stateStruct, typeObj, input_iter)
                    typeObj.finalize(stateStruct)
                elif curCObj.name is None:
                    typeObj = CFuncPointerDecl(parent=curCObj.parent)
                    typeObj._bracketlevel = curCObj._bracketlevel
                    typeObj._type_tokens[:] = curCObj._type_tokens
                    curCObj._type_tokens[:] = [typeObj]
                    cpre3_parse_funcpointername(stateStruct, typeObj, input_iter)
                    curCObj.name = typeObj.name
                else:
                    # K&R-style function-typed parameter:
                    #   ``int get_char(struct tok_state *)``
                    # is equivalent to
                    #   ``int (*get_char)(struct tok_state *)``
                    # (C standard 6.7.6.3p8: a function-type parameter is
                    # adjusted to the corresponding pointer-to-function
                    # type).  Convert this in-place to a function pointer
                    # decl, preserving the name.
                    typeObj = CFuncPointerDecl(parent=curCObj.parent)
                    typeObj._bracketlevel = curCObj._bracketlevel
                    typeObj._type_tokens[:] = curCObj._type_tokens
                    typeObj.name = curCObj.name
                    curCObj._type_tokens[:] = [typeObj]
                    cpre3_parse_funcargs(stateStruct, typeObj, input_iter)
                    typeObj.finalize(stateStruct)
            elif token.content == "[":
                cpre3_parse_arrayargs(stateStruct, curCObj, input_iter)
            else:
                stateStruct.error("cpre3 parse func args: unexpected opening bracket '" + token.content + "'")
                _cpre3_parse_skipbracketcontent(stateStruct, curCObj._bracketlevel, input_iter)
        elif isinstance(token, CClosingBracket):
            if token.brackets == parentCObj._bracketlevel:
                if curCObj:
                    curCObj.finalize(stateStruct)
                return
            if not _isBracketLevelOk(parentCObj._bracketlevel, token.brackets):
                stateStruct.error("cpre3 parse func args: internal error: bracket level messed up with closing bracket: " + str(token.brackets))
            # no error. we already errored on the opening bracket. and the cpre2 parsing ensures the rest
        else:
            stateStruct.error("cpre3 parse func args: unexpected token " + str(token))

    stateStruct.error("cpre3 parse func args: incomplete, missing ')' on level " + str(parentCObj._bracketlevel))

def cpre3_parse_arrayargs(stateStruct, curCObj, input_iter):
    # `parent=curCObj` (the surrounding CVarDecl / CFuncArgDecl /
    # CFuncPointerDecl) is required so that identifiers inside the
    # array-bound expression -- e.g. ``Py_off_t`` inside
    # ``sizeof(Py_off_t)`` reached via a #define macro expansion --
    # can be resolved against the enclosing scope's typedefs.
    # Without it, ``findObjInNamespace`` walks an orphan parent chain
    # that never reaches the State and the typedef lookup silently
    # fails.
    valueStmnt = CStatement(parent=curCObj)
    valueStmnt._bracketlevel = curCObj._bracketlevel
    valueStmnt._cpre3_parse_brackets(stateStruct, COpeningBracket("[", brackets=curCObj._bracketlevel), input_iter)
    assert isinstance(valueStmnt._leftexpr, CArrayStatement)
    if isinstance(curCObj, (CVarDecl, CFuncArgDecl, CFuncPointerDecl)):
        arrayType = make_type_from_typetokens(stateStruct, curCObj, curCObj._type_tokens)
        arrayLen = valueStmnt._leftexpr
        curCObj.type = CArrayType(arrayOf=arrayType, arrayLen=arrayLen)
    else:
        stateStruct.error("cpre3_parse_arrayargs: unexpected: %r" % curCObj)

def cpre3_parse_typedef(stateStruct, curCObj, input_iter):
    state = 0
    typeObj = None

    for token in input_iter:
        if state == 0:
            if isinstance(token, CIdentifier):
                if token.content == "typedef":
                    stateStruct.error("cpre3 parse typedef: typedef not expected twice")
                elif token.content in stateStruct.Attribs:
                    curCObj.attribs += [token.content]
                elif token.content == "struct":
                    typeObj = CStruct(parent=curCObj.parent)
                    curCObj._type_tokens += [typeObj]
                elif token.content == "union":
                    typeObj = CUnion(parent=curCObj.parent)
                    curCObj._type_tokens += [typeObj]
                elif token.content == "enum":
                    typeObj = CEnum(parent=curCObj.parent)
                    curCObj._type_tokens += [typeObj]
                elif (token.content,) in stateStruct.CBuiltinTypes:
                    curCObj._type_tokens += [token.content]
                elif token.content in stateStruct.StdIntTypes:
                    curCObj._type_tokens += [token.content]
                elif token.content in stateStruct.typedefs:
                    if curCObj._type_tokens and curCObj.name is None:
                        curCObj.name = token.content
                    else:
                        curCObj._type_tokens += [token.content]
                else:
                    if typeObj is not None and not typeObj._finalized and typeObj.name is None:
                        typeObj.name = token.content
                    elif curCObj._type_tokens:
                        if curCObj.name is None:
                            curCObj.name = token.content
                        else:
                            stateStruct.error("cpre3 parse in typedef: got second identifier " + token.content + " after name " + curCObj.name)
                    else:
                        stateStruct.error("cpre3 parse in typedef: got unexpected identifier " + token.content)
            elif token == COp("*"):
                curCObj._type_tokens += ["*"]
            elif isinstance(token, COpeningBracket):
                curCObj._bracketlevel = list(token.brackets)
                if token.content == "(":
                    if len(curCObj._type_tokens) == 0 or not isinstance(curCObj._type_tokens[0], CFuncPointerDecl):
                        typeObj = CFuncPointerDecl(parent=curCObj.parent)
                        typeObj._bracketlevel = curCObj._bracketlevel
                        typeObj._type_tokens[:] = curCObj._type_tokens
                        curCObj._type_tokens[:] = [typeObj]
                        if curCObj.name is None: # eg.: typedef int (*Function)();
                            cpre3_parse_funcpointername(stateStruct, typeObj, input_iter)
                            curCObj.name = typeObj.name
                        else: # eg.: typedef int Function();
                            CFunc.overtake(typeObj)
                            typeObj.name = curCObj.name
                            cpre3_parse_funcargs(stateStruct, typeObj, input_iter)
                    else:
                        cpre3_parse_funcargs(stateStruct, typeObj, input_iter)
                elif token.content == "[":
                    cpre3_parse_arrayargs(stateStruct, curCObj, input_iter)
                elif token.content == "{":
                    if typeObj is not None: # it must not be None. but error handling already below
                        typeObj._bracketlevel = curCObj._bracketlevel
                    if isinstance(typeObj, CStruct):
                        cpre3_parse_struct(stateStruct, typeObj, input_iter)
                    elif isinstance(typeObj, CUnion):
                        cpre3_parse_union(stateStruct, typeObj, input_iter)
                    elif isinstance(typeObj, CEnum):
                        cpre3_parse_enum(stateStruct, typeObj, input_iter)
                    else:
                        stateStruct.error("cpre3 parse in typedef: got unexpected '{' after type " + str(typeObj))
                        state = 11
                else:
                    stateStruct.error("cpre3 parse in typedef: got unexpected opening bracket '" + token.content + "' after type " + str(typeObj))
                    state = 11
            elif isinstance(token, CSemicolon):
                if typeObj is not None and not typeObj._finalized:
                    typeObj.finalize(stateStruct, addToContent = typeObj.body is not None)
                curCObj.finalize(stateStruct)
                return
            else:
                stateStruct.error("cpre3 parse typedef: got unexpected token " + str(token))
        elif state == 11: # unexpected bracket
            # just ignore everything until we get the closing bracket
            if isinstance(token, CClosingBracket):
                if token.brackets == curCObj._bracketlevel:
                    state = 0
                if not _isBracketLevelOk(curCObj._bracketlevel, token.brackets):
                    stateStruct.error("cpre3 parse typedef: internal error: bracket level messed up with closing bracket: " + str(token.brackets))
        else:
            stateStruct.error("cpre3 parse typedef: internal error. unexpected state " + str(state))
    stateStruct.error("cpre3 parse typedef: incomplete, missing ';'")


class CCodeBlock(_CBaseWithOptBody):
    NameIsRelevant = False
    def asCCode(self, indent=""):
        return asCCode(self.body, indent)
class CGotoLabel(_CBaseWithOptBody):
    def asCCode(self, indent=""):
        return indent + self.name + ":"

def _getLastCBody(base):
    last = None
    while True:
        if isinstance(base.body, CBody):
            if not base.body.contentlist: break
            last = base.body.contentlist[-1]
        elif isinstance(base.body, CControlStructureBase):
            last = base.body
        else:
            break
        if not isinstance(last, CControlStructureBase): break
        if isinstance(last, CIfStatement):
            if last.elsePart is not None:
                base = last.elsePart
            else:
                base = last
        elif isinstance(last, (CForStatement,CWhileStatement)):
            base = last
        else:
            break
    return last

class CControlStructureBase(_CBaseWithOptBody):
    NameIsRelevant = False
    StrOutAttribList = [
        ("args", bool, None, str),
            ("body", None, None, lambda x: "<...>"),
            ("defPos", None, "@", str),
    ]
    def asCCode(self, indent=""):
        s = indent + self.Keyword
        if self.args: s += "(" + "; ".join(map(asCCode, self.args)) + ")"
        if self.body: s += "\n" + asCCode(self.body, indent)
        if hasattr(self, "whilePart"): s += "\n" + asCCode(self.whilePart, indent)
        if hasattr(self, "elsePart"): s += "\n" + asCCode(self.elsePart, indent)
        return s
class CForStatement(CControlStructureBase):
    Keyword = "for"
class CDoStatement(CControlStructureBase):
    Keyword = "do"
    StrOutAttribList = [
        ("body", None, None, lambda x: "<...>"),
            ("whilePart", None, None, repr),
            ("defPos", None, "@", str),
    ]
    whilePart = None
class CWhileStatement(CControlStructureBase):
    Keyword = "while"
    def finalize(self, stateStruct, addToContent = None):
        if self._finalized:
            stateStruct.error("internal error: " + str(self) + " finalized twice")
            return
        assert self.parent is not None

        if isinstance(self.parent.body, CBody) and self.parent.body.contentlist:
            last = _getLastCBody(self.parent)
            if isinstance(last, CDoStatement) and not last.whilePart:
                if self.body is not None:
                    stateStruct.error("'while' " + str(self) + " as part of 'do' " + str(last) + " has another body")
                last.whilePart = self
                addToContent = False

        CControlStructureBase.finalize(self, stateStruct, addToContent)
class CContinueStatement(CControlStructureBase):
    Keyword = "continue"
    AlwaysNonZero = True
class CBreakStatement(CControlStructureBase):
    Keyword = "break"
    AlwaysNonZero = True
class CIfStatement(CControlStructureBase):
    Keyword = "if"
    StrOutAttribList = [
        ("args", bool, None, str),
            ("body", None, None, lambda x: "<...>"),
            ("elsePart", None, None, repr),
            ("defPos", None, "@", str),
    ]
    elsePart = None
class CElseStatement(CControlStructureBase):
    Keyword = "else"
    def finalize(self, stateStruct, addToContent = False):
        if self._finalized:
            stateStruct.error("internal error: " + str(self) + " finalized twice")
            return
        assert self.parent is not None

        base = self.parent
        lastIf = None
        last = None
        while True:
            if isinstance(base.body, CBody):
                if not base.body.contentlist: break
                last = base.body.contentlist[-1]
            elif isinstance(base.body, CIfStatement):
                last = base.body
            else:
                break
            if not isinstance(last, CIfStatement):
                if isinstance(last, (CForStatement, CWhileStatement)) and isinstance(last.body, CIfStatement):
                    # loop without curly braced body but directly an if
                    last = last.body
                else:
                    break
            assert isinstance(last, CIfStatement)
            if last.elsePart is not None:
                base = last.elsePart
            else:
                lastIf = last
                # if the if-part of the last has a real body (curly braces), we can stop
                if isinstance(lastIf.body, CBody): break
                # otherwise, we might be the else-part of another inner hanging if
                base = lastIf

        if lastIf is not None:
            lastIf.elsePart = self
        else:
            stateStruct.error("'else' " + str(self) + " without 'if', last was " + str(last))
        CControlStructureBase.finalize(self, stateStruct, addToContent)
class CSwitchStatement(CControlStructureBase):
    Keyword = "switch"
class CCaseStatement(CControlStructureBase):
    Keyword = "case"
class CCaseDefaultStatement(CControlStructureBase):
    Keyword = "default"
    AlwaysNonZero = True
class CGotoStatement(CControlStructureBase):
    Keyword = "goto"
class CReturnStatement(CControlStructureBase):
    Keyword = "return"
    AlwaysNonZero = True

CControlStructures = dict(map(lambda c: (c.Keyword, c), [
    CForStatement,
    CDoStatement,
    CWhileStatement,
    CContinueStatement,
    CBreakStatement,
    CIfStatement,
    CElseStatement,
    CSwitchStatement,
    CCaseStatement,
    CCaseDefaultStatement,
    CGotoStatement,
    CReturnStatement,
]))

def cpre3_parse_statements_in_brackets(stateStruct, parentCObj, sepToken, addToList, input_iter):
    brackets = list(parentCObj._bracketlevel)
    curCObj = _CBaseWithOptBody(parent=parentCObj)
    # For C99 for-init ``for (T a = 0, b = 1; ...; ...)``: when ``,``
    # separates additional declarators sharing the same type, we
    # accumulate the earlier ones here so we can bundle ALL the init
    # declarators as a single list-valued entry in ``addToList`` when
    # ``;`` arrives.  ``astForCFor`` knows how to unpack a list-valued
    # ``args[0]``.
    pending_init_vars = []
    def _make_statement(o):
        assert not o.isDerived()
        CStatement.overtake(o)
        for t in o._type_tokens:
            o._cpre3_handle_token(stateStruct, CIdentifier(t))
        o._type_tokens = []
    def _finalizeCObj(o):
        if not o.isDerived():
            _make_statement(o)
        o.finalize(stateStruct, addToContent=False)
    for token in input_iter:
        if isinstance(token, CIdentifier):
            if isinstance(curCObj, CStatement):
                curCObj._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj.body, CStatement):
                curCObj.body._cpre3_handle_token(stateStruct, token)
            elif token.content in stateStruct.Attribs:
                curCObj.attribs += [token.content]
            elif token.content == "struct":
                CStruct.overtake(curCObj)
            elif token.content == "union":
                CUnion.overtake(curCObj)
            elif token.content == "enum":
                CEnum.overtake(curCObj)
            elif (token.content,) in stateStruct.CBuiltinTypes:
                curCObj._type_tokens += [token.content]
            elif token.content in stateStruct.StdIntTypes:
                curCObj._type_tokens += [token.content]
            elif token.content in stateStruct.typedefs:
                curCObj._type_tokens += [token.content]
            else:
                if curCObj._finalized:
                    # e.g. like "struct {...} X" and we parse "X"
                    oldObj = curCObj
                    curCObj = CVarDecl(parent=parentCObj)
                    curCObj._type_tokens[:] = [oldObj]

                if curCObj.name is None:
                    curCObj.name = token.content
                else:
                    stateStruct.error("cpre3 parse statements in brackets: second identifier name " + token.content + ", first was " + curCObj.name + ", first might be an unknwon type")
                    # fallback recovery, guess vardecl with the first identifier being an unknown type
                    curCObj._type_tokens += [CUnknownType(name=curCObj.name)]
                    curCObj.name = token.content

                if not curCObj.isDerived():
                    if len(curCObj._type_tokens) == 0:
                        curCObj.name = None
                        CStatement.overtake(curCObj)
                        curCObj._cpre3_handle_token(stateStruct, token)
                    else:
                        CVarDecl.overtake(curCObj)
        elif isinstance(token, COpeningBracket):
            # C99 §6.7.8 designated array initializer ``[N] = value``:
            # detect a fresh ``[`` at the start of an init-list arg
            # BEFORE falling into the generic bracket-handling path
            # below (which would treat the brackets as array-indexing
            # on an empty subject and lose the designator).  Real-world
            # hit: ast_opt.c::fold_unaryop's ``static const unary_op
            # ops[] = {[Invert] = ..., [Not] = ..., ...}``.
            if (token.content == "["
                    and not curCObj.isDerived()
                    and not curCObj):
                indexStmt = CStatement(parent=curCObj)
                indexStmt._bracketlevel = list(token.brackets)
                indexStmt._cpre3_parse_brackets(stateStruct, token, input_iter)
                indexStmt.finalize(stateStruct)
                curCObj.designators.append(indexStmt)
                # Expect ``=`` (or another designator) next.  We
                # consume tokens until we see ``=`` -- ``[a][b] = ...``
                # and ``[a].field = ...`` are theoretically allowed
                # but rare; we currently support only simple ``[N] =``.
                next_tok = next(input_iter)
                if not (isinstance(next_tok, COp) and next_tok.content == "="):
                    stateStruct.error(
                        "expected '=' after [N] designator, got " + str(next_tok))
                    continue
                # Fall through to value parsing (next loop iteration
                # consumes the value tokens that follow ``=``).
                continue
            if isinstance(curCObj, CStatement):
                curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)
            elif isinstance(curCObj.body, CStatement):
                curCObj.body._cpre3_parse_brackets(stateStruct, token, input_iter)
            elif not curCObj.isDerived():
                _make_statement(curCObj)
                curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)
            else:
                stateStruct.error("cpre3 parse statements in brackets: " + str(token) + " not expected after " + str(curCObj))
                # fallback
                CStatement.overtake(curCObj)
                curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)
        elif isinstance(token, CClosingBracket):
            if token.brackets == brackets:
                break
            stateStruct.error("cpre3 parse statements in brackets: unexpected closing bracket '" + token.content + "' after " + str(curCObj) + " at bracket level " + str(brackets))
        elif token == sepToken:
            _finalizeCObj(curCObj)
            if isinstance(sepToken, CSemicolon) and pending_init_vars:
                # Multi-declarator for-init: emit the pending list +
                # the just-finalized current obj as ONE addToList entry.
                pending_init_vars.append(curCObj)
                addToList.append(pending_init_vars)
                pending_init_vars = []
            else:
                addToList.append(curCObj)
            # For C99 for-loop init (sepToken=semicolon): make declared
            # vars visible in subsequent statements (condition and
            # increment parts).  ALWAYS overwrite any existing entry --
            # if a previous for-loop in the same function declared the
            # same name (e.g. ``for (int i ...) {} for (int i ...) {}``),
            # the stale CVarDecl would otherwise leak into our second
            # loop's cond/inc lookup and the interpreter would fail to
            # find the local var (``CVarDecl 'i' expected to be a
            # global var``).  Side effect: the for-init var still
            # leaks past the loop end into the function scope, but
            # well-formed C code never references it there.
            if isinstance(sepToken, CSemicolon) and isinstance(curCObj, CVarDecl) and curCObj.name:
                p = parentCObj
                while p is not None:
                    if hasattr(p, 'body') and isinstance(p.body, CBody):
                        p.body.vars[curCObj.name] = curCObj
                        break
                    p = getattr(p, 'parent', None)
            curCObj = _CBaseWithOptBody(parent=parentCObj)
        elif (isinstance(sepToken, CSemicolon)
              and token == COp(",")
              and isinstance(curCObj, CVarDecl)
              and curCObj.name):
            # Multi-declarator separator inside a for-loop init:
            # ``for (T a = 0, b = 1; ...; ...)`` -- finalize ``a``,
            # make it visible to subsequent statements, then start a
            # fresh declarator carrying the same type tokens for ``b``.
            # Copy BEFORE finalize so the new declarator inherits the
            # type tokens but NOT ``_finalized=True`` (mirrors the
            # body-parser ``,`` handling around line ~5028).
            oldObj = curCObj
            newObj = oldObj.copy()
            newObj._already_added = False
            oldObj.finalize(stateStruct, addToContent=False)
            newObj.clearDeclForNextVar()
            newObj.name = None
            newObj.body = None
            newObj.parent = parentCObj
            p = parentCObj
            while p is not None:
                if hasattr(p, 'body') and isinstance(p.body, CBody):
                    p.body.vars[oldObj.name] = oldObj
                    break
                p = getattr(p, 'parent', None)
            pending_init_vars.append(oldObj)
            curCObj = newObj
        elif isinstance(token, CSemicolon): # if the sepToken is not the semicolon, we don't expect it at all
            stateStruct.error("cpre3 parse statements in brackets: ';' not expected, separator should be " + str(sepToken))
        elif (token == COp("*") and isinstance(sepToken, CSemicolon)
              and not curCObj.isDerived()
              and (curCObj._type_tokens or curCObj.attribs)
              and (
                  # Type qualifiers (const, volatile, …) are present — unambiguously a
                  # declaration, not multiplication.  E.g. `for (const char *p = …)`.
                  curCObj.attribs
                  # OR every type token so far is a built-in / stdint type (not a typedef
                  # alias), so `*` cannot be multiplication.
                  # E.g. `for (int *p = …)` or `for (char *p = …)`.
                  or all(
                      (isinstance(t, str) and (
                          (t,) in stateStruct.CBuiltinTypes
                          or t in stateStruct.StdIntTypes
                          or t == "*"
                      ))
                      for t in curCObj._type_tokens
                  )
              )):
            # Pointer type modifier in a C99 for-init declaration context.  Only applied
            # when the separator is `;` (for-init), not `,` (function-call args, where
            # `void *` is a plain type argument).  Mirror the `_cpre3_parse_body` handling.
            CVarDecl.overtake(curCObj)
            curCObj._type_tokens += [token.content]
        elif isinstance(curCObj, CVarDecl) and token == COp("="):
            curCObj.body = CStatement(parent=curCObj)
        else:
            # Handle C99 designated initializer syntax: ``.fieldname =
            # value`` (struct) or ``[index] = value`` (array).  ``.``
            # is a COp; ``[`` is a COpeningBracket -- both must be
            # recognized here.  Without the bracket case, the parser
            # falls through to the regular ``[`` handling, and the
            # designator gets lost -- e.g. ``[Invert] = PyNumber_Invert``
            # in ast_opt.c::fold_unaryop produces an off-by-one array
            # of function pointers, leading to a NULL-call SIGSEGV when
            # ``compile()`` invokes the AST optimizer at runtime.
            if (((isinstance(token, COp) and token.content == ".")
                    or (isinstance(token, COpeningBracket) and token.content == "["))
                    and not curCObj.isDerived() and not curCObj):
                while True:
                    if isinstance(token, COp) and token.content == ".":
                        token = next(input_iter)
                        if not isinstance(token, CIdentifier):
                            stateStruct.error("expected identifier after '.' in designated initializer")
                            break
                        curCObj.designators.append(token.content)
                        token = next(input_iter)
                    elif isinstance(token, COpeningBracket) and token.content == "[":
                        indexStmt = CStatement(parent=curCObj)
                        indexStmt._bracketlevel = list(token.brackets)
                        indexStmt._cpre3_parse_brackets(stateStruct, token, input_iter)
                        indexStmt.finalize(stateStruct)
                        curCObj.designators.append(indexStmt)
                        token = next(input_iter)
                    
                    if isinstance(token, COp) and token.content == "=":
                        break
                    if not (isinstance(token, COp) and token.content in (".", "[")):
                        stateStruct.error("expected '=' or another designator, got " + str(token))
                        break
                _make_statement(curCObj)
                continue

            if not curCObj.isDerived():
                _make_statement(curCObj)
            if isinstance(curCObj, CStatement):
                curCObj._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj.body, CStatement):
                curCObj.body._cpre3_handle_token(stateStruct, token)
            else:
                stateStruct.error("cpre3 parse statements in brackets: " + str(token) + " not expected after " + str(curCObj))

    # add also the last object
    if isinstance(sepToken, CSemicolon) or curCObj:
        _finalizeCObj(curCObj)
        addToList.append(curCObj)

def cpre3_parse_single_next_statement(stateStruct, parentCObj, input_iter):
    curCObj = None
    for token in input_iter:
        if isinstance(token, COpeningBracket):
            if token.content == "{" and curCObj is None:
                # No pending statement yet: '{' starts a block body.
                parentCObj._bracketlevel = list(token.brackets)
                cpre3_parse_body(stateStruct, parentCObj, input_iter)
                return
            if curCObj is None:
                curCObj = CStatement(parent=parentCObj)
            if isinstance(curCObj, CStatement):
                curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)
            elif curCObj is not None and isinstance(curCObj.body, CStatement):
                curCObj.body._cpre3_parse_brackets(stateStruct, token, input_iter)
            elif isinstance(curCObj, CControlStructureBase):
                curCObj._bracketlevel = list(token.brackets)
                if token.content == "(":
                    cpre3_parse_statements_in_brackets(stateStruct, curCObj, sepToken=CSemicolon(), addToList=curCObj.args, input_iter=input_iter)
                    curCObj._bracketlevel = list(parentCObj._bracketlevel)
                    lasttoken = cpre3_parse_single_next_statement(stateStruct, curCObj, input_iter)
                    curCObj.finalize(stateStruct)
                    parentCObj.addToBody(curCObj)
                    return lasttoken
                elif token.content == "[":
                    stateStruct.error("cpre3 parse single after " + str(curCObj) + ": got unexpected '['")
                    _cpre3_parse_skipbracketcontent(stateStruct, list(token.brackets), input_iter)
                    return
                elif token.content == "{":
                    if curCObj.body is not None:
                        stateStruct.error("cpre3 parse single after " + str(curCObj) + ": got multiple bodies")
                    cpre3_parse_body(stateStruct, curCObj, input_iter)
                    curCObj.finalize(stateStruct)
                    parentCObj.addToBody(curCObj)
                    return
                else:
                    stateStruct.error("cpre3 parse single after " + str(curCObj) + ": got unexpected/unknown opening bracket '" + token.content + "'")
                    _cpre3_parse_skipbracketcontent(stateStruct, list(token.brackets), input_iter)
                    return
            else:
                stateStruct.error("cpre3 parse single: unexpected opening bracket '" + token.content + "' after " + str(curCObj))
        elif isinstance(token, CClosingBracket):
            if token.brackets == parentCObj._bracketlevel:
                stateStruct.error("cpre3 parse single: closed brackets without expected statement")
                return token
            stateStruct.error("cpre3 parse single: unexpected closing bracket '" + token.content + "' after " + str(curCObj) + " at bracket level " + str(parentCObj._bracketlevel))
        elif isinstance(token, CSemicolon):
            if curCObj and not curCObj.isDerived():
                CVarDecl.overtake(curCObj)
            if curCObj is not None:
                curCObj.finalize(stateStruct)
                parentCObj.addToBody(curCObj)
            return token
        elif curCObj is None and isinstance(token, CIdentifier) and token.content in CControlStructures:
            curCObj = CControlStructures[token.content](parent=parentCObj)
            curCObj.defPos = stateStruct.curPosAsStr()
            if isinstance(curCObj, (CElseStatement,CDoStatement)):
                curCObj._bracketlevel = list(parentCObj._bracketlevel)
                lasttoken = cpre3_parse_single_next_statement(stateStruct, curCObj, input_iter)
                # We finalize in any way, also for 'do'. We don't do any semantic checks here
                # if there is a correct 'while' following or neither if the 'else' has a previous 'if'.
                curCObj.finalize(stateStruct)
                parentCObj.addToBody(curCObj)
                return lasttoken
            elif isinstance(curCObj, CReturnStatement):
                curCObj.body = CStatement(parent=curCObj)
        elif isinstance(curCObj, CGotoStatement):
            if curCObj.name is None:
                curCObj.name = token.content
            else:
                stateStruct.error("cpre3 parse single after %s: got second identifier %s" % (curCObj, token))
        elif isinstance(curCObj, CStatement):
            curCObj._cpre3_handle_token(stateStruct, token)
            if isinstance(curCObj, CGotoLabel):
                if parentCObj.body is None:
                    parentCObj.body = CBody(parent=parentCObj.parent.body)
                parentCObj.addToBody(curCObj)
                curCObj = None
        elif curCObj is not None and isinstance(curCObj.body, CStatement):
            curCObj.body._cpre3_handle_token(stateStruct, token)
        elif isinstance(curCObj, CControlStructureBase):
            stateStruct.error("cpre3 parse after %s: didn't expected identifier %s" % (curCObj, token))
        elif curCObj is None:
            curCObj = CStatement(parent=parentCObj)
            curCObj._cpre3_handle_token(stateStruct, token)
        else:
            stateStruct.error("cpre3 parse single: got unexpected token %s after %s" % (token, curCObj))
    stateStruct.error("cpre3 parse single: runaway")
    return


def cpre3_parse_body(stateStruct, parentCObj, input_iter):
    """
    :param State stateStruct:
    :param parentCObj:
    :param input_iter:
    """
    if parentCObj.body is None:
        parentCObj.body = CBody(parent=parentCObj.parent.body)

    curCObj = _CBaseWithOptBody(parent=parentCObj)

    while True:
        stateStruct._cpre3_atBaseLevel = False
        if parentCObj._bracketlevel is None:
            if not curCObj:
                stateStruct._cpre3_atBaseLevel = True

        try: token = next(input_iter)
        except StopIteration: break

        if isinstance(token, CIdentifier):
            if isinstance(curCObj, CStatement):
                curCObj._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj.body, CStatement):
                curCObj.body._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj, CGotoStatement):
                if curCObj.name is None:
                    curCObj.name = token.content
                else:
                    stateStruct.error("cpre3 parse after " + str(curCObj) + ": got second identifier '" + token.content + "'")
            elif isinstance(curCObj, CCaseStatement):
                if not curCObj.args or not isinstance(curCObj.args[-1], CStatement):
                    curCObj.args.append(CStatement(parent=parentCObj))
                curCObj.args[-1]._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj, CControlStructureBase):
                stateStruct.error("cpre3 parse after " + str(curCObj) + ": didn't expected identifier '" + token.content + "'")
            elif token.content == "typedef":
                CTypedef.overtake(curCObj)
                curCObj.defPos = stateStruct.curPosAsStr()
                cpre3_parse_typedef(stateStruct, curCObj, input_iter)
                curCObj = _CBaseWithOptBody(parent=parentCObj)
            elif token.content in stateStruct.Attribs:
                curCObj.attribs += [token.content]
            elif token.content == "struct":
                CStruct.overtake(curCObj)
                curCObj.defPos = stateStruct.curPosAsStr()
            elif token.content == "union":
                CUnion.overtake(curCObj)
                curCObj.defPos = stateStruct.curPosAsStr()
            elif token.content == "enum":
                CEnum.overtake(curCObj)
                curCObj.defPos = stateStruct.curPosAsStr()
            elif token.content in CControlStructures:
                if curCObj.isDerived() or curCObj:
                    stateStruct.error("cpre3 parse: got '" + token.content + "' after " + str(curCObj))
                    # try to finalize and reset
                    curCObj.finalize(stateStruct)
                    curCObj = _CBaseWithOptBody(parent=parentCObj)
                CControlStructures[token.content].overtake(curCObj)
                curCObj.defPos = stateStruct.curPosAsStr()
                if isinstance(curCObj, (CElseStatement,CDoStatement)):
                    curCObj._bracketlevel = list(parentCObj._bracketlevel)
                    lasttoken = cpre3_parse_single_next_statement(stateStruct, curCObj, input_iter)
                    # We finalize in any way, also for 'do'. We don't do any semantic checks here
                    # if there is a correct 'while' following or neither if the 'else' has a previous 'if'.
                    curCObj.finalize(stateStruct)
                    if isinstance(lasttoken, CClosingBracket) and lasttoken.brackets == parentCObj._bracketlevel:
                        return
                    curCObj = _CBaseWithOptBody(parent=parentCObj)
                elif isinstance(curCObj, CReturnStatement):
                    curCObj.body = CStatement(parent=curCObj)
            elif (token.content,) in stateStruct.CBuiltinTypes:
                curCObj._type_tokens += [token.content]
            elif not curCObj._type_tokens and token.content in stateStruct.StdIntTypes:
                curCObj._type_tokens += [token.content]
            elif not curCObj._type_tokens and not curCObj.isDerived() \
                and (token.content in stateStruct.vars
                     or token.content in parentCObj.body.vars
                     or (isinstance(parentCObj, CFunc)
                         and token.content in [a.name for a in parentCObj.args])):
                assert curCObj.name is None
                CStatement.overtake(curCObj)
                curCObj._cpre3_handle_token(stateStruct, token)
            elif not curCObj._type_tokens and not curCObj.isDerived() and isType(findObjInNamespace(stateStruct, parentCObj, token.content)):
                curCObj._type_tokens += [token.content]
            else:
                if curCObj._finalized:
                    # e.g. like "struct {...} X" and we parse "X"
                    oldObj = curCObj
                    curCObj = CVarDecl(parent=parentCObj)
                    curCObj._type_tokens[:] = [oldObj]

                if curCObj.name is None:
                    curCObj.name = token.content
                    DictName = None
                    if isinstance(curCObj, CStruct): DictName = "structs"
                    elif isinstance(curCObj, CUnion): DictName = "unions"
                    elif isinstance(curCObj, CEnum): DictName = "enums"
                    if DictName is not None:
                        typeObj = findCObjTypeInNamespace(stateStruct, parentCObj, DictName, curCObj.name)
                        if typeObj is not None and typeObj.body is not None: # if body is None, we still wait for another decl
                            curCObj = CVarDecl(parent=parentCObj)
                            curCObj._type_tokens += [typeObj]
                else:
                    stateStruct.error("cpre3 parse: second identifier name " + token.content + ", first was " + curCObj.name + ", first might be an unknwon type")
                    typeObj = CUnknownType(name=curCObj.name)
                    # fallback recovery, guess vardecl with the first identifier being an unknown type
                    curCObj = CVarDecl(parent=parentCObj)
                    curCObj._type_tokens += [typeObj]
                    curCObj.name = token.content

                if not curCObj.isDerived():
                    if len(curCObj._type_tokens) == 0:
                        curCObj.name = None
                        CStatement.overtake(curCObj)
                        curCObj._cpre3_handle_token(stateStruct, token)
                    else:
                        CVarDecl.overtake(curCObj)
        elif isinstance(token, COp):
            if (not curCObj.isDerived() or isinstance(curCObj, CVarDecl)) and len(curCObj._type_tokens) == 0:
                CStatement.overtake(curCObj)
            if isinstance(curCObj, CStatement):
                curCObj._cpre3_handle_token(stateStruct, token)
                if curCObj._finalized: # might have been finalized internally. e.g. in case it was a goto-loop
                    curCObj = _CBaseWithOptBody(parent=parentCObj)
            elif isinstance(curCObj.body, CStatement) and token.content != ",": # op(,) gets some extra handling. eg for CVarDecl
                curCObj.body._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj, CCaseStatement):
                if token.content == ":":
                    curCObj.finalize(stateStruct)
                    curCObj = _CBaseWithOptBody(parent=parentCObj)
                else:
                    if not curCObj.args or not isinstance(curCObj.args[-1], CStatement):
                        curCObj.args.append(CStatement(parent=parentCObj))
                    curCObj.args[-1]._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj, CCaseDefaultStatement) and token.content == ":":
                curCObj.finalize(stateStruct)
                curCObj = _CBaseWithOptBody(parent=parentCObj)
            elif isinstance(curCObj, CControlStructureBase):
                if isinstance(curCObj.body, CStatement): # for example, because of op(,), we might have missed that above
                    curCObj.body._cpre3_handle_token(stateStruct, token)
                else:
                    stateStruct.error("cpre3 parse after " + str(curCObj) + ": didn't expected op '" + token.content + "'")
            else:
                if token.content == "*":
                    if isinstance(curCObj, (CStruct,CUnion,CEnum)):
                        curCObj.finalize(stateStruct)
                        oldObj = curCObj
                        curCObj = CVarDecl(parent=parentCObj)
                        curCObj._type_tokens[:] = [oldObj, "*"]
                    else:
                        CVarDecl.overtake(curCObj)
                        curCObj._type_tokens += [token.content]
                elif token.content == ",":
                    CVarDecl.overtake(curCObj)
                    oldObj = curCObj
                    curCObj = curCObj.copy()
                    curCObj._already_added = False
                    oldObj.finalize(stateStruct)
                    curCObj.clearDeclForNextVar()
                    curCObj.name = None
                    curCObj.body = None
                elif token.content == ":" and curCObj and curCObj._type_tokens:
                    CVarDecl.overtake(curCObj)
                    curCObj.bitsize = None
                elif token.content == "=" and curCObj and (isinstance(curCObj, CVarDecl) or not curCObj.isDerived()):
                    if not curCObj.isDerived():
                        CVarDecl.overtake(curCObj)
                    curCObj.body = CStatement(parent=curCObj)
                    if isinstance(curCObj, CVarDecl):
                        # Early add, so that the var init body can reference it's own instance,
                        # e.g. its pointer.
                        _addToParent(curCObj, stateStruct, dictName="vars")
                        curCObj._already_added = True
                else:
                    stateStruct.error(
                        "cpre3 parse: op %r not expected in %s after %s" % (
                            token.content, parentCObj, curCObj))
        elif isinstance(token, CNumber):
            if isinstance(curCObj, CVarDecl) and hasattr(curCObj, "bitsize"):
                curCObj.bitsize = token.content
            elif isinstance(curCObj, CStatement):
                curCObj._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj.body, CStatement):
                curCObj.body._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj, CCaseStatement):
                if not curCObj.args or not isinstance(curCObj.args[-1], CStatement):
                    curCObj.args.append(CStatement(parent=parentCObj))
                curCObj.args[-1]._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj, CControlStructureBase):
                stateStruct.error("cpre3 parse after " + str(curCObj) + ": didn't expected number '" + str(token.content) + "'")
            else:
                CStatement.overtake(curCObj)
                curCObj._cpre3_handle_token(stateStruct, token)
        elif isinstance(token, COpeningBracket):
            curCObj._bracketlevel = list(token.brackets)
            if not _isBracketLevelOk(parentCObj._bracketlevel, token.brackets):
                stateStruct.error("cpre3 parse body: internal error: bracket level messed up with opening bracket: " + str(token.brackets) + " on level " + str(parentCObj._bracketlevel) + " in " + str(parentCObj))
            if isinstance(curCObj, CStatement):
                curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)
            elif isinstance(curCObj.body, CStatement):
                curCObj.body._cpre3_parse_brackets(stateStruct, token, input_iter)
            elif isinstance(curCObj, CCaseStatement):
                if not curCObj.args or not isinstance(curCObj.args[-1], CStatement):
                    curCObj.args.append(CStatement(parent=parentCObj))
                curCObj.args[-1]._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj, CControlStructureBase):
                if token.content == "(":
                    cpre3_parse_statements_in_brackets(stateStruct, curCObj, sepToken=CSemicolon(), addToList=curCObj.args, input_iter=input_iter)
                    curCObj._bracketlevel = list(parentCObj._bracketlevel or [])
                    lasttoken = cpre3_parse_single_next_statement(stateStruct, curCObj, input_iter)
                    curCObj.finalize(stateStruct)
                    if isinstance(lasttoken, CClosingBracket) and lasttoken.brackets == parentCObj._bracketlevel:
                        return
                    curCObj = _CBaseWithOptBody(parent=parentCObj)
                elif token.content == "[":
                    stateStruct.error("cpre3 parse after " + str(curCObj) + ": got unexpected '['")
                    _cpre3_parse_skipbracketcontent(stateStruct, list(token.brackets), input_iter)
                elif token.content == "{":
                    if curCObj.body is not None:
                        stateStruct.error("cpre3 parse after " + str(curCObj) + ": got multiple bodies")
                    cpre3_parse_body(stateStruct, curCObj, input_iter)
                    curCObj.finalize(stateStruct)
                    curCObj = _CBaseWithOptBody(parent=parentCObj)
                else:
                    stateStruct.error("cpre3 parse after " + str(curCObj) + ": got unexpected/unknown opening bracket '" + token.content + "'")
                    _cpre3_parse_skipbracketcontent(stateStruct, list(token.brackets), input_iter)
            elif token.content == "(":
                if len(curCObj._type_tokens) == 0:
                    CStatement.overtake(curCObj)
                    curCObj._cpre3_parse_brackets(stateStruct, token, input_iter)
                elif curCObj.name is None:
                    typeObj = CFuncPointerDecl(parent=curCObj)
                    typeObj._bracketlevel = curCObj._bracketlevel
                    typeObj._type_tokens[:] = curCObj._type_tokens
                    CVarDecl.overtake(curCObj)
                    curCObj._type_tokens[:] = [typeObj]
                    cpre3_parse_funcpointername(stateStruct, typeObj, input_iter)
                    curCObj.name = typeObj.name
                elif len(curCObj._type_tokens) == 1 and isinstance(curCObj._type_tokens[0], CFuncPointerDecl):
                    typeObj = curCObj._type_tokens[0]
                    cpre3_parse_funcargs(stateStruct, typeObj, input_iter)
                    typeObj.finalize(stateStruct)
                else:
                    CFunc.overtake(curCObj)
                    curCObj.defPos = stateStruct.curPosAsStr()
                    cpre3_parse_funcargs(stateStruct, curCObj, input_iter)
            elif token.content == "[":
                CVarDecl.overtake(curCObj)
                cpre3_parse_arrayargs(stateStruct, curCObj, input_iter)
            elif token.content == "{":
                if curCObj.isDerived():
                    if isinstance(curCObj, CStruct):
                        cpre3_parse_struct(stateStruct, curCObj, input_iter)
                    elif isinstance(curCObj, CUnion):
                        cpre3_parse_union(stateStruct, curCObj, input_iter)
                    elif isinstance(curCObj, CEnum):
                        cpre3_parse_enum(stateStruct, curCObj, input_iter)
                    elif isinstance(curCObj, CFunc):
                        cpre3_parse_funcbody(stateStruct, curCObj, input_iter)
                        curCObj = _CBaseWithOptBody(parent=parentCObj)
                    else:
                        stateStruct.error("cpre3 parse: unexpected '{' after " + str(curCObj))
                        curCObj = _CBaseWithOptBody(parent=parentCObj)
                else:
                    if not parentCObj.body is stateStruct: # not top level
                        CCodeBlock.overtake(curCObj)
                        curCObj.defPos = stateStruct.curPosAsStr()
                        cpre3_parse_body(stateStruct, curCObj, input_iter)
                        curCObj.finalize(stateStruct)
                    curCObj = _CBaseWithOptBody(parent=parentCObj)
            else:
                stateStruct.error("cpre3 parse: unexpected opening bracket '" + token.content + "'")
        elif isinstance(token, CClosingBracket):
            if token.content == "}":
                curCObj.finalize(stateStruct)
                curCObj = _CBaseWithOptBody(parent=parentCObj)
            else:
                stateStruct.error("cpre3 parse: unexpected closing bracket '" + token.content + "' after " + str(curCObj))
            if token.brackets == parentCObj._bracketlevel:
                return
            if not _isBracketLevelOk(parentCObj._bracketlevel, token.brackets):
                stateStruct.error("cpre3 parse body: internal error: bracket level messed up with closing bracket: " + str(token.brackets) + " on level " + str(parentCObj._bracketlevel) + " in " + str(parentCObj))
        elif isinstance(token, CSemicolon):
            if not curCObj.isDerived() and curCObj:
                CVarDecl.overtake(curCObj)
            if not curCObj._finalized:
                curCObj.finalize(stateStruct)
            curCObj = _CBaseWithOptBody(parent=parentCObj)
        elif isinstance(token, (CStr,CChar)):
            if isinstance(curCObj, CStatement):
                curCObj._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj.body, CStatement):
                curCObj.body._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj, CCaseStatement):
                if not curCObj.args or not isinstance(curCObj.args[-1], CStatement):
                    curCObj.args.append(CStatement(parent=parentCObj))
                curCObj.args[-1]._cpre3_handle_token(stateStruct, token)
            elif isinstance(curCObj, CControlStructureBase):
                stateStruct.error("cpre3 parse after " + str(curCObj) + ": didn't expected " + str(token))
            elif not curCObj:
                CStatement.overtake(curCObj)
                curCObj._cpre3_handle_token(stateStruct, token)
            else:
                stateStruct.error("cpre3 parse: unexpected str " + str(token) + " after " + str(curCObj))
        else:
            stateStruct.error("cpre3 parse: unexpected token " + str(token))

    if curCObj and not curCObj._finalized:
        stateStruct.error("cpre3 parse: unfinished " + str(curCObj) + " at end of " + str(parentCObj))

    if parentCObj._bracketlevel is not None:
        stateStruct.error("cpre3 parse: read until end without closing brackets " + str(parentCObj._bracketlevel) + " in " + str(parentCObj))


def cpre3_parse(stateStruct, input):
    """
    :param State stateStruct:
    :param input:
    """
    input_iter = iter(input)
    parentObj = _CBaseWithOptBody()
    parentObj.body = stateStruct
    cpre3_parse_body(stateStruct, parentObj, input_iter)


def parse(filename, state=None):
    """
    :param str filename:
    :param State|None state:
    :rtype: State
    """
    if state is None:
        state = State()
        state.autoSetupSystemMacros()

    preprocessed = state.preprocess_file(filename, local=True)
    tokens = cpre2_parse(state, preprocessed)
    cpre3_parse(state, tokens)

    return state


def parse_code(source_code, state=None):
    """
    :param str source_code:
    :param State|None state:
    :rtype: State
    """
    if state is None:
        state = State()
        state.autoSetupSystemMacros()

    try:
        preprocessed = state.preprocess_source_code(source_code)
        tokens = cpre2_parse(state, preprocessed)
        cpre3_parse(state, tokens)
    except Exception as e:
        state.error("internal exception: %r" % e)
        print("parsing errors:")
        for s in state._errors:
            print(s)
        raise

    return state


def demo_parse_file(filename):
    import better_exchook
    better_exchook.install()
    from pprint import pprint

    state = State()
    state.autoSetupSystemMacros()

    preprocessed = state.preprocess_file(filename, local=True)
    tokens = cpre2_parse(state, preprocessed)

    token_list = []
    def copy_hook(input, output):
        for x in input:
            output.append(x)
            yield x
    tokens = copy_hook(tokens, token_list)

    cpre3_parse(state, tokens)
    if state._errors:
        print("parse errors:")
        pprint(state._errors)

    return state, token_list


class CWrapValue(CType):
    """
    This wraps types, values and custom Python functions.
    """

    def __init__(self, value, decl=None, name=None, **kwattr):
        if isinstance(value, int):
            value = ctypes.c_int(value)
        super(CWrapValue, self).__init__(**kwattr)
        self.value = value
        self.decl = decl
        self.name = name

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
            value = ctypes.cast(value, wrapCTypeClass(ctypes.c_void_p))
        if isinstance(value, ctypes._SimpleCData):
            value = value.value
        return value

    def getReturnType(self, stateStruct, stmnt_args):
        """
        This is called if this is used as a function call to determine its return type.
        """
        assert self.returnType is not None
        return self.returnType


class CWrapFuncType(CType, CFuncPointerBase):
    def __init__(self, func, funcEnv):
        """
        :type func: CFunc
        """
        super(CWrapFuncType, self).__init__()
        self.func = func
        self.funcEnv = funcEnv

    def getCType(self, stateStruct):
        return self.func.getCType(stateStruct)


def isPointerType(t, checkWrapValue=False, alsoFuncPtr=False, alsoArray=True):
    while isinstance(t, CTypedef):
        t = t.type
    if isinstance(t, CPointerType): return True
    if alsoArray:
        if isinstance(t, CArrayType): return True
    if isinstance(t, CBuiltinType) and t.builtinType == ("void", "*"): return True
    if checkWrapValue and isinstance(t, CWrapValue):
        return isPointerType(t.getCType(None), checkWrapValue=True, alsoFuncPtr=alsoFuncPtr)
    from inspect import isclass
    if alsoFuncPtr:
        if isinstance(t, CWrapFuncType): return True
        if isinstance(t, CFuncPointerDecl): return True
        if isclass(t) and issubclass(t, ctypes._CFuncPtr): return True
    if isclass(t):
        if issubclass(t, _ctypes._Pointer): return True
        if issubclass(t, ctypes.c_void_p): return True
    return False


def isVoidPtrType(t):
    if isinstance(t, CPointerType):
        return t.pointerOf == CBuiltinType(("void",))
    if isinstance(t, CBuiltinType) and t.builtinType == ("void", "*"):
        return True
    return False


def isValueType(t):
    if isinstance(t, (CBuiltinType, CStdIntType, CBitfieldType)): return True
    from inspect import isclass
    if isclass(t):
        for c in State.StdIntTypes.values():
            if issubclass(t, c): return True
    return False


def isExternDecl(obj):
    if isinstance(obj, CVarDecl):
        return "extern" in obj.attribs
    elif isinstance(obj, (CStruct, CUnion, CEnum, CFunc)):
        return obj.body is None
    elif isinstance(obj, CTypedef):
        return False
    else:
        assert False, "unknown type: %r %r" % (obj, type(obj))


if __name__ == '__main__':
    import sys
    demo_parse_file(sys.argv[1])
