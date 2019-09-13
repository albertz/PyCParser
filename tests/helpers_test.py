#!/usr/bin/env python3

from __future__ import print_function

import sys, os
my_dir = os.path.dirname(os.path.abspath(__file__))
base_dir = os.path.normpath(my_dir + "/..")
sys.path = [base_dir] + sys.path  # add at the very first entry to avoid problems which being a package

import better_exchook
better_exchook.install()
better_exchook.replace_traceback_format_tb()

import cparser
from pprint import pprint


def parse(testcode, withSystemMacros=True, withGlobalIncludeWrappers=False):
    state = cparser.State()
    if withSystemMacros: state.autoSetupSystemMacros()
    if withGlobalIncludeWrappers: state.autoSetupGlobalIncludeWrappers()
    cparser.parse_code(testcode, state)
    if state._errors:
        print("parsing errors:")
        pprint(state._errors)
        assert False, "there are parsing errors"
    return state


def main(mod):
    """
    :param dict[str] mod:
    """
    import unittest
    better_exchook.install()
    if len(sys.argv) <= 1:
        for k, v in sorted(mod.items()):
            if k.startswith("test_"):
                print("-" * 40)
                print("Executing: %s" % k)
                try:
                    v()
                except unittest.SkipTest as exc:
                    print("SkipTest:", exc)
                print("-" * 40)
        print("Finished all tests.")
    else:
        assert len(sys.argv) >= 2
        for arg in sys.argv[1:]:
            print("Executing: %s" % arg)
            if arg in mod:
                mod[arg]()  # assume function and execute
            else:
                eval(arg)  # assume Python code and execute
