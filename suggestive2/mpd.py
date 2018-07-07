from mpd.asyncio import MPDClient

from suggestive2.types import Config


async def connect(config: Config) -> MPDClient:
    client = MPDClient()
    await client.connect(config['mpd']['host'], int(config['mpd']['port']))

    return client
