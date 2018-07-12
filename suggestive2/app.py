import asyncio
import urwid
import argparse
import logging
import weakref
import functools
import os
import itertools
from collections import defaultdict
from typing import List, NamedTuple, Tuple, Dict, Callable, Union, Any, Set, Iterable

from suggestive2.monkey import monkeypatch
from suggestive2.mpd import MPDClient
from suggestive2.types import Config
from suggestive2.util import run_method_coroutine, expand, prefix_matches
import suggestive2.config as default_config


LOG = logging.getLogger('suggestive2')
LOG.addHandler(logging.NullHandler())


monkeypatch()

class LibraryListWalker(urwid.ListWalker):

    def __init__(self):
        self.library: List[Tuple[str, str]] = []
        self.contents: List[urwid.Widget] = []
        self.focus: int = 0

    def get_focus(self):
        return self._get(self.focus)

    def set_focus(self, focus):
        self.focus = focus
        self._modified()

    def clear(self):
        self.library[:] = []
        self.contents[:] = []
        self._modified()

    def get_next(self, current):
        return self._get(current + 1)

    def get_prev(self, current):
        return self._get(current - 1)

    def _get(self, position):
        if position < 0:
            return None, None

        if position >= len(self.contents):
            if position >= len(self.library):
                app.run_coroutine(self.load, weakref.ref(app))
                return None, None
            else:
                self.contents.extend(
                    urwid.AttrMap(LibraryAlbum(artist, album), 'album', 'focus album')
                    for artist, album in self.library[len(self.contents):position + 1]
                )

        return self.contents[position], position

    async def load(self, appref):
        app = appref()
        if not app:
            return

        client = await app.async_mpd()
        self.library = [(obj['albumartist'], obj['album'])
                        async for obj in client.list('albumartist', groupby=('album',))]
        self._modified()

    # def find(self, pattern):
    #     word_to_idx = sorted(itertools.chain.from_iterable(
    #         ((artist, i), (album, i))
    #         for i, (artist, album) in enumerate(self.library)
    #     ))


class Palette(NamedTuple):
    name: str
    fg: str
    bg: str
    bold: bool = False
    invert: bool = False


class SimpleText(urwid.WidgetWrap):

    def __init__(self, text: str) -> None:
        widget = urwid.Filler(urwid.Text(text), 'top')
        super().__init__(widget)


class CommandPrompt(urwid.Edit):

    def __init__(self):
        super().__init__('')
        self.search_results = []
        self.keypress_callback: Optional[Callable] = None
        self.complete_callback: Optional[Callable] = None

    def clear(self):
        self.set_caption('')
        self.set_edit_text('')
        self.search_results.clear()

    def start(self,
              keypress_callback: Callable,
              complete_callback: Callable,
              caption: str = ': ') -> None:
        self.set_caption(caption)

        self.keypress_callback = keypress_callback
        self.complete_callback = complete_callback

    def keypress(self, size, key: str):
        if key == 'esc':
            app.widget_by_name('top').focus_body()
            self.clear()
        elif key == 'enter':
            app.widget_by_name('top').focus_body()
            self.complete_callback(self.get_edit_text())
            self.clear()
        else:
            result = super().keypress(size, key)

            self.keypress_callback(self.get_edit_text())

            return result


class VimListBox(urwid.ListBox):
    REMAP = {
        'k': 'up',
        'j': 'down',
        'h': 'left',
        'l': 'right',
        'ctrl f': 'page down',
        'ctrl b': 'page up',
    }

    def __init__(self, body):
        super().__init__(body)
        self.search_contents: Dict[str, Set[int]] = {}
        self.search_results: List[List[str]] = []
        self.search_result: List[int] = []

    def keypress(self, size, key: str):
        if key == '/':
            search_contents = defaultdict(set)
            for key, value in self.get_search_contents():
                search_contents[key.lower()].add(value)

            self.search_contents = search_contents

            app.widget_by_name('command_prompt').start(
                self.search_keypress,
                self.search_complete,
                '/',
            )
            app.widget_by_name('top').focus_on('footer')
        elif key == 'n':
            self.next_search_match()
        elif key == 'N':
            self.prev_search_match()
        else:
            return super().keypress(size, self.REMAP.get(key, key))

    def get_search_contents(self) -> Iterable[Tuple[str, int]]:
        raise NotImplementedError

    def search_keypress(self, value: str) -> None:
        assert len(value) != len(self.search_results)

        if len(value) < len(self.search_results):
            self.search_results.pop()
        else:
            words = (self.search_results[-1]
                     if self.search_results
                     else sorted(self.search_contents))
            self.search_results.append(prefix_matches(value.lower(), words))

        if not self.search_results:
            return

        LOG.debug('Current search results for prefix %s: %s', value, self.search_results[-1])

    def search_complete(self, value) -> None:
        if not self.search_results:
            LOG.info('No search performed')
            return

        self.search_result = sorted(set(itertools.chain.from_iterable(
            self.search_contents[word]
            for word in self.search_results[-1]
        )))

        self.search_results.clear()
        if not self.search_result:
            LOG.info("No search results found for pattern '%s'", value)
            return

        LOG.info('Found search results at indicies %s',
                 ', '.join(str(i) for i in self.search_result))

        self.next_search_match()

    def next_search_match(self) -> None:
        if not self.search_result:
            return

        idx = next(
            (i for i in self.search_result if i > self.focus_position),
            self.search_result[0],
        )
        LOG.debug('Next search match is at index %d', idx)
        self.focus_position = idx

    def prev_search_match(self) -> None:
        if not self.search_result:
            return

        idx = next(
            (i for i in reversed(self.search_result) if i < self.focus_position),
            self.search_result[-1],
        )

        LOG.debug('Previous search match is at index %d', idx)
        self.focus_position = idx


