import asyncio
import urwid
import argparse
import logging
import importlib
import inspect
import os.path
import weakref
import functools
import traceback
import sys
from collections import ChainMap
from typing import List, Optional, NamedTuple, Tuple, Dict, Callable

from suggestive2 import mpd
from suggestive2.types import Config
from suggestive2.util import expand
import suggestive2.config as default_config


LOG = logging.getLogger('suggestive2')
LOG.addHandler(logging.NullHandler())


class Palette(NamedTuple):
    name: str
    fg: str
    bg: str


class SimpleText(urwid.WidgetWrap):

    def __init__(self, text: str):
        widget = urwid.Filler(urwid.Text(text), 'top')
        super().__init__(widget)


class CommandPrompt(urwid.Edit):

    def __init__(self):
        super().__init__('')

    def clear(self):
        self.set_caption('')
        self.set_edit_text('')

    def start(self, caption: str=': '):
        self.set_caption(caption)

    def keypress(self, size, key: str):
        if key == 'esc':
            app.widget_by_name('top').focus_body()
            self.clear()
        else:
            return super().keypress(size, key)


class VimListBox(urwid.ListBox):
    REMAP = {
        'k': 'up',
        'j': 'down',
        'h': 'left',
        'l': 'right',
        'ctrl f': 'page down',
        'ctrl b': 'page up',
    }

    def keypress(self, size, key: str):
        return super().keypress(size, self.REMAP.get(key, key))


class Library(VimListBox):

    def __init__(self):
        albums = [
            urwid.SelectableIcon('item1'),
            urwid.SelectableIcon('item2'),
            urwid.SelectableIcon('item3'),
        ]
        self._body = urwid.SimpleFocusListWalker([
            urwid.AttrMap(item, 'album', 'focus album')
            for item in albums
        ])
        super().__init__(self._body)


class PlaylistTrack(urwid.WidgetWrap):

    def __init__(self, mpd_id: int, artist: str, album: str, track: str):
        self.mpd_id =  mpd_id
        self.artist = artist
        self.album = album
        self.track = track

        widget = urwid.SelectableIcon(f'{artist} - {album} - {track}')
        super().__init__(widget)

    @classmethod
    def from_mpd_info(cls, info):
        return cls(
            int(info['id']),
            info['artist'],
            info['album'],
            info['title'],
        )

# {
#     'file': 'The Black Angels/Phosphene Dream/05 River of Blood.mp3',
#     'last-modified': '2016-09-17T19:04:18Z',
#     'artist': 'The Black Angels',
#     'album': 'Phosphene Dream',
#     'albumartistsort': 'Black Angels, The',
#     'title': 'River of Blood',
#     'track': '5/10',
#     'genre': 'Rock',
#     'date': '2010-09-13',
#     'disc': '1/1',
#     'albumartist': 'The Black Angels',
#     'time': '238',
#     'duration': '238.184',
#     'pos': '4',
#     'id': '49'
# }

class Playlist(VimListBox):

    def __init__(self):
        self._body = urwid.SimpleFocusListWalker([])
        super().__init__(self._body)

    def set_contents(self, contents):
        self._body[:] = contents

    async def sync(self, config):
        client = await mpd.connect(config)
        items = [item async for item in client.playlistinfo()]

        self.set_contents([
            urwid.AttrMap(PlaylistTrack.from_mpd_info(item), 'track', 'focus track')
            for item in items
        ])

        client.disconnect()


class Pane(urwid.WidgetWrap):

    def __init__(self, body: urwid.Widget, statusline: urwid.Widget):
        widget = urwid.Frame(
            body=body,
            footer=statusline,
        )
        super().__init__(widget)


class Window(urwid.Columns):

    def __init__(self, panes: List[Pane]):
        super().__init__(panes, dividechars=1)

    def keypress(self, size, key: str):
        if key == 'q':
            raise urwid.ExitMainLoop
        else:
            return super().keypress(size, key)


class TopLevel(urwid.WidgetWrap):

    def __init__(self, body: urwid.Widget, header=urwid.Widget, footer=urwid.Widget):
        widget = urwid.Frame(body=body, header=header, footer=footer)
        super().__init__(widget)

    def focus_body(self):
        self._w.set_focus('body')

    def keypress(self, size, key: str):
        if key == ':':
            app.widget_by_name('command_prompt').start()
            self._w.set_focus('footer')
        else:
            return super().keypress(size, key)


