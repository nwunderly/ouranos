import asyncio
import discord
import math
import time

from datetime import datetime, timedelta
from discord.ext import commands
from discord.ext.commands import Cog

from ouranos.utils import dispatch


# CONFIG = 'src/neptuneshelper/config/logchamp.json'
CONFIG_FILE = './logchamp.json'
EVENTS = [
    'member_join',
]

SECOND = 1
MINUTE = SECOND*60
HOUR = MINUTE*60
DAY = HOUR*24
WEEK = DAY*7
MONTH = DAY*30
YEAR = DAY*365


def s(n):
    return 's' if n != 1 else ''


def approximate_timedelta(dt):
    if isinstance(dt, timedelta):
        dt = dt.total_seconds()
    if dt >= YEAR:
        t = f"{int(_y := dt // YEAR)} year" + s(_y)
    elif dt >= MONTH:
        t = f"{int(_mo := dt // MONTH)} month" + s(_mo)
    elif dt >= WEEK:
        t = f"{int(_w := dt // WEEK)} week" + s(_w)
    elif dt >= DAY:
        t = f"{int(_d := dt // DAY)} day" + s(_d)
    elif dt >= HOUR:
        t = f"{int(_h := dt // HOUR)} hour" + s(_h)
    elif dt >= MINUTE:
        t = f"{int(_m := dt // MINUTE)} minute" + s(_m)
    else:
        t = f"{int(_s := dt // SECOND)} second" + s(_s)

    return t


def timestamp():
    # return f"**<t:{math.floor(time.time())}:T>**"
    # return f"[**<t:{math.floor(time.time())}:f>**]"
    return datetime.now().strftime("`[%H:%M:%S]`")


def ago(t):
    return approximate_timedelta(datetime.utcnow() - t)


def format_user(u):
    if not u:
        return None
    if isinstance(u, dict):
        return f"{u.get('username')}#{u.get('discriminator')} (`{u.get('id')}`)"
    else:
        return f"{u} (`{u.id}`)"


def format_log(guild, event, message):
    emoji = dispatch.get_log_emoji(event)
    message = f"{timestamp()} {emoji} {message}"
    return message


class Logging(Cog):
    """LOGCHAMP"""
    def __init__(self, bot):
        self.bot = bot

    async def send_log_message(self, guild, event, message):
        if not guild:
            return
        message = format_log(guild, event, message)
        await dispatch.send_message(guild, event, message)

    @Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        content = f"{format_user(member)} joined the server (created about {ago(member.created_at)} ago)"
        await self.send_log_message(guild, 'member_join', content)

    @Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        content = f"{format_user(member)} left the server (joined about {ago(member.joined_at)} ago)"
        await self.send_log_message(guild, 'member_remove', content)

    @Cog.listener()
    async def on_raw_message_edit(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        after = payload.data.get('content')
        if payload.cached_message:
            if payload.cached_message.content == after:
                return
            before = payload.cached_message.content
            author = payload.cached_message.author
        else:
            before = None
            author = payload.data.get('author')
            author = self.bot.get_user(author) or author
        cid = payload.channel_id
        created_at = discord.utils.snowflake_time(payload.message_id)
        content = f"message by {format_user(author)} in <#{cid}> has been edited (sent about {ago(created_at)} ago)\n" \
                  f"**Old**: {before}\n" \
                  f"**New**: {after}"
        await self.send_log_message(guild, 'message_edit', content)

    @Cog.listener()
    async def on_raw_message_delete(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        if payload.cached_message:
            before_msg = payload.cached_message
            before = payload.cached_message.content
            author = payload.cached_message.author
        else:
            before_msg = before = author = None
        cid = payload.channel_id
        created_at = discord.utils.snowflake_time(payload.message_id)
        content = f"message by {format_user(author)} in <#{cid}> has been deleted (sent about {ago(created_at)} ago)\n" \
                  f"**Content**: {before}"
        if before_msg and before_msg.attachments:
            urls = ', '.join(a.url for a in before_msg.attachments)
            content += f"\n({urls})"
        await self.send_log_message(guild, 'message_delete', content)


def setup(bot):
    bot.add_cog(Logging(bot))
