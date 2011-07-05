PyCParser
=========
<https://github.com/albertz/PyCParser>

A **C** parser written in Python. Also includes an automatic ctypes interface generator.

It is a bit loosely on the C grammer, i.e. it should support a superset of the C language in general.

Some of the support may a bit incomplete or wrong at this point because I didn't really strictly followed the language specs but rather improved the parser by iteration on real-world source code.

Similar projects
----------------

* [pyclibrary](https://launchpad.net/pyclibrary) ([Github fork](https://github.com/albertz/pyclibrary)). Is quite slow and didn't worked that well for me.

Why this project?
-----------------

* Be more flexible. It is much easier now with a hand-written parser to do operations on certain levels of the parsing pipe.
* I wanted to implement [PySDL](https://github.com/albertz/PySDL) and didn't wanted to translate the SDL headers by hand. Also, I didn't wanted to use existing tools to do this to avoid further maintaining work at some later time. See the project for further info.
* This functionality could be used similarly for many other C libraries.
* A challenge for myself. Just for fun. :)

Samples
-------

* [PySDL](https://github.com/albertz/PySDL).

TODOs / further directions
--------------------------

* More testing.
* Complete C support. Right now, most of the stuff in the function body is not really supported, i.e. function calls, expressions, if/while/for/etc control structure, and so on. Only very simple statements can be evaluated so far and it completely ignores operator priority right now. 
* With complete C support, it is not so difficult anymore to write a C interpreter.
* Maybe C++ support. :)

--- Albert Zeyer, <http://www.az2000.de>

