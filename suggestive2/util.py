import weakref
import os.path

from typing import Any


ESCAPE_TRANSLATION = str.maketrans({
    '"': '\\"',
    '\n': None,
    '\r': None,
})


def expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))


def run_method_coroutine(loop, method, *args):
    proxy = weakref.proxy(method.__self__)
    weak_method = method.__func__.__get__(proxy)
    return loop.create_task(weak_method(*args))


def escape(value: Any) -> str:
    escaped = str(value).translate(ESCAPE_TRANSLATION)
    return f'"{escaped}"'
