import asyncio
import re
import time

import discord

from ouranos.bot import Ouranos
from ouranos.utils import db
from ouranos.utils.emojis import EMOJI_NOTE, EMOJI_WARN, EMOJI_MUTE, \
    EMOJI_UNMUTE, EMOJI_KICK, EMOJI_BAN, EMOJI_UNBAN, EMOJI_MASSBAN, BEE
from ouranos.utils.format import exact_timedelta
from ouranos.utils.errors import OuranosCommandError


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


class MassActionLogEvent:
    def __init__(self, type, guild, users, mod, reason, note, duration):
        self.type = type
        self.guild = guild
        self.users = users
        self.mod = mod
        self.reason = reason
        self.note = note
        self.duration = duration

    async def dispatch(self):
        Ouranos.bot.dispatch('mass_action_log', self)


case_id_lock = asyncio.Lock()


async def get_case_id(guild_id, count=1, increment=True):
    async with case_id_lock:
        infraction_ids = []

        if guild_id in db.last_case_id_cache:
            misc = db.last_case_id_cache[guild_id]

        else:
            misc, _ = await db.MiscData.get_or_create(guild_id=guild_id)
        for i in range(count):
            infraction_id = misc.last_case_id + 1
            if increment:
                misc.last_case_id += 1
            infraction_ids.append(infraction_id)

        await db.edit_record(misc)

    return infraction_ids[0] if count == 1 else infraction_ids


async def new_infraction(guild_id, user_id, mod_id, type, reason, note, duration, active, infraction_id=None):
    if not infraction_id:
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
        {'note': [], 'warn': [], 'mute': [], 'unmute': [], 'kick': [], 'ban': [], 'unban': [], 'active': []},
        guild_id=guild_id, user_id=user_id
    )
    history.__getattribute__(type).append(infraction_id)
    if active:
        history.active.append(infraction_id)
    await db.edit_record(history)  # runs save() and ensures cache is updated
    db.infraction_cache[guild_id, infraction_id] = infraction
    db.history_cache[guild_id, user_id] = history
    return infraction


async def new_infractions_bulk(guild_id, user_ids, mod_id, type, reason, note, duration, active, infraction_ids=None):
    if not infraction_ids:
        infraction_ids = await get_case_id(guild_id, count=len(user_ids))
    created_at = time.time()
    ends_at = created_at + duration if duration else None
    rng = [min(infraction_ids), max(infraction_ids)]
    await db.Infraction.bulk_create([
        db.Infraction(
            guild_id=guild_id,
            infraction_id=infraction_ids[i],
            user_id=user_id,
            mod_id=mod_id,
            type=type,
            reason=reason,
            note=note,
            created_at=created_at,
            ends_at=ends_at,
            active=active,
            bulk_infraction_id_range=rng,
        ) for i, user_id in enumerate(user_ids)
    ])
    for i, user_id in enumerate(user_ids):
        infraction_id = infraction_ids[i]
        history, _ = await db.History.get_or_create(
            {'note': [], 'warn': [], 'mute': [], 'unmute': [], 'kick': [], 'ban': [], 'unban': [], 'active': []},
            guild_id=guild_id, user_id=user_id
        )
        history.__getattribute__(type).append(infraction_id)
        if active:
            history.active.append(infraction_id)
        await db.edit_record(history)  # runs save() and ensures cache is updated
    return infraction_ids


async def get_infraction(guild_id, infraction_id):
    if i := db.infraction_cache.get((guild_id, infraction_id)):
        return i
    return await db.Infraction.get_or_none(guild_id=guild_id, infraction_id=infraction_id)


async def get_infractions_bulk(guild_id, infraction_ids):
    infractions = []
    remaining_ids = list(infraction_ids)

    # check cache
    for infraction_id in infraction_ids:
        if inf := db.infraction_cache.get((guild_id, infraction_id)):
            infractions.append(inf)
            remaining_ids.remove(inf.infraction_id)

    # query the db
    if remaining_ids:
        async for infraction in db.Infraction.filter(infraction_id__in=remaining_ids):
            infractions.append(infraction)

    # sort and return
    return sorted(infractions, key=lambda inf: inf.infraction_id)


