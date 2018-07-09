import pytest
import asyncio

from suggestive2.mpd import MPDClient


pytestmark = pytest.mark.asyncio


class MockServer(object):

    def __init__(self, host, port, loop, statusline=None):
        self.host = host
        self.port = port
        self.loop = loop
        self.statusline = statusline or b'OK MPD 0.20.0'
        self._lines = []

    @property
    def lines(self):
        return self._lines

    @lines.setter
    def lines(self, values):
        self._lines = iter(values)

    async def __call__(self, reader, writer):
        writer.write(self.statusline + b'\n')

        try:
            for outline in self.lines:
                line = await reader.readline()
                if not line:
                    break

                writer.write(outline.encode() + b'\n')
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def start(self):
        return await asyncio.start_server(
            self,
            self.host,
            self.port,
            loop=self.loop,
        )


@pytest.fixture
async def server(event_loop, unused_tcp_port):
    server = MockServer('127.0.0.1', unused_tcp_port, event_loop)
    running = await server.start()

    yield server

    running.close()


@pytest.fixture
async def not_mpd_server(event_loop, unused_tcp_port):
    server = MockServer('127.0.0.1', unused_tcp_port, event_loop, statusline=b'welkrjewlkj')
    running = await server.start()

    yield server

    running.close()


async def test_connect(server):
    client = MPDClient(server.host, server.port)
    await client.connect()
    client.close()


async def test_not_mpd(not_mpd_server):
    client = MPDClient(not_mpd_server.host, not_mpd_server.port)
    with pytest.raises(ConnectionError) as exc:
        await client.connect()
        exc.match(f'Unable to understand response from '
                  f'{not_mpd_server.host}:{not_mpd_server.port}; MPD may not be bound to this '
                  f'address')

    client.close()


async def test_no_connection(unused_tcp_port):
    client = MPDClient('127.0.0.1', unused_tcp_port)
    with pytest.raises(ConnectionError) as exc:
        await client.connect()
        exc.match(f'Unable to connect to 127.0.0.1:{unused_tcp_port}')

    client.close()
