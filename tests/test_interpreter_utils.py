#!/usr/bin/env python3

from __future__ import print_function

from helpers_test import main
import interpreter_utils
from interpreter_utils import *
import ast
import inspect
from py_demo_unparse import Unparser


def test_ast_bin_op_to_ast_expression():
    op = ast.Add
    expr = interpreter_utils._ast_bin_op_to_ast_expression(op)
    print("Dump:")
    print(ast.dump(expr))
    print("Unparse:")
    Unparser(expr)
    print()
    code = compile_expr_to_code(expr)
    f = eval(code)
    assert callable(f)
    y = f(5, 7)
    assert y == 12


def test_ast_bin_op_to_func_add():
    op = ast.Add
    f = ast_bin_op_to_func(op)
    y = f(5, 7)
    assert y == 12


if __name__ == "__main__":
    main(globals())
