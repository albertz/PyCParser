PyCParser
=========
<https://github.com/albertz/PyCParser>

A **C** parser written in Python. Also includes an automatic ctypes interface generator.

It is looser than the C grammar, i.e. it should support a superset of the C language in general.

Some of the support may a bit incomplete or wrong at this point because I didn't really strictly followed the language specs but rather improved the parser by iteration on real-world source code.

Similar projects
----------------

* [pyclibrary](https://launchpad.net/pyclibrary) ([Github fork](https://github.com/albertz/pyclibrary)). Is quite slow and didn't worked that well for me.
* The equally named [pycparser](http://code.google.com/p/pycparser/). It depends on [Python Lex-Yacc](http://www.dabeaz.com/ply/). (I didn't really tested it yet.)
* [ctypesgen](http://code.google.com/p/ctypesgen/). Also uses Lex+Yacc.
* [codegen](http://starship.python.net/crew/theller/ctypes/old/codegen.html). Uses GCC-XML. See below about the disadvantages of such an aproach.

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

Parsed without (fatal) errors but not much checked otherwise:

* `zlib.h`, `readline.h`, `Python.h`

TODOs / further directions
--------------------------

* I'm quite sure that function pointer typedefs are handled incorrectly. E.g. `typedef void f();` and `typedef void (*f)();` are just the same right now. See `cpre3_parse_typedef` and do some testing if you want to fix this.
* More testing.
* Complete C support. Right now, most of the stuff in the function body is not really supported, i.e. function calls, expressions, if/while/for/etc control structure, and so on. Only very simple statements can be evaluated so far and it completely ignores operator priority right now. Operator priority is also ignored for C preprocessor expressions. 
* With complete C support, it is not so difficult anymore to write a C interpreter.
* Maybe C++ support. :)

--- Albert Zeyer, <http://www.az2000.de>

