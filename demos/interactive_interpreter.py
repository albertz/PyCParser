#!/usr/bin/env python3

"""
Interactive C parser & interpreter.
"""

import sys
import os
import better_exchook
from argparse import ArgumentParser

MyDir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(MyDir))

from cparser.interactive_interpreter import InteractiveInterpreter


def main():
    arg_parser = ArgumentParser()
    arg_parser.add_argument("--debug", action="store_true")
    args = arg_parser.parse_args()
    interactive_interpreter = InteractiveInterpreter(debug=args.debug)
    interactive_interpreter.loop()


if __name__ == '__main__':
    better_exchook.install()
    try:
        main()
    except KeyboardInterrupt:
        print("KeyboardInterrupt")
        sys.exit(1)
