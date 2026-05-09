
import os
import sys
import io
import argparse
import re
from typing import Optional

# Ensure tests/ is in sys.path so we can import cparser as a package from there
my_dir = os.path.dirname(os.path.abspath(__file__))
if my_dir not in sys.path:
    sys.path.insert(0, my_dir)

from cparser import interpreter
from cparser import globalincludewrappers
from cparser import cparser


base_dir = os.path.join(os.path.dirname(__file__), "c-testsuite/tests/single-exec")


def run_ctest(c_file: str, *, timeout: float = 10.0, debug_log_assign: bool = False, capture_stdout: bool = True) -> int:
    with open(c_file, "r") as f:
        code = f.read()

    state = cparser.State()
    state.autoSetupSystemMacros()
    # Pre-load all wrappers to handle tests that declare functions without including headers
    wrapper = globalincludewrappers.Wrapper(state)
    wrapper.install()
    wrapper.add_all_to_state(state)

    cparser.parse_code(code, state)

    interp = interpreter.Interpreter()
    interp.debug_log_assign = debug_log_assign
    interp.register(state)
    wrapper.interpreter = interp

    if "main" not in state.funcs:
        return 0

    main_func = state.funcs["main"]
    arg_count = 0
    if hasattr(main_func, "args"):
        arg_count = len(main_func.args)

    # Capture stdout
    old_stdout = sys.stdout
    if capture_stdout:
        sys.stdout = io.StringIO()
    try:
        if arg_count == 0:
            res = interp.runFunc("main", timeout=timeout)
        else:
            res = interp.runFunc("main", 1, ["./test", None], timeout=timeout)
    finally:
        if capture_stdout:
            output = sys.stdout.getvalue()
        else:
            output = None
        sys.stdout = old_stdout

    if hasattr(res, "value"):
        res = res.value
    if res is None:
        res = 0

    expected_file = c_file + ".expected"
    if capture_stdout and os.path.exists(expected_file):
        with open(expected_file, "r") as f:
            expected_output = f.read()
        if output.strip() != expected_output.strip():
            raise Exception(f"Output mismatch.\nExpected:\n{expected_output.strip()}\nGot:\n{output.strip()}")

    return res


def test_ctestsuite(*, limit: Optional[int] = None, summarize: bool = False, debug_log_assign: bool = False):
    if not os.path.exists(base_dir):
        raise Exception("c-testsuite not found at", base_dir)

    files = sorted([f for f in os.listdir(base_dir) if f.endswith(".c")])
    if limit:
        files = files[:limit]

    passed = 0
    failed = []

    for f in files:
        print(f"test: {f}")
        c_path = os.path.join(base_dir, f)
        try:
            res = run_ctest(c_path, debug_log_assign=debug_log_assign)
            if res == 0:
                passed += 1
            else:
                if summarize:
                    failed.append(f"{f} (rc {res})")
                else:
                    raise Exception(f"Test failed with rc {res}")
        except Exception as e:
            if summarize:
                failed.append(f"{f} (error: {e})")
            else:
                raise

    print(f"ctestsuite: {passed} passed, {len(failed)} failed")
    if failed:
        print("Failed tests:")
        for f_err in failed:
            print(f"  {f_err}")
        raise Exception("ctestsuite failed")


def _main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--limit", type=int, default=None)
    arg_parser.add_argument("--no-summarize", dest="summarize", action="store_false")
    arg_parser.add_argument("--debug-log-assign", action="store_true")
    arg_parser.add_argument("--no-capture-stdout", dest="capture_stdout", action="store_false")
    arg_parser.add_argument("--timeout", type=float, default=10.0, help="Timeout for each test in seconds.")
    arg_parser.add_argument("tests", nargs="*")
    arg_parser.set_defaults(summarize=True, capture_stdout=True, debug_log_assign=False)
    args = arg_parser.parse_args()
    if args.tests:
        for test in args.tests:
            test_path = _convert_user_test_name(test)
            print(f"Running test: {test_path}")
            res = run_ctest(
                test_path,
                debug_log_assign=args.debug_log_assign, capture_stdout=args.capture_stdout, timeout=args.timeout)
            print(f"Result: {res}")
            assert res == 0
    else:
        print("Running ctestsuite...")
        test_ctestsuite(summarize=args.summarize, limit=args.limit, debug_log_assign=args.debug_log_assign)


def _convert_user_test_name(name: str) -> str:
    if os.path.exists(name):
        return name
    if name.startswith("/"):
        return name
    if name.startswith("0") and name.endswith(".c"):
        return os.path.join(base_dir, name)
    if re.match(r"^\d+$", name):
        return os.path.join(base_dir, f"{name.zfill(5)}.c")
    raise ValueError(f"Unknown test name: {name!r}")


if __name__ == "__main__":
    _main()
