
import helpers_test
import sys
import cparser
import better_exchook

PY3 = sys.version_info[0] >= 3


def test_interpreter_helloworld():
    testcode = """
    #include <stdio.h>
    
    int main(int argc, char** argv) {
        printf("Hello %s\n", "world");
        printf("args: %i\n", argc);
        int i;
        for(i = 0; i < argc; ++i)
            printf("%s\n", argv[i]);
        fflush(stdout);
    }
    """

    state = helpers_test.parse(testcode, withGlobalIncludeWrappers=True)

    from cparser import interpreter
    interp = interpreter.Interpreter()
    interp.register(state)

    def dump():
        for f in state.contentlist:
            if not isinstance(f, cparser.CFunc): continue
            if not f.body: continue

            print()
            print("parsed content of " + str(f) + ":")
            for c in f.body.contentlist:
                print(c)

        print()
        print("PyAST of main:")
        interp.dumpFunc("main")

    #interpreter.runFunc("main", len(sys.argv), sys.argv + [None])

    import os
    # os.pipe() returns pipein,pipeout
    pipes = os.pipe(), os.pipe()  # for stdin/stdout+stderr
    if hasattr(os, "set_inheritable"):
        # Python 3 by default will close all fds in subprocesses. This will avoid that.
        os.set_inheritable(pipes[0][0], True)
        os.set_inheritable(pipes[0][1], True)
        os.set_inheritable(pipes[1][0], True)
        os.set_inheritable(pipes[1][1], True)

    pid = os.fork()
    if pid == 0:  # child
        os.close(pipes[0][1])
        os.close(pipes[1][0])
        os.dup2(pipes[0][0], sys.__stdin__.fileno())
        os.dup2(pipes[1][1], sys.__stdout__.fileno())
        os.dup2(pipes[1][1], sys.__stderr__.fileno())

        try:
            interp.runFunc("main", 2, ["./test", "abc", None])
        except SystemExit:
            raise
        except BaseException:
            better_exchook.better_exchook(*sys.exc_info())

        print("Normal exit.")
        os._exit(0)
        return

    # parent
    os.close(pipes[0][0])
    os.close(pipes[1][1])
    child_stdout = os.fdopen(pipes[1][0], "rb", 0)
    child_stdout = child_stdout.readlines()
    if PY3:
        child_stdout = [l.decode("utf8") for l in child_stdout]

    expected_out = [
        "Hello world\n",
        "args: 2\n",
        "./test\n",
        "abc\n",
        "Normal exit.\n",
    ]

    if expected_out != child_stdout:
        print("Got output:")
        print("".join(child_stdout))
        dump()

        print("run directly here now:")
        interp.runFunc("main", 2, ["./test", "abc", None])

        raise Exception("child stdout %r" % (child_stdout,))


if __name__ == '__main__':
    helpers_test.main(globals())
