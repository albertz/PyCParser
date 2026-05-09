
import os
import sys
import io
import argparse
from typing import Optional

# Ensure tests/ is in sys.path so we can import cparser as a package from there
my_dir = os.path.dirname(os.path.abspath(__file__))
if my_dir not in sys.path:
    sys.path.insert(0, my_dir)

from cparser import cparser
from cparser import interpreter
from cparser import globalincludewrappers


def run_ctest(c_file: str, *, timeout: float = 10.0):
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
    sys.stdout = io.StringIO()
    try:
        if arg_count == 0:
            res = interp.runFunc("main", timeout=timeout)
        else:
            res = interp.runFunc("main", 1, ["./test", None], timeout=timeout)
    finally:
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        
    if hasattr(res, "value"):
        res = res.value
    if res is None:
        res = 0
        
    expected_file = c_file + ".expected"
    if os.path.exists(expected_file):
        with open(expected_file, "r") as f:
            expected_output = f.read()
        if output.strip() != expected_output.strip():
            raise Exception(f"Output mismatch.\nExpected:\n{expected_output.strip()}\nGot:\n{output.strip()}")

    return res


def test_ctestsuite(*, limit: Optional[int] = None, summarize: bool = False):
    base_dir = os.path.join(os.path.dirname(__file__), "c-testsuite/tests/single-exec")
    if not os.path.exists(base_dir):
        print("c-testsuite not found at", base_dir)
        return

    files = sorted([f for f in os.listdir(base_dir) if f.endswith(".c")])
    if limit:
        files = files[:limit]
    
    passed = 0
    failed = []
    
    for f in files:
        if f == "00040.c": continue
        print(f"test: {f}")
        c_path = os.path.join(base_dir, f)
        try:
            res = run_ctest(c_path)
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
    arg_parser.set_defaults(summarize=True)
    args = arg_parser.parse_args()
    test_ctestsuite(summarize=args.summarize, limit=args.limit)


if __name__ == "__main__":
    _main()
