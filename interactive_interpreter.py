
from typing import Optional
import sys
import better_exchook
import cparser
from . import interpreter as _interpreter


class InteractiveInterpreter:
    def __init__(
        self, *,
        debug: bool = False,
        state: Optional[cparser.State] = None,
        interpreter: Optional[_interpreter.Interpreter] = None,
    ):
        self.debug = debug
        if state is not None:
            self.state = state
        else:
            self.state = cparser.State()
            self.state.autoSetupSystemMacros()
            self.state.autoSetupGlobalIncludeWrappers()
        self.state.readLocalInclude = self._read_local_include_handler
        if interpreter is not None:
            self.interp = interpreter
        else:
            self.interp = _interpreter.Interpreter()
            self.interp.register(self.state)

    def _read_local_include_handler(self, fn):
        """
        :param str fn:
        :return: iterator over chars, filename
        :rtype: (typing.Iterable[str],str|None)
        """
        if fn == "<input>":
            reader = self._input_reader_handler()
            return reader, None
        return cparser.State.readLocalInclude(self.state, fn)

    def _input_reader_handler(self):
        """
        :param cparser.State state:
        :return: yields chars
        :rtype: typing.Generator[str]
        """
        state = self.state
        old_err_num = len(state._errors)
        old_content_list_num = len(state.contentlist)

        while True:
            try:
                line = input(">>> ")
            except EOFError:
                break
            for c in line + "\n":
                yield c
            for m in state._errors[old_err_num:]:
                print("Error:", m)
            old_err_num = len(state._errors)
            for m in state.contentlist[old_content_list_num:]:
                if self.debug:
                    print("Parsed:", m)
                if isinstance(m, (cparser.CStatement, cparser.CControlStructureBase)):
                    try:
                        res = self.interp.runSingleStatement(m, dump=self.debug)
                        print(res)
                    except Exception as exc:
                        print("Interpreter exception:", type(exc).__name__, ":", exc)
                        if self.debug:
                            better_exchook.better_exchook(*sys.exc_info())

            old_content_list_num = len(state.contentlist)

    def loop(self):
        cparser.parse("<input>", self.state)
