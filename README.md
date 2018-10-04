PyCParser
=========
<https://github.com/albertz/PyCParser>

A **C** parser and interpreter written in Python. Also includes an automatic ctypes interface generator.

It is looser than the C grammar, i.e. it should support a superset of the C language in general.

Some of the support may a bit incomplete or wrong at this point because I didn't really strictly followed the language specs but rather improved the parser by iteration on real-world source code.

Similar projects
----------------

Parsers / `ctypes` interface generators:

* [Eli Bendersky's pycparser](https://github.com/eliben/pycparser).
 Complete C99 parser in pure Python.
 It depends on [Python Lex-Yacc (PLY)](http://www.dabeaz.com/ply/).
 (I didn't tested it yet. Seems to be the most complete and most professional project.
 If you don't want a C interpreter, this is probably the project you should use.)
* [pyclibrary](https://launchpad.net/pyclibrary) ([Github fork](https://github.com/albertz/pyclibrary)). Is quite slow and didn't worked that well for me.
* [ctypesgen](http://code.google.com/p/ctypesgen/). Also uses Lex+Yacc.
* [codegen](http://starship.python.net/crew/theller/ctypes/old/codegen.html). Uses GCC-XML. See below about the disadvantages of such an aproach.

Interpreters:

* [CInterpreter](https://github.com/SKantar/CInterpreter). Python.
* [CINT](http://root.cern.ch/drupal/content/cint). Not in Python. Probably the most famous one.
* [Ch](http://www.softintegration.com/). Not in Python. Is not really free.
* [ups debugger](http://ups.sourceforge.net/main.html). Not in Python.
* [PicoC](http://code.google.com/p/picoc/). Not in Python. "A very small C interpreter."

Why this project?
-----------------

* Be more flexible. It is much easier now with a hand-written parser to do operations on certain levels of the parsing pipe.
* I wanted to have some self-contained code which can also easily run on the end-user side. So the end-user can just update the lib and its headers and then some application using this Python lib will automatically use the updated lib. This is not possible if you generated the ctypes interface statically (via some GCC-XML based tool or so).
* I wanted to implement [PySDL](https://github.com/albertz/PySDL) and didn't wanted to translate the SDL headers by hand. Also, I didn't wanted to use existing tools to do this to avoid further maintaining work at some later time. See the project for further info.
* This functionality could be used similarly for many other C libraries.
* A challenge for myself. Just for fun. :)

Examples
--------

* [PySDL](https://github.com/albertz/PySDL). Also uses the automatic ctypes wrapper and maps it to a Python module.
* [PyCPython](https://github.com/albertz/PyCPython). Interpret CPython in Python.
* [PyLua](https://github.com/albertz/PyLua). Interpret Lua in Python.

Also see the *tests/test_interpreter.{c,py}* 'Hello world' example.

Current state
-------------

* I'm quite sure that function pointer typedefs are handled incorrectly. E.g. `typedef void f();` and `typedef void (*f)();` are just the same right now. See `cpre3_parse_typedef` and do some testing if you want to fix this.
* Many functions from the standard C library are still missing.
* There might be some bugs. :)
* C++ isn't supported yet. :)


--- Albert Zeyer, <http://www.az2000.de>

