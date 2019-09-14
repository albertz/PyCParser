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
from argparse import ArgumentParser

MyDir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(MyDir))

import cparser
import interpreter


class InteractiveInterpreter:
    def __init__(self, debug=False):
        """
        :param bool debug:
        """
        self.debug = debug
        self.state = cparser.State()
        self.state.autoSetupSystemMacros()
        self.state.autoSetupGlobalIncludeWrappers()
        self.state.readLocalInclude = self._read_local_include_handler
        self.interp = interpreter.Interpreter()
        self.interp.register(self.state)

    def _read_local_include_handler(self, fn):
        """
        :param str fn:
        :return: iterator over chars, filename
        :rtype: (typing.Iterable[str],str|None)
        """
        if fn == "<input>":
            reader = self._input_reader_handler()
            return reader, None
        return cparser.State.readLocalInclude(self.state, fn)

    def _input_reader_handler(self):
        """
        :param cparser.State state:
        :return: yields chars
        :rtype: typing.Generator[str]
        """
        state = self.state
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
                if self.debug:
                    print("Parsed:", m)
                if isinstance(m, (cparser.CStatement, cparser._CControlStructure)):
                    try:
                        res = self.interp.runSingleStatement(m, dump=self.debug)
                        print(res)
                    except Exception as exc:
                        print("Interpreter exception:", type(exc).__name__, ":", exc)
                        if self.debug:
                            better_exchook.better_exchook(*sys.exc_info())

            old_content_list_num = len(state.contentlist)

    def loop(self):
        cparser.parse("<input>", self.state)


def main():
    arg_parser = ArgumentParser()
    arg_parser.add_argument("--debug", action="store_true")
    args = arg_parser.parse_args()
    interactive_interpreter = InteractiveInterpreter(
        debug=args.debug)
    interactive_interpreter.loop()


if __name__ == '__main__':
    better_exchook.install()
    try:
        main()
    except KeyboardInterrupt:
        print("KeyboardInterrupt")
        sys.exit(1)
