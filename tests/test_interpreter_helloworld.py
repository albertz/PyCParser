import sys
sys.path += [".."]
from pprint import pprint
import cparser, test

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

state = test.parse(testcode, withGlobalIncludeWrappers=True)


import interpreter
interpreter = interpreter.Interpreter()
interpreter.register(state)
interpreter.registerFinalize()

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
	interpreter.dumpFunc("main")
	
#interpreter.runFunc("main", len(sys.argv), sys.argv + [None])

import os
# os.pipe() returns pipein,pipeout
pipes = os.pipe(), os.pipe() # for stdin/stdout+stderr

if os.fork() == 0: # child
	os.close(pipes[0][1])
	os.close(pipes[1][0])
	os.dup2(pipes[0][0], sys.stdin.fileno())
	os.dup2(pipes[1][1], sys.stdout.fileno())
	os.dup2(pipes[1][1], sys.stderr.fileno())
	
	interpreter.runFunc("main", 2, ["./test", "abc", None])
	
	sys.exit(0)
	
else: # parent
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

assert expected_out == child_stdout

