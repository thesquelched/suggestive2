import weakref
import os.path
from itertools import dropwhile, takewhile

from typing import Any, List


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


def prefix_matches(prefix: str, words: List[str]) -> List[str]:
    return _prefix_search('', prefix, words)


def _prefix_search(prefix: str, suffix: str, words: List[str]) -> List[str]:
    if not words:
        return []
    elif not suffix:
        return [prefix + word for word in words]

    matches = list(takewhile(
        lambda word: word and word[0] == suffix[0],
        dropwhile(
            lambda word: not (word and word[0] == suffix[0]),
            words
        )
    ))
    remaining = [word[1:] for word in matches]
    return _prefix_search(prefix + suffix[0], suffix[1:], remaining)
