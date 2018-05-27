import types
import sys

if sys.version_info.major == 2:
    def rebound_instance_method(f, newobj):
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


def setup_Structure_debug_helper():
    import ctypes

    class DebugStruct(ctypes.Structure):
        def __init__(self, *args):
            assert hasattr(self, "_fields_")
            assert len(args) <= len(self._fields_)
            super(DebugStruct, self).__init__(*args)

    ctypes.Structure = DebugStruct
