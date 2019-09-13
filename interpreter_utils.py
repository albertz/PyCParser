
import sys
import ast
import inspect


def _arg_name(name):
    """
    :param str name:
    :return:
    """
    if sys.version_info[0] == 2:
        return ast.Name(id=name, ctx=ast.Param())
    return ast.arg(arg=name, annotation=None)


def _ast_bin_op_to_ast_expression(op):
    if inspect.isclass(op):
        op = op()
    assert isinstance(op, ast.operator)
    l = ast.Lambda()
    a = l.args = ast.arguments()
    a.args = [_arg_name("a"), _arg_name("b")]
    a.vararg = None
    a.kwarg = None
    a.defaults = []
    if sys.version_info[0] >= 3:
        a.kwonlyargs = []
        a.kw_defaults = []
    t = l.body = ast.BinOp()
    t.left = ast.Name(id="a", ctx=ast.Load())
    t.right = ast.Name(id="b", ctx=ast.Load())
    t.op = op
    expr = ast.Expression(body=l)
    return expr


def compile_expr_to_code(expr):
    ast.fix_missing_locations(expr)
    code = compile(expr, "<_astOpToFunc>", "eval")
    return code


def ast_bin_op_to_func(op):
    expr = _ast_bin_op_to_ast_expression(op)
    code = compile_expr_to_code(expr)
    f = eval(code)
    return f
