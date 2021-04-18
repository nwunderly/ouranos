import discord
import logging
import re
import time

from discord.ext import commands

from ouranos.bot import Ouranos
from ouranos.utils import database as db
from ouranos.utils.constants import EMOJI_WARN, EMOJI_MUTE, EMOJI_UNMUTE, EMOJI_KICK, EMOJI_BAN, EMOJI_UNBAN
from ouranos.utils.helpers import exact_timedelta


logger = logging.getLogger(__name__)


infraction_cache = {}
history_cache = {}
last_case_id_cache = {}


class LogEvent:
    def __init__(self, type, guild, user, mod, reason, note, duration):
        self.type = type
        self.guild = guild
        self.user = user
        self.mod = mod
        self.reason = reason
        self.note = note
        self.duration = duration

    async def dispatch(self):
        Ouranos.bot.dispatch('log', self)


class SmallLogEvent:
    def __init__(self, type, guild, user, infraction_id):
        self.type = type
        self.guild = guild
        self.user = user
        self.infraction_id = infraction_id

    async def dispatch(self):
        Ouranos.bot.dispatch('small_log', self)


async def get_case_id(guild_id):
    if guild_id in last_case_id_cache:
        misc = last_case_id_cache[guild_id]
    else:
        misc, _ = await db.MiscData.get_or_create(guild_id=guild_id)
    misc.last_case_id += 1
    await misc.save()
    infraction_id = misc.last_case_id
    last_case_id_cache[guild_id] = misc
    return infraction_id


async def new_infraction(guild_id, user_id, mod_id, type, reason, note, duration, active):
    infraction_id = await get_case_id(guild_id)
    created_at = time.time()
    ends_at = created_at + duration if duration else None
    infraction = await db.Infraction.create(
        guild_id=guild_id,
        infraction_id=infraction_id,
        user_id=user_id,
        mod_id=mod_id,
        type=type,
        reason=reason,
        note=note,
        created_at=created_at,
        ends_at=ends_at,
        active=active,
    )
    history, _ = await db.History.get_or_create(
        {'warn': [], 'mute': [], 'unmute': [], 'kick': [], 'ban': [], 'unban': [], 'active': []},
        guild_id=guild_id, user_id=user_id
    )
    history.__getattribute__(type).append(infraction_id)
    if active:
        history.active.append(infraction_id)
    await history.save()
    return infraction


async def get_infraction(guild_id, infraction_id):
    return await db.Infraction.get_or_none(guild_id=guild_id, infraction_id=infraction_id)


async def get_history(guild_id, user_id):
    return await db.History.get_or_none(guild_id=guild_id, user_id=user_id)


def format_log_message(emoji, title, infraction_id, duration, user, mod, reason, note):
    lines = [
        f"{emoji} **{title} (#{infraction_id})**\n",
        f"**User:** {user} (`{user.id}`)\n",
        f"**Duration:** {duration}\n" if duration else "",
        f"**Moderator:** {mod}\n",
        f"**Reason:** {reason}\n",
        f"**Note:** {note}\n",
    ]
    return "".join(lines)


def format_edited_log_message(content, **kwargs):
    split = content.split('\n')
    first_line = split[0] + '\n'
    split = split[1:]

    entry = {}
    pattern = re.compile(r'\*\*(\w+):\*\* (.*)')
    for line in split:
        match = pattern.match(line)
        entry[match.group(1).lower()] = match.group(2)

    entry.update(kwargs)
    return first_line + "".join(f"**{key.capitalize()}:** {value}\n" for key, value in entry.items())


def format_small_log_message(emoji, title, user, infraction_id):
    return f"{emoji} {title} for user {user} (#{infraction_id})"


async def new_log_message(guild, content):
    config = await db.get_config(guild)
    channel = guild.get_channel(config.modlog_channel_id)
    message = await channel.send(content)
    return message


async def edit_log_message(infraction, **kwargs):
    guild = Ouranos.bot.get_guild(infraction.guild_id)
    config = await db.get_config(guild)
    channel = guild.get_channel(config.modlog_channel_id)
    message = await channel.fetch_message(infraction.message_id)
    content = format_edited_log_message(message.content, **kwargs)
    await message.edit(content=content)
    return message


