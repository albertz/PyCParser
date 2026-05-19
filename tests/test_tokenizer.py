
from __future__ import print_function

import helpers_test
import cparser
from cparser import *
from helpers_test import assert_equal

# Use helpers_test.parse explicitly to avoid clash with cparser.parse
_parse = helpers_test.parse


# ---------------------------------------------------------------------------
# CWideStr: L"..." wide string literals
# ---------------------------------------------------------------------------

def test_wchar_string_literal_token():
    """L"..." should tokenize to a CWideStr token."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, 'L"hello"'))
    wide = [t for t in tokens if isinstance(t, CWideStr)]
    assert len(wide) == 1, "expected one CWideStr token, got: %r" % tokens
    assert_equal(wide[0].content, "hello")


def test_wchar_string_literal_escape():
    """Escape sequences inside L\"...\" should be handled."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, r'L"hello\nworld"'))
    wide = [t for t in tokens if isinstance(t, CWideStr)]
    assert len(wide) == 1
    assert "\n" in wide[0].content


def test_string_literal_hex_and_unicode_escapes():
    """Hex and unicode escapes inside string literals should be decoded."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, r'"A\x42\u0043\U00000044"'))
    strs = [t for t in tokens if isinstance(t, CStr)]
    assert len(strs) == 1, "expected one CStr token, got: %r" % tokens
    assert_equal(strs[0].content, "ABCD")


def test_wchar_string_literal_not_regular_str():
    """L"..." must produce CWideStr, not the plain CStr."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, 'L"abc"'))
    for t in tokens:
        if isinstance(t, CWideStr):
            break
    else:
        assert False, "no CWideStr token found in %r" % tokens
    # must NOT be emitted as plain CStr
    assert not any(isinstance(t, CStr) and not isinstance(t, CWideStr) for t in tokens)


def test_wchar_string_literal_no_L_macro():
    """The old 'L=""' macro hack must be gone; L on its own is an identifier."""
    state = State()
    state.autoSetupSystemMacros()
    # If the old macro were still present, L"..." would expand to "" + "..." = "..."
    # and produce a plain CStr.  With the fix it must be CWideStr.
    tokens = list(cpre2_parse(state, 'L"test"'))
    assert any(isinstance(t, CWideStr) for t in tokens), \
        "expected CWideStr, got: %r" % tokens
    assert "L" not in state.macros, "L macro should not exist"


# ---------------------------------------------------------------------------
# L'...' wchar char literals
# ---------------------------------------------------------------------------

def test_wchar_char_literal_token():
    """L'x' should tokenize to a CChar token (treated like a regular char)."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, "L'A'"))
    chars = [t for t in tokens if isinstance(t, CChar)]
    assert len(chars) == 1, "expected one CChar token, got: %r" % tokens
    assert_equal(chars[0].content, ord('A'))


def test_wchar_char_literal_escape():
    """L'\\n' should produce CChar with the newline code point."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, r"L'\n'"))
    chars = [t for t in tokens if isinstance(t, CChar)]
    assert len(chars) == 1, "expected one CChar token, got: %r" % tokens
    assert_equal(chars[0].content, ord('\n'))


def test_char_literal_octal_and_hex_escapes():
    """Octal and hex escapes inside char literals should be decoded."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, r"'\7' '\x7f'"))
    chars = [t for t in tokens if isinstance(t, CChar)]
    assert len(chars) == 2, "expected two CChar tokens, got: %r" % tokens
    assert_equal([c.content for c in chars], [7, 127])


# ---------------------------------------------------------------------------
# cpre2_parse_number: float and scientific-notation literals
# ---------------------------------------------------------------------------

def test_number_scientific_notation():
    """1e5 should parse as the float 100000.0, not raise an error."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, "float v = 1e5;"))
    assert not state._errors, "unexpected errors: %r" % state._errors
    nums = [t for t in tokens if isinstance(t, CNumber)]
    assert any(abs(t.content - 1e5) < 1 for t in nums), \
        "expected 1e5 in tokens, got: %r" % nums


def test_number_scientific_notation_with_suffix():
    """1e5f should parse as the float 100000.0 (suffix stripped)."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, "float v = 1e5f;"))
    assert not state._errors, "unexpected errors: %r" % state._errors
    nums = [t for t in tokens if isinstance(t, CNumber)]
    assert any(isinstance(t.content, float) for t in nums), \
        "expected a float CNumber, got: %r" % nums


def test_number_scientific_notation_negative_exponent():
    """1e-6 should parse as the float 1e-6 without errors."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, "double v = 1e-6;"))
    assert not state._errors, "unexpected errors: %r" % state._errors
    nums = [t for t in tokens if isinstance(t, CNumber)]
    assert any(isinstance(t.content, float) and abs(t.content - 1e-6) < 1e-15
               for t in nums), "expected 1e-6 in tokens, got: %r" % nums


