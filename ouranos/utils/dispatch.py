import asyncio
import io
import discord

from collections import deque, namedtuple
from loguru import logger

from ouranos.bot import Ouranos
from ouranos.utils import db
from ouranos.utils.emojis import PENCIL, TRASH, INBOX, OUTBOX


CATEGORIES = {
    'message_logs': {
        'message_edit': PENCIL,
        'message_delete': TRASH,
    },
    'join_leave_logs': {
        'member_join': INBOX,
        'member_remove': OUTBOX,
    }
}


def get_log_category(event):
    for category, events in CATEGORIES.items():
        if event in events:
            return category


def get_log_emoji(event):
    for category, events in CATEGORIES.items():
        if event in events:
            return events[event]


log_queue = dict()
LogMessage = namedtuple('LogMessage', ['content', 'file'])


def copy_file(file):
    f = None
    if file is not None:
        buffer = file[0]
        name = file[1]
        buffer.seek(0)
        b2 = io.BytesIO()
        for line in buffer.readlines():
            b2.write(line)
        b2.seek(0)
        f = discord.File(b2, name)
    return f


async def send_message(guild, event, message=None, file=None):
    targets = []
    event_category = get_log_category(event)
    if not event_category:
        logger.error(f"Could not find log category for event {event}.")
        return

    config = await db.get_config(guild)
    if not (config and config.logging_config):
        return

    for channel_id, enabled_categories in config.logging_config.items():
        if event_category in enabled_categories:
            targets.append(channel_id)

    # no targets? no logging
    if len(targets) == 0:
        return

    for target in targets:
        # make sure we have a queue and a running task
        if target not in log_queue:
            log_queue[target] = deque()
            await Ouranos.bot.run_in_background(log_task(guild, target))

        # duplicate the file bytes so it doesn't freak out when we try to send it twice
        f = copy_file(file)

        # actually adding to the queue
        log_queue[target].append(LogMessage(message, f))


async def log_task(guild, target):
    to_send = ""

    # keep pumping until we run out of messages
    while log_queue[target]:
        try:
            channel = Ouranos.bot.get_channel(int(target))

            # channel no longer exists
            if channel is None:
                del log_queue[target]
                return

            # pull message from queue
            try:
                todo = log_queue[target].popleft()
            except IndexError:
                return

            if (len(to_send) + len(todo.content) if todo.content is not None else 0) < 2000:
                to_send = f'{to_send}\n{todo.content if todo.content is not None else ""}'
            else:
                # too large, send it out
                await channel.send(to_send, allowed_mentions=discord.AllowedMentions.none())
                to_send = todo.content

            # if there's a file, or if queue is empty, send it right away
            if todo.file is not None or not log_queue[target]:
                await channel.send(to_send, file=todo.file, allowed_mentions=discord.AllowedMentions.none())
                to_send = ""

        except discord.Forbidden:
            # someone screwed up their permissions
            del log_queue[target]
            return
        except asyncio.CancelledError:
            return  # bot is terminating

    del log_queue[target]