class LibraryAlbum(urwid.WidgetWrap):

    def __init__(self, artist: str, album: str) -> None:
        self.artist = artist
        self.album = album

        widget = urwid.SelectableIcon(f'{artist} - {album}')
        super().__init__(widget)

    def keypress(self, size, key: str):
        if key in ('enter', ' '):
            app.run_coroutine(self.enqueue, weakref.ref(app), key == 'enter')
        else:
            return super().keypress(size, key)

    async def enqueue(self, appref: weakref.ref, play: bool) -> None:
        app = appref()
        if not app:
            return

        client = await app.async_mpd()
        await client.searchadd(artist=self.artist, album=self.album)

        if play:
            tracks = [track async for track in client.playlistsearch(artist=self.artist,
                                                                     album=self.album)]
            if not tracks:
                raise ValueError('There should be tracks here...')

            first = tracks[0]
            last_track_id = next(track['id']
                                 for track in reversed(tracks)
                                 if track['title'] == first['title'])
            await client.playid(int(last_track_id))



class Library(VimListBox):

    def __init__(self):
        self._body = LibraryListWalker()
        super().__init__(self._body)

    def clear(self):
        self._body.clear()

    def get_search_contents(self) -> Iterable[Tuple[str, int]]:
        return (itertools.chain.from_iterable(
            ((artist, i), (album, i))
            for i, (artist, album) in enumerate(self._body.library)
        ))

    # def __init__(self):
    #     self._body = urwid.SimpleFocusListWalker([])
    #     super().__init__(self._body)

    # def update_albums(self, albums):
    #     self._body[:] = [urwid.AttrMap(LibraryAlbum(artist, album), 'album' 'focus album')
    #                      for artist, album in albums]