def test_number_integer_with_UL_suffix():
    """42UL should parse as integer 42 without errors."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, "int v = 42UL;"))
    assert not state._errors, "unexpected errors: %r" % state._errors
    nums = [t for t in tokens if isinstance(t, CNumber)]
    assert any(t.content == 42 for t in nums), "expected 42, got: %r" % nums


def test_float_literal_with_exponent_in_initializer():
    """`{0.0e0,}` must parse correctly as a single float 0.0.

    The cpre2 tokenizer splits float-with-fraction-and-exponent literals
    into a 3-token sequence [int, ".", int-or-float], and the expression
    parser must glue them back together using the original lexemes (not
    the parsed values), otherwise a right-hand side like "0e0" gets
    string-concatenated as "0.0.0" and the parse blows up.  This is the
    pattern used in CPython's Objects/longobject.c (`log_base_BASE[37] =
    {0.0e0,};`).
    """
    import cparser as _cparser
    state = State()
    state.autoSetupSystemMacros()
    _cparser.parse_code(
        "double v[1] = {0.0e0,};\n"
        "double w[1] = {1.5e-3,};\n",
        state)
    assert not state._errors, "unexpected errors: %r" % state._errors


def test_float_literal_with_f_suffix():
    """`1.0f` (C float-suffix) must parse without choking."""
    import cparser as _cparser
    state = State()
    state.autoSetupSystemMacros()
    _cparser.parse_code(
        "float v = 1.0f;\n"
        "float w = 2.5e1f;\n",
        state)
    assert not state._errors, "unexpected errors: %r" % state._errors


# ---------------------------------------------------------------------------
# __func__: CFuncName sentinel token
# ---------------------------------------------------------------------------

def test_func_identifier_token():
    """__func__ should tokenize to a CFuncName sentinel token (subclass of CStr)."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, "__func__;"))
    func_name_tokens = [t for t in tokens if isinstance(t, CFuncName)]
    assert len(func_name_tokens) == 1, \
        "expected one CFuncName token for __func__, got: %r" % tokens


# ---------------------------------------------------------------------------
# Macro appearing multiple times in the same expression (anti-recursion blacklist)
# ---------------------------------------------------------------------------

def test_macro_used_twice_in_same_expression():
    """A macro appearing twice in the same expression must be expanded both times.

    When a macro like SST expands to another macro (SIZEOF_SIZE_T → 8),
    the anti-recursion blacklist must be cleared once the first expansion is
    done, so the second occurrence is expanded correctly.
    """
    state = State()
    state.autoSetupSystemMacros()
    state.macros["SIZEOF_SIZE_T"] = cparser.Macro(rightside="8")
    state.macros["SST"] = cparser.Macro(rightside="SIZEOF_SIZE_T")
    tokens = list(cpre2_parse(state, "f(SST-1, SST-1)"))
    nums = [t for t in tokens if isinstance(t, CNumber)]
    assert len([n for n in nums if n.content == 8]) == 2, \
        "expected two '8' tokens (one per SST), got: %r" % nums


def test_char_literal_ascode_single_quote():
    """CChar containing a single-quote must round-trip through asCCode."""
    state = State()
    state.autoSetupSystemMacros()
    # '\'' is the C char literal for the single-quote character (ASCII 39).
    tokens = list(cpre2_parse(state, r"char c = '\''"))
    chars = [t for t in tokens if isinstance(t, CChar)]
    assert len(chars) == 1, "expected one CChar token, got: %r" % tokens
    assert_equal(chars[0].content, ord("'"))
    # Round-trip: asCCode() must produce valid C that re-tokenises to the same value.
    roundtrip = list(cpre2_parse(state, chars[0].asCCode()))
    rt_chars = [t for t in roundtrip if isinstance(t, CChar)]
    assert len(rt_chars) == 1, "asCCode round-trip gave: %r" % roundtrip
    assert_equal(rt_chars[0].content, ord("'"))


def test_char_literal_ascode_backslash():
    """CChar containing a backslash must round-trip through asCCode."""
    state = State()
    state.autoSetupSystemMacros()
    tokens = list(cpre2_parse(state, r"char c = '\\'"))
    chars = [t for t in tokens if isinstance(t, CChar)]
    assert len(chars) == 1, "expected one CChar token, got: %r" % tokens
    assert_equal(chars[0].content, ord("\\"))
    roundtrip = list(cpre2_parse(state, chars[0].asCCode()))
    rt_chars = [t for t in roundtrip if isinstance(t, CChar)]
    assert len(rt_chars) == 1, "asCCode round-trip gave: %r" % roundtrip
    assert_equal(rt_chars[0].content, ord("\\"))


def test_macro_expansion_with_char_literal_arg():
    """A macro called with a '\\'' or '\\\\' arg must expand and re-tokenise correctly.

    Before the fix, CChar.asCCode() produced bare ''' for a single-quote arg,
    which the tokeniser read as an empty char literal followed by a stray quote.
    """
    state = State()
    state.autoSetupSystemMacros()
    state.macros["IDENTITY"] = cparser.Macro(args=("x",), rightside="(x)")
    for raw_arg, expected_ord in [(r"'\''", ord("'")), (r"'\\'", ord("\\"))]:
        # The trailing ';' gives cpre2_parse the lookahead character it needs to
        # trigger macro finalisation (state 32) before end-of-input.
        tokens = list(cpre2_parse(state, "IDENTITY(%s);" % raw_arg))
        chars = [t for t in tokens if isinstance(t, CChar)]
        assert len(chars) == 1, \
            "IDENTITY(%s) expanded to %r, expected one CChar" % (raw_arg, tokens)
        assert_equal(chars[0].content, expected_ord)


if __name__ == "__main__":
    helpers_test.main(globals())
