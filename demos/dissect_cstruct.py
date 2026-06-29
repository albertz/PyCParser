"""
https://github.com/fox-it/dissect.cstruct
"""

import ctypes
import cparser
from cparser import interpreter


def demo_struct_and_enum():
    # language=C
    parser_def = """
    #include <stdint.h>

    #define SOME_CONSTANT 5

    typedef enum : uint16_t {
        A,
        B = 0x5,
        C
    } Example;

    struct __attribute__((packed)) some_struct {
        uint8_t field_1;
        char    field_2[SOME_CONSTANT];
        char    field_3[5];
        Example field_4[2];
    };
    """

    state = cparser.parse_code(parser_def)
    intp = interpreter.Interpreter()
    intp.register(state)

    some_struct = intp.getCType(state.structs["some_struct"])
    Example = {c.name: c.value for c in state.typedefs["Example"].type.body.contentlist}
    assert Example == {"A": 0, "B": 5, "C": 6}

    data = b"\x01helloworld\x00\x00\x06\x00"
    result = some_struct.from_buffer_copy(data)
    assert result.field_1.value == 0x01
    assert bytes(result.field_2) == b"hello"
    assert bytes(result.field_3) == b"world"
    assert [x.value for x in result.field_4] == [Example["A"], Example["C"]]

    inst = some_struct()
    inst.field_1 = 5
    inst.field_2[:] = b"lorem"
    inst.field_3[:] = b"ipsum"
    inst.field_4[0], inst.field_4[1] = Example["B"], Example["A"]

    blob = bytes(inst)
    print("dumped %d bytes: %r" % (len(blob), blob))
    assert blob == b"\x05loremipsum\x05\x00\x00\x00"
    print("OK")


def demo_unions_and_anonymous():
    # language=C
    parser_def = """
    #include <stdint.h>

    struct test_union {
        char magic[4];
        union {
            struct {
                uint32_t a;
                uint32_t b;
            } a;
            struct {
                char b[8];
            } b;
        } c;
    };

    struct test_anonymous {
        char magic[4];
        struct {
            uint32_t a;
            uint32_t b;
        };
        struct {
            char c[8];
        };
    };
    """

    state = cparser.parse_code(parser_def)
    intp = interpreter.Interpreter()
    intp.register(state)

    test_union = intp.getCType(state.structs["test_union"])
    assert ctypes.sizeof(test_union) == 12
    a = test_union.from_buffer_copy(b"ohaideadbeef")
    assert bytes(a.magic) == b"ohai"
    assert a.c.a.a.value == 0x64616564
    assert a.c.a.b.value == 0x66656562
    assert bytes(a.c.b.b) == b"deadbeef"
    assert bytes(a) == b"ohaideadbeef"

    test_anonymous = intp.getCType(state.structs["test_anonymous"])
    b = test_anonymous.from_buffer_copy(b"ohai\x39\x05\x00\x00\x28\x23\x00\x00deadbeef")
    assert bytes(b.magic) == b"ohai"
    assert b.a.value == 1337
    assert b.b.value == 9000
    assert bytes(b.c) == b"deadbeef"
    print("OK")


if __name__ == "__main__":
    demo_struct_and_enum()
    demo_unions_and_anonymous()
