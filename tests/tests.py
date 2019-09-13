#!/usr/bin/env python3

import sys
import os
import helpers_test
import better_exchook
import importlib

my_dir = os.path.dirname(os.path.abspath(__file__))


def main():
    better_exchook.install()
    my_files = sorted(os.listdir(my_dir))
    for fn in my_files:
        if fn.startswith("test_") and fn.endswith(".py"):
            print("=" * 40)
            print("Python test file:", fn)
            mod = importlib.import_module(os.path.splitext(fn)[0])
            for name in dir(mod):
                if not name.startswith("test_"):
                    continue
                value = getattr(mod, name)
                if callable(value):
                    print("-" * 40)
                    print("Test:", name)
                    value()
                    print("-" * 40)
            print("=" * 40)


if __name__ == '__main__':
    main()
