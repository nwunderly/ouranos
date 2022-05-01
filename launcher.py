from argparse import ArgumentParser

from auth import DB_URL_DEV, DB_URL_PROD, TOKEN_DEV, TOKEN_PROD
from loguru import logger

from ouranos.bot import Ouranos
from ouranos.utils import log

# set up uvloop if we can
try:
    import uvloop

    uvloop.install()
except:
    pass


def start_bot(args):
    dev = args.dev
    lvl = args.log

    if not lvl:
        lvl = "debug" if dev else "info"

    log.init(lvl.upper())

    token = TOKEN_DEV if dev else TOKEN_PROD
    db_url = DB_URL_DEV if dev else DB_URL_PROD
    bot = Ouranos(token, db_url)

    logger.info("Starting up.")

    try:
        bot.run()
    finally:
        try:
            exit_code = bot._exit_code
        except AttributeError:
            logger.info("Bot's exit code could not be retrieved.")
            exit_code = 0
        logger.info(f"Bot closed with exit code {exit_code}.\n" + "-" * 100)
        exit(exit_code)


def main():
    parser = ArgumentParser(description="Launch Ouranos Discord bot.")

    parser.add_argument("--log")
    parser.add_argument("--dev", action="store_true")

    args = parser.parse_args()

    start_bot(args)


if __name__ == "__main__":
    main()
