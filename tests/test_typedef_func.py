
import helpers_test
import cparser
import ctypes

def test_typedef_func_vs_ptr():
    # typedef void f();
    # f x; -> void x();
    state1 = helpers_test.parse("typedef void f(); f x;")
    x1 = state1.vars['x']
    
    # typedef void (*f_ptr)();
    # f_ptr y; -> void (*y)();
    state2 = helpers_test.parse("typedef void (*f_ptr)(); f_ptr y;")
    y2 = state2.vars['y']
    
    def resolve(t):
        while isinstance(t, cparser.CTypedef):
            t = t.type
        return t

    rx1 = resolve(x1.type)
    ry2 = resolve(y2.type)
    
    assert isinstance(rx1, cparser.CFunc)
    assert isinstance(ry2, cparser.CFuncPointerDecl)

    # Test pointers
    state3 = helpers_test.parse("typedef void f(); f* p;")
    p3 = state3.vars['p']
    c_p3 = p3.type.getCType(state3)
    c_f = rx1.getCType(state3)
    assert c_p3 == c_f

    # Test pointer to function pointer
    state4 = helpers_test.parse("typedef void (*f_ptr)(); f_ptr* p;")
    p4 = state4.vars['p']
    c_p4 = p4.type.getCType(state4)
    c_f_ptr = ry2.getCType(state4)
    assert c_p4 != c_f_ptr
    assert c_p4 == ctypes.POINTER(c_f_ptr)

if __name__ == "__main__":
    test_typedef_func_vs_ptr()
