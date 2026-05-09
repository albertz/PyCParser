
import os
import sys

# Ensure tests/ is in sys.path so we can import cparser as a package from there
my_dir = os.path.dirname(os.path.abspath(__file__))
if my_dir not in sys.path:
    sys.path.insert(0, my_dir)

import helpers_test
from cparser import interpreter
from cparser import globalincludewrappers
import better_exchook
import ctypes
import io

def run_ctest(c_file):
    with open(c_file, "r") as f:
        code = f.read()
    
    from cparser import cparser
    
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
            res = interp.runFunc("main")
        else:
            res = interp.runFunc("main", 1, ["./test", None])
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

def test_ctestsuite(limit=20):
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
        c_path = os.path.join(base_dir, f)
        try:
            res = run_ctest(c_path)
            if res == 0:
                passed += 1
            else:
                failed.append(f"{f} (rc {res})")
        except Exception as e:
            failed.append(f"{f} (error: {e})")
            
    print(f"ctestsuite: {passed} passed, {len(failed)} failed")
    if failed:
        print("Failed tests:")
        for f_err in failed:
            print(f"  {f_err}")

if __name__ == "__main__":
    test_ctestsuite(limit=None)
