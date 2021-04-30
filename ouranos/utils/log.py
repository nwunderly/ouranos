import aiohttp
import logging
import sys

from loguru import logger
from discord.webhook import Webhook, AsyncWebhookAdapter

from auth import WEBHOOK_URL_PROD


class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


async def webhook_log(msg):
    async with aiohttp.ClientSession() as session:
        webhook = Webhook.from_url(WEBHOOK_URL_PROD, adapter=AsyncWebhookAdapter(session))
        await webhook.send(f"```\n{msg}\n```")


def init(lvl):
    logger.remove()

    debug = lvl == 'DEBUG'

    discord_log = logging.getLogger('discord')
    discord_log.setLevel(logging.INFO)
    discord_log.addHandler(InterceptHandler())

    logger.add(
        sys.stdout,
        diagnose=debug,
    )

    logger.add(
        './logs/discord.log',
        rotation='00:00',
        retention='1 week',
        filter='discord',
    )

    to_log = ('__main__', 'ouranos')

    logger.add(
        './logs/ouranos.log',
        rotation='00:00',
        retention='1 week',
        diagnose=debug,
        level=lvl,
        filter=lambda r: r['name'].startswith(to_log),
    )

    if not debug:
        logger.add(
            webhook_log,
            level=logging.ERROR,
            filter=lambda r: r['name'].startswith(to_log),
        )