async def edit_infraction_and_message(infraction, **kwargs):
    if 'edited_by' in kwargs:
        edited_by = kwargs.pop('edited_by')
    else:
        edited_by = None
    k1, k2 = kwargs.copy(), kwargs.copy()
    if 'duration' in kwargs:
        duration = kwargs.pop('duration')
        ends_at = infraction.created_at + duration
        k1['ends_at'] = ends_at
        edit = f"(edited by {edited_by})" if edited_by else ''
        k2['duration'] = f"{exact_timedelta(duration)} {edit}"
    i = await db.edit_record(infraction, **k1)
    m = await edit_log_message(infraction, **k2)
    return i, m


async def has_active_infraction(guild_id, user_id, type):
    return await db.Infraction.exists(guild_id=guild_id, user_id=user_id, type=type)


async def deactivate_infractions(guild_id, user_id, type):
    history = await get_history(guild_id, user_id)
    if not history:
        return
    active = list(history.active)
    count = 0
    for infraction_id in history.active:
        infraction = await get_infraction(guild_id, infraction_id)
        if infraction.type == type:
            active.remove(infraction_id)
            await db.edit_record(history, active=active)
            await db.edit_record(infraction, active=False)
            count += 1
    return count


async def log_warn(guild, user, mod, reason, note, _):
    infraction = await new_infraction(guild.id, user.id, mod.id, 'warn', reason, note, None, False)
    content = format_log_message(EMOJI_WARN, 'MEMBER WARNED', infraction.infraction_id, None, user, mod, reason, note)
    message = await new_log_message(guild, content)
    await db.edit_record(infraction, message_id=message.id)


async def log_mute(guild, user, mod, reason, note, duration):
    infraction = await new_infraction(guild.id, user.id, mod.id, 'mute', reason, note, duration, True)
    duration = exact_timedelta(duration) if duration else None
    content = format_log_message(EMOJI_MUTE, 'MEMBER MUTED', infraction.infraction_id, duration, user, mod, reason, note)
    message = await new_log_message(guild, content)
    await db.edit_record(infraction, message_id=message.id)


async def log_unmute(guild, user, mod, reason, note, _):
    infraction = await new_infraction(guild.id, user.id, mod.id, 'unmute', reason, note, None, False)
    content = format_log_message(EMOJI_UNMUTE, 'MEMBER UNMUTED', infraction.infraction_id, None, user, mod, reason, note)
    message = await new_log_message(guild, content)
    await db.edit_record(infraction, message_id=message.id)


async def log_kick(guild, user, mod, reason, note, _):
    infraction = await new_infraction(guild.id, user.id, mod.id, 'kick', reason, note, None, False)
    content = format_log_message(EMOJI_KICK, 'MEMBER KICKED', infraction.infraction_id, None, user, mod, reason, note)
    message = await new_log_message(guild, content)
    await db.edit_record(infraction, message_id=message.id)


async def log_ban(guild, user, mod, reason, note, duration):
    infraction = await new_infraction(guild.id, user.id, mod.id, 'ban', reason, note, duration, True)
    duration = exact_timedelta(duration) if duration else None
    content = format_log_message(EMOJI_BAN, 'MEMBER BANNED', infraction.infraction_id, duration, user, mod, reason, note)
    message = await new_log_message(guild, content)
    await db.edit_record(infraction, message_id=message.id)


async def log_forceban(guild, user, mod, reason, note, duration):
    infraction = await new_infraction(guild.id, user.id, mod.id, 'ban', reason, note, duration, True)
    duration = exact_timedelta(duration) if duration else None
    content = format_log_message(EMOJI_BAN, 'USER FORCEBANNED', infraction.infraction_id, duration, user, mod, reason, note)
    message = await new_log_message(guild, content)
    await db.edit_record(infraction, message_id=message.id)


async def log_unban(guild, user, mod, reason, note, _):
    infraction = await new_infraction(guild.id, user.id, mod.id, 'unban', reason, note, None, False)
    content = format_log_message(EMOJI_UNBAN, 'USER UNBANNED', infraction.infraction_id, None, user, mod, reason, note)
    message = await new_log_message(guild, content)
    await db.edit_record(infraction, message_id=message.id)


async def log_mute_expire(guild, user, infraction_id):
    content = format_small_log_message(EMOJI_UNMUTE, 'Mute expired', user, infraction_id)
    await new_log_message(guild, content)


async def log_ban_expire(guild, user, infraction_id):
    content = format_small_log_message(EMOJI_UNBAN, 'Ban expired', user, infraction_id)
    await new_log_message(guild, content)


async def log_mute_persist(guild, user, infraction_id):
    content = format_small_log_message(EMOJI_MUTE, 'Mute persisted', user, infraction_id)
    await new_log_message(guild, content)
