import asyncio
import urwid
from typing import List, Optional, NamedTuple, Tuple, Dict, Callable


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


class AlbumList(VimListBox):

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
            raise KeyboardInterrupt
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
    ]

    return [(p.name, 'default', 'default', 'default', p.fg, p.bg)
            for p in palette]


class Application(object):

    def __init__(self):
        self.widgets: Dict[str, urwid.Widget] = dict()
        self.loop = urwid.MainLoop(
            self.build(),
            palette=generate_palette(),
            handle_mouse=False,
            unhandled_input=self.unhandled_input,
            event_loop=urwid.AsyncioEventLoop(loop=asyncio.get_event_loop()),
        )
        self.loop.screen.set_terminal_properties(colors=256)
        self.key_buffer: List[str] = []

        self.buffer_sequences: Dict[Tuple[str], Callable[[], Any]] = {
            ('Z', 'Z'): self.exit,
        }

    def exit(self):
        raise KeyboardInterrupt

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
        window = Window([
            urwid.AttrMap(
                Pane(
                    AlbumList(),
                    urwid.AttrMap(urwid.Text('footer1'), 'status')),
                'pane'
            ),
            urwid.AttrMap(
                Pane(
                    AlbumList(),
                    urwid.AttrMap(urwid.Text('footer2'), 'status')),
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

        top.focus_body()

        return urwid.AttrMap(
            top,
            'background',
        )

    def run(self):
        try:
            self.loop.run()
        except KeyboardInterrupt:
            pass


app = Application()


def main():
    app.run()


if __name__ == '__main__':
    main()
