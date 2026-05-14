
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


if __name__ == "__main__":
    helpers_test.main(globals())
