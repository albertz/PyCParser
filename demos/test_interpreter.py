#!/usr/bin/env python3

"""
Test interpreter
by Albert Zeyer, 2011
code under BSD 2-Clause License
"""

from __future__ import print_function

import sys
import os

import better_exchook
better_exchook.install()

import cparser

def prepareState():
    state = cparser.State()
    state.autoSetupSystemMacros()
    state.autoSetupGlobalIncludeWrappers()
    return state

MyDir = os.path.dirname(__file__)

state = prepareState()
cparser.parse(MyDir + "/test_interpreter.c", state)

from cparser import interpreter

interpreter = interpreter.Interpreter()
interpreter.register(state)


if __name__ == '__main__':
    print("errors so far:")
    for m in state._errors:
        print(m)

    for f in state.contentlist:
        if not isinstance(f, cparser.CFunc): continue
        if not f.body: continue

        print()
        print("parsed content of " + str(f) + ":")
        for c in f.body.contentlist:
            print(c)

    print()
    print("PyAST of main:")
    interpreter.dumpFunc("main")

    print()
    print()
    interpreter.runFunc("main", len(sys.argv), sys.argv + [None])