async def get_history(guild_id, user_id):
    if h := db.history_cache.get((guild_id, user_id)):
        return h
    return await db.History.get_or_none(guild_id=guild_id, user_id=user_id)


def format_log_message(emoji, title, infraction_id, duration, user, mod, reason, note):
    lines = [
        f"{emoji} **{title} (#{infraction_id})**\n",
        f"**User:** {user} (`{user.id}`)\n",
        f"**Duration:** {duration}\n" if duration else "",
        f"**Moderator:** {mod}\n",
        f"**Reason:** {reason}\n",
        f"**Note:** {note}\n" if note else "",
    ]
    return "".join(lines)


def format_edited_log_message(content, **kwargs):
    order = ['user', 'users', 'duration', 'moderator', 'reason', 'note']
    split = content.split('\n')
    first_line = split[0] + '\n'
    split = split[1:]

    entry = {}
    pattern = re.compile(r'\*\*(\w+):\*\* (.*)')
    for line in split:
        match = pattern.match(line)
        entry[match.group(1).lower()] = match.group(2)

    entry.update(kwargs)
    return first_line + "".join(
        f"**{key.capitalize()}:** {entry[key]}\n" for key in order if (
            key in entry and (key != 'duration' or entry[key] is not None)
        ))


def format_small_log_message(emoji, title, user, infraction_id):
    return f"{emoji} {title} for user {user} (#{infraction_id})"


def format_mass_action_log_message(emoji, title, infraction_id_range, duration, user_count, mod, reason, note):
    infraction_id_start, infraction_id_end = infraction_id_range
    if infraction_id_start != infraction_id_end:
        _range = f"#{infraction_id_start}-{infraction_id_end}"
    else:
        _range = f"#{infraction_id_start}"
    lines = [
        f"{emoji} **{title} ({_range})**\n",
        f"**Users:** {user_count}\n",
        f"**Duration:** {duration}\n" if duration else "",
        f"**Moderator:** {mod}\n",
        f"**Reason:** {reason}\n",
        f"**Note:** {note}\n",
    ]
    return "".join(lines)


async def new_log_message(guild, content):
    config = await db.get_config(guild)
    channel = guild.get_channel(config.modlog_channel_id if config else 0)
    if channel:
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
        edit = f"(edited by {kwargs.pop('edited_by')})"
    else:
        edit = ''

    k1, k2 = kwargs.copy(), kwargs.copy()
    if 'duration' in kwargs:
        duration = kwargs.pop('duration')
        k1['ends_at'] = infraction.created_at + duration if duration else None
        d = exact_timedelta(duration) if duration else 'permanent'
        k2['duration'] = f"{d} {edit}"
    if 'reason' in kwargs:
        r = kwargs.pop('reason')
        k1['reason'] = k2['reason'] = f"{r} {edit}"
    if 'note' in kwargs:
        n = kwargs.pop('note')
        k1['note'] = k2['note'] = f"{n} {edit}"

    i = await db.edit_record(infraction, **k1)
    try:
        m = await edit_log_message(infraction, **k2)
    except discord.HTTPException as e:
        raise OuranosCommandError(f"I edited the infraction, but was unable to edit the modlog message "
                                  f"({e.text.lower().capitalize()}).")
    return i, m


