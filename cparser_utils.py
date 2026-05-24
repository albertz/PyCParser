import types
import sys
import keyword


if sys.version_info.major == 2:
    def rebound_instance_method(f, newobj):
        # noinspection PyArgumentList
        return types.MethodType(f.im_func, newobj, newobj.__class__)
else:
    def rebound_instance_method(f, newobj):
        return lambda *args, **kwargs: f.__func__(newobj, *args, **kwargs)

if sys.version_info.major == 2:
    def generic_class_method(f):
        return f.im_func
else:
    def generic_class_method(f):
        return f

if sys.version_info.major >= 3:
    unicode = str
    long = int
    unichr = chr
else:
    # noinspection PyUnresolvedReferences
    unicode = __builtins__["unicode"]
    # noinspection PyUnresolvedReferences
    long = __builtins__["long"]
    # noinspection PyUnresolvedReferences
    unichr = __builtins__["unichr"]


# Python object class-level attrs (``__doc__``, ``__class__``,
# ``__annotations__``, ``__dict__``, ...).  A C identifier with one
# of these names would silently return the inherited Python attr
# instead of our ``GlobalsWrapper.__getattr__`` value, OR collide
# with the class itself when used as a Python identifier.  Include
# ``object``'s and ``type``'s attrs so we cover both instance and
# class lookup paths.
_object_dunders = frozenset(
    a for a in dir(object) if a.startswith("__") and a.endswith("__")
)
_type_dunders = frozenset(
    a for a in dir(type) if a.startswith("__") and a.endswith("__")
)
_shadowing_dunders = _object_dunders | _type_dunders | frozenset({
    # Common dunders not on plain ``object`` that nevertheless
    # collide when present on user objects (e.g. modules).
    "__annotations__", "__name__", "__qualname__", "__module__",
    "__file__", "__path__", "__loader__", "__spec__", "__package__",
    "__builtins__",
})


def py_safe_identifier(name):
    """Rename a C identifier to a non-Python-keyword equivalent.

    C allows ``def``, ``class``, ``lambda``, ``return`` etc. as
    identifiers (variable names, struct field names, function names);
    Python forbids them.  C code also sometimes uses dunder names
    that Python's ``object`` class has built-in (``__doc__``,
    ``__class__``, ``__annotations__`` ...) -- those would silently
    return the inherited Python value instead of our C-side value.

    Rule: append a single underscore.  Applied consistently
    everywhere a C identifier becomes a Python identifier -- at
    struct ``_fields_`` definition AND at every access site -- so
    the two sides stay in sync.

    >>> py_safe_identifier("def")
    'def_'
    >>> py_safe_identifier("__doc__")
    '__doc___'
    >>> py_safe_identifier("foo")
    'foo'
    """
    if name is None:
        return name
    if keyword.iskeyword(name):
        return name + "_"
    # ``match`` / ``case`` / ``type`` are *soft* keywords in 3.10+.
    # Valid as regular identifiers but ambiguous in kwarg context.
    if hasattr(keyword, "issoftkeyword") and keyword.issoftkeyword(name):
        return name + "_"
    # Dunders that ``object``/``type`` already provide: rename so
    # ``GlobalsWrapper`` / struct-instance attribute lookups don't
    # silently return Python's inherited class attr.
    if name in _shadowing_dunders:
        return name + "_"
    return name


def setup_Structure_debug_helper():
    import ctypes

    class DebugStruct(ctypes.Structure):
        def __init__(self, *args):
            assert hasattr(self, "_fields_")
            assert len(args) <= len(self._fields_)
            super(DebugStruct, self).__init__(*args)

    ctypes.Structure = DebugStruct
