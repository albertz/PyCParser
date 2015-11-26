
import sys
import cparser, helpers_test
import better_exchook


def test_interpreter_helloworld():
	testcode = """
	#include <stdio.h>

	int main(int argc, char** argv) {
		printf("Hello %s\n", "world");
		printf("args: %i\n", argc);
		int i;
		for(i = 0; i < argc; ++i)
			printf("%s\n", argv[i]);
	}
	"""

	state = helpers_test.parse(testcode, withGlobalIncludeWrappers=True)

	import interpreter
	interp = interpreter.Interpreter()
	interp.register(state)

	def dump():
		for f in state.contentlist:
			if not isinstance(f, cparser.CFunc): continue
			if not f.body: continue

			print
			print "parsed content of " + str(f) + ":"
			for c in f.body.contentlist:
				print c

		print
		print "PyAST of main:"
		interp.dumpFunc("main")

	#interpreter.runFunc("main", len(sys.argv), sys.argv + [None])

	import os
	# os.pipe() returns pipein,pipeout
	pipes = os.pipe(), os.pipe() # for stdin/stdout+stderr

	if os.fork() == 0: # child
		os.close(pipes[0][1])
		os.close(pipes[1][0])
		os.dup2(pipes[0][0], sys.__stdin__.fileno())
		os.dup2(pipes[1][1], sys.__stdout__.fileno())
		os.dup2(pipes[1][1], sys.__stderr__.fileno())

		try:
			interp.runFunc("main", 2, ["./test", "abc", None])
		except BaseException:
			better_exchook.better_exchook(*sys.exc_info())

		os._exit(0)
		return

	# parent
	os.close(pipes[0][0])
	os.close(pipes[1][1])
	child_stdout = os.fdopen(pipes[1][0])
	child_stdout = child_stdout.readlines()

	expected_out = [
		"Hello world\n",
		"args: 2\n",
		"./test\n",
		"abc\n",
	]

	if expected_out != child_stdout:
		print "Got output:"
		print "".join(child_stdout)
		dump()
		assert False