async def edit_infractions_and_messages_bulk(infractions, linked=True, **kwargs):
    """Edits a set of infractions. All must be linked to the same log message."""
    inf = infractions[0]

    for i in infractions:
        if i.type != inf.type:
            raise OuranosCommandError("Infraction type mismatch during bulk edit.")
        if linked:
            if i.message_id != inf.message_id:
                raise OuranosCommandError("Infraction message_id mismatch during bulk edit.")
            elif i.created_at != inf.created_at:
                raise OuranosCommandError("Infraction created_at mismatch during bulk edit.")

    if 'edited_by' in kwargs:
        edit = f"(edited by {kwargs.pop('edited_by')})"
    else:
        edit = ''

    k1, k2 = kwargs.copy(), kwargs.copy()
    if 'duration' in kwargs:
        duration = kwargs.pop('duration')
        k1['ends_at'] = inf.created_at + duration if duration else None
        d = exact_timedelta(duration) if duration else 'permanent'
        k2['duration'] = f"{d} {edit}"
    if 'reason' in kwargs:
        r = kwargs.pop('reason')
        k1['reason'] = k2['reason'] = f"{r} {edit}"
    if 'note' in kwargs:
        n = kwargs.pop('note')
        k1['note'] = k2['note'] = f"{n} {edit}"

    i = await db.edit_records_bulk(infractions, **k1)

    if linked:
        try:
            m = await edit_log_message(inf, **k2)
        except discord.HTTPException as e:
            raise OuranosCommandError(f"I edited the infractions, but was unable to edit the modlog message "
                                      f"({e.text.lower()}).")
        return i, m

    # edit a batch of messages
    else:
        count = 0
        skip = set()
        for inf in infractions:
            if inf.infraction_id in skip:
                continue

            # make sure we only edit each message once
            if inf.bulk_infraction_id_range:
                start, end = inf.bulk_infraction_id_range
                for _i_id in range(start, end+1):
                    skip.add(_i_id)

            # actually edit now
            try:
                await edit_log_message(inf, **k2)
                count += 1
            except discord.HTTPException as e:
                raise OuranosCommandError(f"I edited the infractions, but was unable to edit the modlog message "
                                          f"for #{inf.infraction_id} ({e.text.lower()}).")
        return i, count


async def has_active_infraction(guild_id, user_id, type):
    # if (exists := db.active_infraction_exists_cache.get((guild_id, user_id))) is not None:
    #     return exists
    history = await get_history(guild_id, user_id)
    if history:
        for i in getattr(history, type):
            if i in history.active:
                # db.active_infraction_exists_cache[guild_id, user_id] = True
                return True
    # db.active_infraction_exists_cache[guild_id, user_id] = False
    return False


async def deactivate_infractions(guild_id, user_id, type):
    now = time.time()
    history = await get_history(guild_id, user_id)
    if not history:
        return
    active = list(history.active)
    count = 0
    for infraction_id in history.active:
        infraction = await get_infraction(guild_id, infraction_id)
        if infraction.type == type and infraction.created_at < now:
            active.remove(infraction_id)
            await db.edit_record(history, active=active)
            await db.edit_record(infraction, active=False)
            count += 1
    return count


async def log_note(guild, user, mod, reason, _, __):
    infraction = await new_infraction(guild.id, user.id, mod.id, 'note', reason, None, None, False)
    content = format_log_message(EMOJI_NOTE, 'NOTE CREATED', infraction.infraction_id, None, user, mod, reason, None)
    message = await new_log_message(guild, content)
    await db.edit_record(infraction, message_id=message.id)


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


async def log_beemo_ban(guild, user, _):
    content = f"{BEE} {user} (`{user.id}`) has been banned by Beemo."
    await new_log_message(guild, content)


async def log_mass_ban(guild, users, mod, reason, note, duration):
    infraction_ids = await get_case_id(guild.id, count=len(users))
    user_ids = [user.id for user in users]

    await new_infractions_bulk(guild.id, user_ids, mod.id, 'ban', reason, note, duration, True, infraction_ids)

    duration = exact_timedelta(duration) if duration else None
    content = format_mass_action_log_message(
        EMOJI_MASSBAN, 'USERS MASS-BANNED', (infraction_ids[0], infraction_ids[-1]), duration, len(users), mod, reason, note)
    message = await new_log_message(guild, content)

    await db.Infraction.filter(infraction_id__in=infraction_ids).update(message_id=message.id)


async def log_mass_mute(guild, users, mod, reason, note, duration):
    infraction_ids = await get_case_id(guild.id, count=len(users))
    user_ids = [user.id for user in users]

    await new_infractions_bulk(guild.id, user_ids, mod.id, 'mute', reason, note, duration, True, infraction_ids)

    duration = exact_timedelta(duration) if duration else None
    content = format_mass_action_log_message(
        EMOJI_MUTE, 'USERS MASS-MUTED', (infraction_ids[0], infraction_ids[-1]), duration, len(users), mod, reason, note)
    message = await new_log_message(guild, content)

    await db.Infraction.filter(infraction_id__in=infraction_ids).update(message_id=message.id)
