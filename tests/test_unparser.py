#!/usr/bin/env python3

from __future__ import print_function

from helpers_test import main
import ast
import inspect
from py_demo_unparse import Unparser


def test_Unparser():
    expr = compile("lambda a, b: a + b", "<eval>", "eval", ast.PyCF_ONLY_AST)
    print("Dump:")
    print(ast.dump(expr))
    print("Unparse:")
    Unparser(expr)
    print()


if __name__ == "__main__":
    main(globals())
