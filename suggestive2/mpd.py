import asyncio
import logging
import itertools
from typing import Iterable, Optional, Dict, Union, AsyncGenerator, List, cast

from suggestive2.util import run_method_coroutine


LOG = logging.getLogger(__name__)
LOG.addHandler(logging.NullHandler())


class MPDClient(object):

    def __init__(self, host: str = 'localhost', port: int = 6600) -> None:
        self.host = host
        self.port = port
        self._lock = asyncio.Lock()

        self._idle_lock = asyncio.Lock()
        self._idle_task: Optional[asyncio.Task] = None

        self._reader: asyncio.StreamReader = cast(asyncio.StreamReader, None)
        self._writer: asyncio.StreamWriter = cast(asyncio.StreamWriter, None)

    async def __aenter__(self) -> 'MPDClient':
        return await self.connect()

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    async def connect(self, timeout: Union[float, int] = 1.0) -> 'MPDClient':
        async with self._lock:
            if self._reader or self._writer:
                return self

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

    async def _run(self,
                   command: str,
                   timeout: Optional[Union[float, int]] = 1.0) -> AsyncGenerator[str, str]:
        if self._idle_task is not None and command != 'idle':
            self._writer.write(b'noidle\n')
            await self._writer.drain()

        if not (self._reader and self._writer):
            await self.connect()

        async with self._lock:
            self._writer.write(command.encode() + b'\n')
            await self._writer.drain()

            while True:
                try:
                    line = await asyncio.wait_for(self._reader.readline(), timeout=timeout)
                except Exception as exc:
                    raise ValueError(f'fak! {command}') from exc

                LOG.debug('Result line: %s', line)

                if line is None:
                    raise ConnectionError('Unable to read command output')
                elif line.startswith(b'ACK '):
                    msg = line.decode().split(' ', 3)[-1]
                    raise ValueError(f'MPD error: {msg}')

                if line == b'OK\n':
                    return

                yield line.decode().strip()

    async def _run_list(self, *args, **kwargs) -> AsyncGenerator[str, str]:
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

        tags: List[str] = [type_]
        tags.extend(groupby)

        command = ' '.join(itertools.chain(
            ('list', type_),
            itertools.chain.from_iterable(('group', group) for group in tags[1:]),
        ))

        async for item in self._run_tagged(command, type_):
            yield item

    async def playlistinfo(self) -> AsyncGenerator[Dict[str, str], str]:
        async for item in self._run_tagged('playlistinfo', 'file'):
            yield item

    async def _idle(self) -> List[str]:
        items = self._run_tagged('idle', 'changed', timeout=None)
        return [item['changed'] async for item in items]

    async def idle(self) -> List[str]:
        async with self._idle_lock:
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
        escaped = {key: value.replace('"', '\\"') for key, value in tags.items()}
        command = ' '.join(itertools.chain(
            ('searchadd',),
            itertools.chain.from_iterable(
                (key, f'"{value}"') for key, value in escaped.items()
            ),
        ))
        await self._run_list(command)
