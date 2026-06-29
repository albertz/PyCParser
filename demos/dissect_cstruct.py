"""
https://github.com/fox-it/dissect.cstruct
"""

import cparser
from cparser import interpreter


def main():
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


if __name__ == "__main__":
    main()
