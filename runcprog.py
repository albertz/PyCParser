#!/usr/bin/env python

"""Run a program written in C

Any arguments prior to the first "--" should be c source code files,
one of which must contain a main() declaration which can have void or
int as a return value and no paramaters or standard C main()
variable arguments (int argc0, char **argv0)

Any arguments after the first -- are passed to the C main

A current limitation is that this must be run from the same directory that
any local includes #include "example.h" are relative. Generally this is the
same directory as the c source file.

When calling a main accepting arguments, the first c file provided will
be the first (index 0) argument.

Example, if you have example1.c, example1.h, example2.c, and example2.h
you can ./runcprog.py example1.c example2.c -- arg1 arg2
as long as your current working directory is the same as example1.c and
example2.c

If you want to include some c preprocessor defines or macros, just make a
.h file and make that your first argument.
"""

# Copyright (c) 2018, Mark Jenkins <mark@markjenkins.ca> www.markjenkins.ca

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

from sys import argv

import better_exchook
better_exchook.install()

from cparser import State, parse
from interpreter import Interpreter

def main():
    # excluding this programs name (argv[0]) and all arguments up to and
    # and excluding the first "--" are c files to include
    try:
        c_code_files = argv[1:argv.index("--")]
    except ValueError: # there might be no "--"
        c_code_files = argv[1:]

    if len(c_code_files) == 0:
        raise Exception("You must provide at least one C source file")

    state = State()
    state.autoSetupSystemMacros()
    state.autoSetupGlobalIncludeWrappers()
    interpreter = Interpreter()
    interpreter.register(state)

    for cfile in c_code_files:
        state = parse(cfile, state)

    main_func = interpreter.getFunc("main")
    if len(main_func.C_argTypes) == 0:
        return_code = interpreter.runFunc("main", return_as_ctype=False)
    else:
        # if the main() function doesn't have zero arguments, it
        # should have the standard two, (int argc0, char **argv0)
        assert(len(main_func.C_argTypes) == 2)

        # first c file is program name and first argument
        arguments_to_c_prog = [c_code_files[0]]
        try: # append everything after the "--" as c program arguments
            arguments_to_c_prog += argv[argv.index("--")+1:]
        except: ValueError

        # return_as_ctype=False as we're expecting a simple int or None for void
        return_code = interpreter.runFunc(
            "main",
            len(arguments_to_c_prog), arguments_to_c_prog,
            return_as_ctype=False)

    if isinstance(return_code, int):
        exit(return_code)

if __name__ == "__main__":
    main()