def generate_palette() -> List[Tuple[str, str, str, str, str, str]]:
    palette = [
        Palette(name='footer', fg='#000', bg='#00f'),
        Palette(name='command', fg='#000', bg='#00f'),
        Palette(name='status', fg='#000', bg='#08f'),
        Palette(name='background', fg='#000', bg='#00f'),
        Palette(name='pane', fg='#000', bg='#fff'),
        Palette(name='album', fg='#000', bg='#fff'),
        Palette(name='focus album', fg='#000', bg='#0ff'),
        Palette(name='track', fg='#000', bg='#fff'),
        Palette(name='focus track', fg='#000', bg='#0ff'),
    ]

    return [(p.name, 'default', 'default', 'default', p.fg, p.bg)
            for p in palette]


class Application(object):

    def __init__(self):
        self.config: Config = {}
        self.widgets: Dict[str, urwid.Widget] = dict()
        self.loop = asyncio.get_event_loop()
        self.mainloop = urwid.MainLoop(
            self.build(),
            palette=generate_palette(),
            handle_mouse=False,
            unhandled_input=self.unhandled_input,
            event_loop=urwid.AsyncioEventLoop(loop=self.loop),
        )
        self.mainloop.screen.set_terminal_properties(colors=256)
        self.key_buffer: List[str] = []

        self.buffer_sequences: Dict[Tuple[str], Callable[[], Any]] = {
            ('Z', 'Z'): self.exit,
        }

    def exit(self):
        raise urwid.ExitMainLoop

    def register_widget(self, widget: urwid.Widget, name: str):
        self.widgets[name] = widget

    def widget_by_name(self, name: str) -> urwid.Widget:
        return self.widgets[name]

    def unhandled_input(self, key: str) -> bool:
        if key == 'esc':
            self.key_buffer.clear()
        else:
            self.key_buffer.append(key)
            action = self.buffer_sequences.get(tuple(self.key_buffer))
            if action is not None:
                action()
                self.key_buffer.clear()

        return True

    def build(self) -> urwid.Widget:
        command_prompt = CommandPrompt()
        library = Library()
        playlist = Playlist()

        window = Window([
            urwid.AttrMap(
                Pane(
                    library,
                    urwid.AttrMap(urwid.Text('library'), 'status')),
                'pane'
            ),
            urwid.AttrMap(
                Pane(
                    playlist,
                    urwid.AttrMap(urwid.Text('playlist'), 'status')),
                'pane'
            ),
        ])
        top = TopLevel(
            body=window,
            header=urwid.Text('suggestive2'),
            footer=urwid.AttrMap(command_prompt, 'command'),
        )

        self.register_widget(top, 'top')
        self.register_widget(command_prompt, 'command_prompt')
        self.register_widget(library, 'library')
        self.register_widget(playlist, 'playlist')

        top.focus_body()

        return urwid.AttrMap(
            top,
            'background',
        )

    def run_coroutine(self, method, *args):
        proxy = weakref.proxy(method.__self__)
        weak_method = method.__func__.__get__(proxy)
        self.loop.create_task(weak_method(*args))

    def run(self):
        self.run_coroutine(self.widget_by_name('playlist').sync, self.config)
        self.mainloop.run()


app = Application()


def load_config(path: str) -> Config:
    defaults = {key: vars(value)
                for key, value in inspect.getmembers(default_config, inspect.isclass)}

    if os.path.isfile(path):
        sys.path.insert(0, os.path.dirname(path))
        config = import_module(os.path.splitext(os.path.basename(path))[0])

        config_vals = {section: vars(getattr(config, section)) if hasattr(config, section) else {}
                       for section in defaults}

        result = {section: ChainMap(config_vals[section], defaults[section])
                  for section in defaults}
    else:
        result = defaults

    return {key.lower(): value for key, value in result.items()}


def main(args=None):
    p = argparse.ArgumentParser(prog='suggestive2')
    p.add_argument('--config', '-c', default=expand('~/.suggestive/config.py'),
                   help='Config file (default: $HOME/.suggestive/config.py)')

    args = p.parse_args(args)
    app.config = load_config(args.config)

    app.run()


if __name__ == '__main__':
    main()
