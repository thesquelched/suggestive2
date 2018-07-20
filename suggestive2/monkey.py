import urwid


# See: https://github.com/urwid/urwid/pull/283
def _exception_handler(self, loop, context):
    exc = context.get('exception')
    if exc:
        loop.stop()
        if not isinstance(exc, urwid.ExitMainLoop):
            # Store the exc_info so we can re-raise after the loop stops
            import sys
            self._exc_info = sys.exc_info()
            if self._exc_info == (None, None, None):
                self._exc_info = (type(exc), exc, None)
    else:
        loop.default_exception_handler(context)


_orig_keypress_max_left = urwid.ListBox._keypress_max_left
_orig_keypress_max_right = urwid.ListBox._keypress_max_right


# See: https://github.com/urwid/urwid/issues/305
def _keypress_max_left(self):
    _orig_keypress_max_left(self)


# See: https://github.com/urwid/urwid/issues/305
def _keypress_max_right(self):
    _orig_keypress_max_right(self)


def monkeypatch():
    urwid.AsyncioEventLoop._exception_handler = _exception_handler
    urwid.ListBox._keypress_max_left = _keypress_max_left
    urwid.ListBox._keypress_max_right = _keypress_max_right
