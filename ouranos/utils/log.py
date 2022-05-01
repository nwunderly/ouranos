import logging
import sys
from collections import deque

import aiohttp
from auth import WEBHOOK_URL_PROD
from discord.webhook import AsyncWebhookAdapter, Webhook
from loguru import logger


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

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def ouranos_or_main(r):
    return r["name"].startswith(("__main__", "ouranos"))


async def webhook_log(msg):
    async with aiohttp.ClientSession() as session:
        webhook = Webhook.from_url(
            WEBHOOK_URL_PROD, adapter=AsyncWebhookAdapter(session)
        )
        await webhook.send(f"```\n{msg}\n```")


log_cache = deque(maxlen=100)


def cache_log(msg):
    log_cache.append(msg)


def init(lvl):
    logger.remove()
    debug = lvl == "DEBUG"

    # main log (stdout, viewable with docker logs command)
    logger.add(sys.stdout, diagnose=debug, level=lvl, backtrace=False)

    # discord log file
    logging.getLogger("discord").addHandler(InterceptHandler())
    logger.add(
        "./logs/discord.log",
        rotation="00:00",
        retention="1 week",
        backtrace=False,
        diagnose=False,
        level="INFO",
        filter="discord",
    )

    # ouranos log file
    logger.add(
        "./logs/ouranos.log",
        rotation="00:00",
        retention="1 week",
        diagnose=debug,
        backtrace=False,
        level=lvl,
        filter=ouranos_or_main,
    )

    # if production, also use webhook error log
    if not debug:
        logger.add(
            webhook_log,
            diagnose=False,
            backtrace=False,
            level="ERROR",
            filter=ouranos_or_main,
        )

    # cache of last 100 log messages
    logger.add(
        cache_log,
        diagnose=False,
        backtrace=False,
        level="DEBUG",
        filter=ouranos_or_main,
    )
