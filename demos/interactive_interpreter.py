#!/usr/bin/env python3

"""
Interactive C parser & interpreter.
"""

from __future__ import print_function

import sys
import os
import typing
import readline
import better_exchook

MyDir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(MyDir))

import cparser


def input_reader_handler(state):
    """
    :param cparser.State state:
    :return: yields chars
    :rtype: typing.Generator[str]
    """
    old_err_num = len(state._errors)
    old_content_list_num = len(state.contentlist)

    while True:
        try:
            line = input(">>> ")
        except EOFError:
            break
        for c in line + "\n":
            yield c
        for m in state._errors[old_err_num:]:
            print("Error:", m)
        old_err_num = len(state._errors)
        for m in state.contentlist[old_content_list_num:]:
            print("Parsed:", m)
        old_content_list_num = len(state.contentlist)


def prepare_state():
    """
    :rtype: cparser.State
    """
    state = cparser.State()
    state.autoSetupSystemMacros()
    state.autoSetupGlobalIncludeWrappers()

    def read_include(fn):
        """
        :param str fn:
        :return: iterator over chars, filename
        :rtype: (typing.Iterable[str],str|None)
        """
        if fn == "<input>":
            reader = input_reader_handler(state)
            return reader, None
        return cparser.State.readLocalInclude(state, fn)

    state.readLocalInclude = read_include
    return state


def main():
    state = prepare_state()
    cparser.parse("<input>", state)


if __name__ == '__main__':
    better_exchook.install()
    main()
