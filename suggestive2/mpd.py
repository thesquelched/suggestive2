import asyncio
import logging
import itertools
from contextlib import asynccontextmanager
from typing import Iterable, Optional, Dict, Union, AsyncGenerator, List, cast

from suggestive2.util import run_method_coroutine, escape


LOG = logging.getLogger(__name__)
LOG.addHandler(logging.NullHandler())


def make_slice(start: Optional[int] = None, end: Optional[int] = None) -> str:
    if start is not None and end is not None:
        return f"{start}:{'' if end == -1 else end}"
    elif start is not None:
        return f'{start}'
    elif end is not None:
        return f":{'' if end == -1 else end}"
    else:
        return ''


class MPDClient(object):

    def __init__(self, host: str = 'localhost', port: int = 6600) -> None:
        self.host = host
        self.port = port
        self._lock = asyncio.Lock()

        self._noidle_lock = asyncio.Lock()
        self._idle_lock = asyncio.Lock()
        self._idle_task: Optional[asyncio.Task] = None

        self._reader: asyncio.StreamReader = cast(asyncio.StreamReader, None)
        self._writer: asyncio.StreamWriter = cast(asyncio.StreamWriter, None)

    async def __aenter__(self) -> 'MPDClient':
        return await self.connect()

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @asynccontextmanager
    async def _acquire(self, lock, name=None):
        lockname = 'lock' if name is None else f'{name} lock'

        LOG.debug('Waiting for %s (%s)', lockname, lock)
        async with lock:
            LOG.debug('Acquired %s (%s)', lockname, lock)
            yield

        LOG.debug('Released %s (%s)', lockname, lock)

    async def connect(self, timeout: Union[float, int] = 1.0) -> 'MPDClient':
        async with self._acquire(self._lock, 'connect'):
            if self._reader or self._writer:
                LOG.debug('Already connected to MPD on %s:%d', self.host, self.port)
                return self

            LOG.info('Connecting to MPD on %s:%d', self.host, self.port)

            try:
                reader, writer = await asyncio.open_connection(self.host, self.port)
            except Exception:
                raise ConnectionError(f'Unable to connect to {self.host}:{self.port}')

            try:
                statusline = await asyncio.wait_for(reader.readline(), timeout=timeout)
                LOG.debug('Host %s:%d responded with %s', self.host, self.port, repr(statusline))
                if not statusline:
                    raise ConnectionError(f'Unable to connect to {self.host}:{self.port}')
                elif not statusline.startswith(b'OK MPD '):
                    raise ConnectionError(
                        f'Unable to understand response from {self.host}:{self.port}; MPD may '
                        f'not be bound to this address')

                version = statusline.decode().strip().rsplit(' ', 1)[-1]
                LOG.info('Connected to MPD version %s on %s:%d', version, self.host, self.port)
            except Exception:
                writer.close()
                raise

            self._reader: asyncio.StreamReader = reader
            self._writer: asyncio.StreamWriter = writer

            return self

    def close(self) -> None:
        if not (self._reader and self._writer):
            return

        self._writer.write(b'close\n')
        self._writer.close()

    async def _send_command(self, command: str) -> None:
        LOG.debug("Running mpd command '%s'", command)

        self._writer.write(command.encode() + b'\n')
        await self._writer.drain()

    async def _run(self,
                   command: str,
                   timeout: Optional[Union[float, int]] = 1.0) -> AsyncGenerator[str, str]:
        if command != 'idle' and self._lock.locked() and self._idle_lock.locked():
            while self._idle_task is None:
                await asyncio.sleep(0.01)

            async with self._noidle_lock:
                if self._idle_task is not None:
                    await self._send_command('noidle')

                    while self._idle_task is not None:
                        await asyncio.sleep(0.01)

        if not (self._reader and self._writer):
            await self.connect()

        async with self._acquire(self._lock, f"command '{command}'"):
            await self._send_command(command)

            while True:
                try:
                    line = await asyncio.wait_for(self._reader.readline(), timeout=timeout)
                except Exception as exc:
                    raise ValueError(f'fak! {command}') from exc

                LOG.debug('MPD line from command %s: %s', command, line)

                if line is None:
                    raise ConnectionError('Unable to read command output')
                elif line.startswith(b'ACK '):
                    LOG.debug('Error response: %s', line)
                    msg = line.decode().split(' ', 3)[-1]
                    raise ValueError(f'MPD error: {msg}')

                if line == b'OK\n':
                    return

                yield line.decode().strip()

    async def _run_list(self, *args, **kwargs) -> List[str]:
        return [line async for line in self._run(*args, **kwargs)]

    async def _run_tagged(self,
                          command: str,
                          type_: str,
                          **kwargs) -> AsyncGenerator[Dict[str, str], str]:
        obj: Dict[str, str] = {}
        async for line in self._run(command, **kwargs):
            tag, value = line.split(': ', 1)
            tag = tag.lower()

            if tag == type_ and obj:
                yield obj
                obj = {}

            obj[tag] = value

        if obj:
            yield obj

    async def list(self,
                   type_: str,
                   groupby: Optional[Iterable[str]] = None) -> AsyncGenerator[Dict[str, str], str]:
        if groupby is None:
            groupby = []

        command = ' '.join(itertools.chain(
            ('list', type_),
            itertools.chain.from_iterable(('group', escape(group)) for group in groupby),
        ))

        async for item in self._run_tagged(command, type_):
            yield item

    async def playlistinfo(
            self,
            start: Optional[int] = None,
            end: Optional[int] = None
    ) -> AsyncGenerator[Dict[str, str], str]:
        spec = make_slice(start, end)
        command = f'playlistinfo {spec}' if spec else 'playlistinfo'

        async for item in self._run_tagged(command, 'file'):
            yield item

    async def _idle(self) -> List[str]:
        items = self._run_tagged('idle', 'changed', timeout=None)
        return [item['changed'] async for item in items]

    async def idle(self) -> List[str]:
        async with self._acquire(self._idle_lock, 'idle'):
            task = run_method_coroutine(asyncio.get_event_loop(), self._idle)
            self._idle_task = task

            try:
                result = await task
                return result
            finally:
                self._idle_task = None

    async def clear(self) -> None:
        await self._run_list('clear')

    async def pause(self) -> None:
        await self._run_list('pause')

    async def searchadd(self, **tags) -> None:
        command = ' '.join(itertools.chain(
            ('searchadd',),
            itertools.chain.from_iterable(
                (key, escape(value)) for key, value in tags.items()
            ),
        ))
        await self._run_list(command)

    async def playlistsearch(self, **tags) -> AsyncGenerator[Dict[str, str], str]:
        command = ' '.join(itertools.chain(
            ('playlistsearch',),
            itertools.chain.from_iterable(
                (key, escape(value)) for key, value in tags.items()
            ),
        ))
        async for track in self._run_tagged(command, 'file'):
            yield track

    async def playid(self, track_id: int) -> None:
        await self._run_list(f'playid {track_id}')

    async def play(self, position: int) -> None:
        await self._run_list(f'play {position}')

    async def delete(self,
                     start: int,
                     end: Optional[int] = None) -> None:
        spec = make_slice(start, end)
        await self._run_list(f'delete {spec}')

    async def next(self) -> None:
        await self._run_list('next')

    async def previous(self) -> None:
        await self._run_list('previous')

    async def currentsong(self) -> Optional[Dict[str, str]]:
        result = [track async for track in self._run_tagged('currentsong', 'file')]
        return result[0] if result else None
