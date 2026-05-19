#!/usr/bin/env python3
"""
Test runner for cparser.

Default (no flags): preserves the historical verbose behaviour -- prints every
test as it runs, propagates the first exception (fail-fast).

`--summary`: catches per-test exceptions, prints only failures + a final
PASSED/FAILED summary, and exits non-zero on any failure.  Designed for
non-interactive use (e.g. by automation/agents) so the output is self-contained
and no shell piping is needed.

`--timeout N`: aborts any single test that runs longer than N seconds.  Useful
together with `--summary` for catching infinite loops.

`filter` (positional): substring; only tests whose `module.name` contains it
are run.

Implementation note: in --summary mode we redirect FD 1/2 (not just sys.stdout)
to a per-test temp file so that the per-test output is captured even from
forked subprocesses or C-level prints via ctypes.  Tests that fork and re-dup2
their own pipes to FD 1 (e.g. test_interpreter_helloworld) keep working
because the redirect only sets the *current* FD 1 mapping -- once the child
does its own dup2, it sees the pipe.
"""

import argparse
import importlib
import os
import signal
import sys
import tempfile
import traceback

my_dir = os.path.dirname(os.path.abspath(__file__))


class _TestTimeout(Exception):
    pass


def _alarm_handler(signum, frame):
    raise _TestTimeout("test exceeded timeout")


def _iter_tests():
    """Yield (mod_name, test_name, callable) for every test in this directory."""
    for fn in sorted(os.listdir(my_dir)):
        if not (fn.startswith("test_") and fn.endswith(".py")):
            continue
        if fn == "test_ctestsuite.py":
            continue
        mod_name = os.path.splitext(fn)[0]
        mod = importlib.import_module(mod_name)
        for name in dir(mod):
            if not name.startswith("test_"):
                continue
            value = getattr(mod, name)
            if callable(value):
                yield mod_name, name, value


def _run_one(value, timeout):
    """Run a single test callable, optionally under a SIGALRM-based timeout."""
    if timeout > 0:
        old = signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(timeout)
        try:
            value()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
    else:
        value()


def _run_one_captured(value, timeout, saved_stdout_fd, saved_stderr_fd):
    """Run a test with FD 1/2 redirected to a temp file.  Stores the captured
    text in `_run_one_captured.last_captured` (set both on success and on
    failure, so the caller can access it from an exception handler).
    Restores FDs even on exceptions."""
    _run_one_captured.last_captured = ""
    tmp = tempfile.TemporaryFile()
    sys.stdout.flush()
    sys.stderr.flush()
    os.dup2(tmp.fileno(), 1)
    os.dup2(tmp.fileno(), 2)
    try:
        _run_one(value, timeout)
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved_stdout_fd, 1)
        os.dup2(saved_stderr_fd, 2)
        try:
            tmp.seek(0)
            _run_one_captured.last_captured = tmp.read().decode("utf-8", "replace")
        finally:
            tmp.close()


_run_one_captured.last_captured = ""


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--summary", action="store_true",
                   help="Quiet output; catch exceptions; print a final summary; "
                        "exit non-zero on any failure.")
    p.add_argument("--timeout", type=int, default=0,
                   help="Per-test timeout in seconds (0 = none, default).")
    p.add_argument("filter", nargs="?", default=None,
                   help="Optional substring; only tests whose 'mod.name' "
                        "contains this string are run.")
    args = p.parse_args(argv)

    # Pretty tracebacks only in verbose mode -- in summary mode we capture
    # exceptions ourselves so the default hook is fine.
    if not args.summary:
        import better_exchook
        better_exchook.install()

    passed = 0
    failed = []  # list[(mod, name, err_one_line, captured_str)]
    last_file = None
    selected = 0

    # For summary mode: dup the real stdout/stderr so we can write progress
    # dots and the final summary regardless of the per-test redirection.
    if args.summary:
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
        progress = os.fdopen(saved_stdout_fd, "w", buffering=1)
    else:
        saved_stdout_fd = saved_stderr_fd = -1
        progress = None

    try:
        for mod_name, name, value in _iter_tests():
            full = "%s.%s" % (mod_name, name)
            if args.filter and args.filter not in full:
                continue
            selected += 1

            if not args.summary:
                if mod_name != last_file:
                    if last_file is not None:
                        print("=" * 40)
                    print("=" * 40)
                    print("Python test file:", mod_name + ".py")
                    last_file = mod_name
                print("-" * 40)
                print("Test:", mod_name, ".", name)

            if args.summary:
                try:
                    _run_one_captured(value, args.timeout,
                                      saved_stdout_fd, saved_stderr_fd)
                except _TestTimeout:
                    failed.append((mod_name, name,
                                   "timeout after %ds" % args.timeout,
                                   _run_one_captured.last_captured))
                    progress.write("T")
                except BaseException as e:
                    # Build a traceback string manually -- traceback.format_exc()
                    # can hit incompatibility issues when better_exchook is
                    # imported indirectly by some test module.
                    tb = "".join(traceback.format_exception(
                        type(e), e, e.__traceback__))
                    failed.append((mod_name, name,
                                   "%s: %s" % (type(e).__name__, e),
                                   _run_one_captured.last_captured + "\n" + tb))
                    progress.write("F")
                else:
                    passed += 1
                    progress.write(".")
            else:
                _run_one(value, args.timeout)
                passed += 1
                print("-" * 40)

        if not args.summary and last_file is not None:
            print("=" * 40)

        if args.summary:
            progress.write("\n")
            progress.write("=" * 60 + "\n")
            if failed:
                progress.write("FAILED TESTS (%d):\n" % len(failed))
                for mod_name, name, err, captured in failed:
                    progress.write("-" * 60 + "\n")
                    progress.write("  %s.%s\n" % (mod_name, name))
                    progress.write("    %s\n" % err)
                    if captured:
                        lines = captured.rstrip().splitlines()
                        if len(lines) > 40:
                            progress.write("    ... (%d earlier lines elided)\n" %
                                           (len(lines) - 40))
                            lines = lines[-40:]
                        for ln in lines:
                            progress.write("    " + ln + "\n")
                progress.write("-" * 60 + "\n")
            progress.write("SUMMARY: %d run, %d passed, %d failed\n" % (
                selected, passed, len(failed)))
            progress.write("=" * 60 + "\n")
            progress.flush()
            return 1 if failed else 0

        return 0
    finally:
        if progress is not None:
            progress.flush()
            # Note: closing `progress` would also close the dup'd fd.  We let
            # process exit handle cleanup since we may be in a finally during
            # an unwind.


if __name__ == '__main__':
    sys.exit(main())