class PlaylistTrack(urwid.WidgetWrap):

    def __init__(self, mpd_id: Union[str, int], artist: str, album: str, track: str) -> None:
        self.mpd_id: int = int(mpd_id)
        self.artist = artist
        self.album = album
        self.track = track

        widget = urwid.SelectableIcon(f'{artist} - {album} - {track}')
        super().__init__(widget)

    @classmethod
    def from_mpd_info(cls, info):
        return cls(
            info.get('id'),
            info.get('artist', info.get('albumartist', 'Unknown')),
            info.get('album', 'Unknown'),
            info.get('title', 'Unknown'),
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

    async def sync(self, appref):
        app = appref()
        if not app:
            return

        client = await app.async_mpd()
        items = [item async for item in client.playlistinfo()]

        playing_track = await client.currentsong()
        playing_idx = int(playing_track['pos']) if playing_track else None

        self.set_contents([
            urwid.AttrMap(PlaylistTrack.from_mpd_info(item),
                          'playing' if i == playing_idx else 'track',
                          'focus playing' if i == playing_idx else 'focus track')
            for i, item in enumerate(items)
        ])

    def get_search_contents(self) -> Iterable[Tuple[str, int]]:
        widgets = (widget.base_widget for widget in self._body)
        return itertools.chain.from_iterable(
            ((track.artist, i), (track.album, i), (track.track, i))
            for i, track in enumerate(widgets)
        )


class Pane(urwid.WidgetWrap):

    def __init__(self, body: urwid.Widget, statusline: urwid.Widget) -> None:
        widget = urwid.Frame(
            body=body,
            footer=statusline,
        )
        super().__init__(widget)

    def get_body(self):
        return self._w.body


class Window(urwid.Columns):

    def __init__(self, panes: List[Pane]) -> None:
        super().__init__(panes, dividechars=1)

    def keypress(self, size, key: str):
        if key == 'q':
            raise urwid.ExitMainLoop
        elif key == 'c':
            app.loop.create_task(functools.partial(mpd_clear, weakref.ref(app))())
        elif key == 'p':
            app.loop.create_task(functools.partial(mpd_pause, weakref.ref(app))())
        else:
            return super().keypress(size, key)


class TopLevel(urwid.WidgetWrap):

    def __init__(self, body: urwid.Widget, header=urwid.Widget, footer=urwid.Widget) -> None:
        widget = urwid.Frame(body=body, header=header, footer=footer)
        super().__init__(widget)

    def focus_on(self, what: str):
        self._w.set_focus(what)

    def focus_body(self):
        self.focus_on('body')

    def keypress(self, size, key: str):
        if key == ':':
            app.widget_by_name('command_prompt').start(
                announce,
                announce,
            )
            self._w.set_focus('footer')
        else:
            return super().keypress(size, key)


def announce(value):
    LOG.info('Search/command received %s', value)


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
        Palette(name='playing', fg='#000', bg='#fff', bold=True),
        Palette(name='focus playing', fg='#000', bg='#0ff', bold=True, invert=True),
    ]

    colors = (
        (p, p.bg if p.invert else p.fg, p.fg if p.invert else p.bg)
        for p in palette
    )

    return [
        (
            p.name,
            'default',
            'default',
            'default',
            f'bold,{fg}' if p.bold else fg,
            bg,
        ) for p, fg, bg in colors
    ]


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

        self.buffer_sequences: Dict[Tuple[str, ...], Callable[[], Any]] = {
            ('Z', 'Z'): self.exit,
        }
        self.mpd_lock = asyncio.Lock()
        self.mpd: MPDClient = None


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
        self.register_widget(window, 'window')

        top.focus_body()

        return urwid.AttrMap(
            top,
            'background',
        )

    async def async_mpd(self):
        if not self.mpd:
            async with self.mpd_lock:
                if not self.mpd:
                    self.mpd = await MPDClient(
                        self.config['mpd']['host'],
                        self.config['mpd']['port']
                    ).connect()

        return self.mpd

    def run_coroutine(self, method, *args):
        run_method_coroutine(self.loop, method, *args)

    def run(self):
        self.run_coroutine(self.widget_by_name('playlist').sync, weakref.ref(self))
        self.loop.create_task(functools.partial(mpd_idle, weakref.ref(self))())
        self.mainloop.run()


async def mpd_idle(appref):
    app = appref()
    if not app:
        return

    client = await app.async_mpd()

    while True:
        # Wait to let other commands queue up
        await asyncio.sleep(0.1)

        for subsystems in await client.idle():
            if not appref():
                return

            LOG.debug('Subsystems changed: %s', subsystems)

            if 'playlist' in subsystems or 'player' in subsystems:
                app.run_coroutine(app.widget_by_name('playlist').sync, appref)
            if 'database' in subsystems:
                app.widget_by_name('library').clear()



def mpd_func(command):
    async def func(appref, *args, __command=command, **kwargs):
        app = appref()
        if not app:
            return

        client = await app.async_mpd()
        await getattr(client, __command)()

    return func


mpd_clear = mpd_func('clear')
mpd_pause = mpd_func('pause')


app = Application()


def init_logging(args):
    path = expand(args.log)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    logging.basicConfig(filename=path,
                        level=logging.ERROR,
                        format='%(asctime)s %(threadName)s %(levelname)s %(name)s: %(message)s')
    LOG.setLevel(args.log_level)


def main(args=None):
    p = argparse.ArgumentParser(prog='suggestive2')
    p.add_argument('--config', '-c', default='$HOME/.suggestive/config.py',
                   help='Config file (default: $HOME/.suggestive/config.py)')
    p.add_argument('--log', '-l', default='$HOME/.suggestive/log.txt',
                   help='Log file (default: $HOME/.suggestive/log.txt)')
    p.add_argument('--debug', '-d', dest='log_level', action='store_const',
                   const=logging.DEBUG, default=logging.INFO,
                   help='Enable debug logging')

    args = p.parse_args(args)
    init_logging(args)

    app.config = default_config.load_config(args.config)

    app.run()


if __name__ == '__main__':
    main()
