import argparse
import asyncio
import re
import time
import typing
import shlex

import discord
from discord.ext import commands
from discord.ext import tasks
from collections import defaultdict
from typing import Optional
from loguru import logger

from ouranos.cog import Cog
from ouranos.utils import checks
from ouranos.utils import database as db
from ouranos.utils import modlog_utils as modlog
from ouranos.utils.modlog_utils import LogEvent, SmallLogEvent
from ouranos.utils.constants import TICK_RED, TICK_GREEN, TICK_YELLOW, OK_HAND, THUMBS_UP, PRAY, HAMMER, CLAP
from ouranos.utils.converters import Duration, UserID, MutedUser, BannedUser, Reason, RequiredReason, NotInt
from ouranos.utils.helpers import exact_timedelta
from ouranos.utils.errors import OuranosCommandError, ModerationError, UserNotInGuild, NotConfigured, \
    BotMissingPermission, BotRoleHierarchyError, ModActionOnMod, UnexpectedError


ALERT_FORMAT = {
    'warn': 'warned in',
    'mute': 'muted in',
    'unmute': 'unmuted in',
    'kick': 'kicked from',
    'ban': 'banned from',
    'unban': '',
}


def format_alert_dm(guild, user, infraction_type, duration=None, reason=None, auto=False):
    actioned_in = ALERT_FORMAT[infraction_type]
    if not actioned_in:
        return None
    msg = f"Hello {user.name}, you have been {'automatically ' if auto else ''}{actioned_in} guild **{guild.name}** ({guild.id}).\n"
    if duration:
        msg += f"**Duration**: {exact_timedelta(duration)}\n"
    msg += f"**Reason**: {reason}"
    return msg


def notified(delivered):
    return f"*User was {'' if delivered else 'not '}notified.*" if delivered is not None else ""


async def try_send(user, message):
    try:
        await user.send(message)
        return True
    except discord.DiscordException:
        return False


class Moderation(Cog):
    """Moderation commands."""
    def __init__(self, bot):
        self.bot = bot
        self.check_timers.start()
        self.handling = set()

    def cog_unload(self):
        self.check_timers.stop()

    @tasks.loop(seconds=10)
    async def check_timers(self):
        await self.bot.wait_until_ready()
        t0 = time.monotonic()

        async def _lift_infraction(s, cb, g, u, i):
            await asyncio.sleep(s)
            await cb(g, u, i)
            self.handling.remove(i.infraction_id)

        types = {
            'mute': self._do_auto_unmute,
            'ban': self._do_auto_unban
        }
        now = time.time()
        limit = now + 30
        n = 0

        for infraction in await db.Infraction.filter(active=True, ends_at__lt=limit):
            guild = self.bot.get_guild(infraction.guild_id)
            if infraction.type in types and infraction.infraction_id not in self.handling and guild:
                self.handling.add(infraction.infraction_id)
                callback = types[infraction.type]
                sleep = infraction.ends_at - now
                n += 1
                await self.bot.run_in_background(
                    _lift_infraction(sleep, callback, guild, infraction.user_id, infraction))

        dt = time.monotonic() - t0
        if n:
            logger.info(f"Completed expired infraction check in {dt} seconds, queued {n} tasks")

    @Cog.listener()
    async def on_member_join(self, member):
        config = await db.get_config(member.guild)
        if not (config and config.mute_role_id):
            return
        history = await modlog.get_history(member.guild.id, member.id)
        if history and history.active:
            for i in history.active:
                if i in history.mute:
                    infraction = await modlog.get_infraction(member.guild.id, i)
                    return await self._do_auto_mute(member.guild, member, infraction)

    @Cog.listener()
    async def on_member_remove(self, member):
        config = await db.get_config(member.guild)
        if not (config and config.mute_role_id):
            return
        role = member.guild.get_role(config.mute_role_id)
        if role in member.roles and not await modlog.has_active_infraction(member.guild.id, member.id, 'mute'):
            reason = "Infraction created automatically."
            note = "Muted user left guild but did not have any active mute infractions."
            await LogEvent('mute', member.guild, member, self.bot.user, reason, note, None).dispatch()

    async def _do_warn(self, guild, user, mod, reason, note=None):
        """Applies a warn to a user and dispatches the event to the modlog."""
        config = await db.get_config(guild)
        member = await self.bot.get_or_fetch_member(guild, user.id)

        # some checks to make sure we can actually do this
        if not member:
            raise UserNotInGuild(user)
        if await checks.is_server_mod(member):
            raise ModActionOnMod

        if (not config) or config.dm_on_infraction:
            message = format_alert_dm(guild, user, 'warn', reason=reason)
            delivered = await try_send(user, message)
        else:
            delivered = None

        await LogEvent('warn', guild, user, mod, reason, note, None).dispatch()
        return delivered

    async def _do_mute(self, guild, user, mod, reason, note, audit_reason, duration=None):
        """Applies a mute to a user and dispatches the event to the modlog."""
        config = await db.get_config(guild)
        member = await self.bot.get_or_fetch_member(guild, user.id)
        role = guild.get_role(config.mute_role_id if config else 0)

        # some checks to make sure we can actually do this
        if not member:
            raise UserNotInGuild(user)
        if not role:
            raise NotConfigured('mute_role')
        if role in member.roles:
            raise ModerationError('User is already muted.')
        if not guild.me.guild_permissions.manage_roles:
            raise BotMissingPermission('Manage Roles')
        if not guild.me.top_role > role:
            raise BotRoleHierarchyError
        if await checks.is_server_mod(member):
            raise ModActionOnMod

        # add the role
        await member.add_roles(role, reason=audit_reason)

        # notify the user if the setting is enabled
        if (not config) or config.dm_on_infraction:
            message = format_alert_dm(guild, user, 'mute', reason=reason, duration=duration)
            delivered = await try_send(user, message)
        else:
            delivered = None

        # dispatch the modlog event and return to the command
        await LogEvent('mute', guild, user, mod, reason, note, duration).dispatch()
        return delivered

    async def _do_mute_duration_edit(self, guild, user, new_duration, edited_by):
        """Edits the duration of an existing mute infraction."""
        history = await modlog.get_history(guild.id, user.id)
        if not history:
            raise UnexpectedError("Attempted to edit the mute duration of a user with empty history.")

        infraction = None
        for i in reversed(history.active):
            if i in history.mute:
                infraction = await modlog.get_infraction(guild.id, i)
                break

        if not infraction:
            raise UnexpectedError("Attempted to edit the mute duration of a user with no active mute infractions.")

        await modlog.edit_infraction_and_message(infraction, duration=new_duration, edited_by=edited_by)
        return infraction.infraction_id

    async def _do_unmute(self, guild, user, mod, reason, note, audit_reason):
        """Lifts a user's mute and dispatches the event to the modlog."""
        config = await db.get_config(guild)
        member = await self.bot.get_or_fetch_member(guild, user.id)
        role = guild.get_role(config.mute_role_id if config else 0)

        # some checks to make sure we can actually do this
        if not member:
            raise UserNotInGuild(user)
        if not role:
            raise NotConfigured('mute_role')
        if not guild.me.guild_permissions.manage_roles:
            raise BotMissingPermission('Manage Roles')
        if not guild.me.top_role > role:
            raise BotRoleHierarchyError
        if await checks.is_server_mod(member):
            raise ModActionOnMod

        # remove the role
        await member.remove_roles(role, reason=audit_reason)

        # notify the user if the setting is enabled
        if (not config) or config.dm_on_infraction:
            message = format_alert_dm(guild, user, 'unmute', reason=reason)
            delivered = await try_send(user, message)
        else:
            delivered = None

        # mark any mutes for this user as inactive
        await self.bot.run_in_background(
            modlog.deactivate_infractions(guild.id, user.id, 'mute'))

        # dispatch the modlog event and return to the command
        await LogEvent('unmute', guild, user, mod, reason, note, None).dispatch()
        return delivered

    async def _do_kick(self, guild, user, mod, reason, note, audit_reason):
        """Applies a kick to a user and dispatches the event to the modlog."""
        config = await db.get_config(guild)
        member = await self.bot.get_or_fetch_member(guild, user.id)

        # some checks to make sure we can actually do this
        if not member:
            raise UserNotInGuild(user)
        if not guild.me.guild_permissions.kick_members:
            raise BotMissingPermission('Kick Members')
        if not guild.me.top_role > member.top_role:
            raise BotRoleHierarchyError
        if await checks.is_server_mod(member):
            raise ModActionOnMod

        # notify the user if the setting is enabled
        # this one has to be done before kicking (for obvious reasons)
        if (not config) or config.dm_on_infraction:
            message = format_alert_dm(guild, user, 'kick', reason=reason)
            delivered = await try_send(user, message)
        else:
            delivered = None

        # kick the user
        await member.kick(reason=audit_reason)

        # dispatch the modlog event and return to the command
        await LogEvent('kick', guild, user, mod, reason, note, None).dispatch()
        return delivered

    async def _do_ban(self, guild, user, mod, reason, note, audit_reason, duration=None):
        """Lifts a user's ban and dispatches the event to the modlog."""
        config = await db.get_config(guild)
        member = await self.bot.get_or_fetch_member(guild, user.id)

        # some checks to make sure we can actually do this
        if not guild.me.guild_permissions.ban_members:
            raise BotMissingPermission('Ban Members')
        if member:
            if not guild.me.top_role > member.top_role:
                raise BotRoleHierarchyError
            if await checks.is_server_mod(member):
                raise ModActionOnMod

        # notify the user if the setting is enabled
        # this one has to be done before banning (for obvious reasons)
        if (not config) or config.dm_on_infraction:
            if member:
                message = format_alert_dm(guild, user, 'ban', reason=reason, duration=duration)
                delivered = await try_send(user, message)
            else:
                delivered = None
        else:
            delivered = None

        # set up a task that waits a few moments for discord to dispatch the event.
        # this makes printing the user look pretty without having to fetch.
        async def _wait():
            try:
                def check(_, _u):
                    return _u.id == user.id
                _, _u = await self.bot.wait_for('member_ban', check=check, timeout=1)
                return _u
            except asyncio.TimeoutError:
                pass

        # ban the user
        coro = guild.ban(user, reason=audit_reason, delete_message_days=0)
        if member:
            # regular ban
            await coro
        else:
            # forceban case
            user = (await asyncio.gather(_wait(), coro))[0] or user

        # dispatch the modlog event and return to the command
        type = ('force' if not member else '') + 'ban'
        await LogEvent(type, guild, user, mod, reason, note, duration).dispatch()
        return user, delivered, not bool(member)

    async def _do_ban_duration_edit(self, guild, user, new_duration, edited_by):
        """Edits the duration of an existing ban infraction."""
        history = await modlog.get_history(guild.id, user.id)
        if not history:
            raise UnexpectedError("Attempted to edit the ban duration of a user with empty history.")

        infraction = None
        for i in reversed(history.active):
            if i in history.ban:
                infraction = await modlog.get_infraction(guild.id, i)
                break

        if not infraction:
            raise UnexpectedError("Attempted to edit the ban duration of a user with no active ban infractions.")

        await modlog.edit_infraction_and_message(infraction, duration=new_duration, edited_by=edited_by)
        return infraction.infraction_id

    async def _do_unban(self, guild, user, mod, reason, note, audit_reason):
        """Removes a ban from a user and dispatches the event to the modlog."""
        # check to make sure we can actually do this
        if not guild.me.guild_permissions.ban_members:
            raise BotMissingPermission('Ban Members')

        # unban the user
        await guild.unban(user, reason=audit_reason)

        # mark any bans for this user as inactive
        await self.bot.run_in_background(
            modlog.deactivate_infractions(guild.id, user.id, 'ban'))

        # dispatch the modlog event and return to the command
        await LogEvent('unban', guild, user, mod, reason, note, None).dispatch()

    async def _do_auto_mute(self, guild, user, infraction):
        """Applies a mute to a user without dispatching the modlog event.
        Used for reassigning mute role when a user rejoins the server before their mute expires.
        """
        config = await db.get_config(guild)
        member = await self.bot.get_or_fetch_member(guild, user.id)
        role = guild.get_role(config.mute_role_id if config else 0)
        infraction_id = infraction.infraction_id

        # make sure we can actually do this
        can_mute = bool(member) \
            and bool(role) \
            and guild.me.guild_permissions.manage_roles \
            and guild.me.top_role > role

        if can_mute:
            # add the role
            await member.add_roles(role, reason=f'Active mute (#{infraction_id})')

            # dispatch the modlog event
            await SmallLogEvent('mute-persist', guild, user, infraction_id).dispatch()

        return can_mute


    async def _do_auto_unmute(self, guild, user_id, infraction):
        """Removes a mute from a user without dispatching the modlog event.
        Used for handling expired mutes without creating an infraction.
        """
        config = await db.get_config(guild)
        member = await self.bot.get_or_fetch_member(guild, user_id)
        role = guild.get_role(config.mute_role_id if config else 0)
        infraction_id = infraction.infraction_id

        # make sure we can actually do this
        can_unmute = bool(member) \
            and bool(role) \
            and guild.me.guild_permissions.manage_roles \
            and guild.me.top_role > role

        if can_unmute:
            # remove the role
            await member.remove_roles(role, reason=f'Mute expired (#{infraction_id})')

            # dispatch the modlog event
            await SmallLogEvent('mute-expire', guild, member, infraction_id).dispatch()

        # even if we don't have any permissions, mark any mutes for this user as inactive
        # so we don't keep trying to unmute.
        await self.bot.run_in_background(
            modlog.deactivate_infractions(guild.id, user_id, 'mute'))

        return can_unmute

    async def _do_auto_unban(self, guild, user_id, infraction):
        """Removes a ban from a user without dispatching the modlog event.
        Used for handling expired bans without creating an infraction.
        """
        infraction_id = infraction.infraction_id

        # make sure we can actually do this
        can_unban = guild.me.guild_permissions.ban_members

        if can_unban:
            # remove the role
            ban = await guild.fetch_ban(discord.Object(user_id))
            await guild.unban(ban.user, reason=f'Ban expired (#{infraction_id})')

            # dispatch the modlog event
            await SmallLogEvent('ban-expire', guild, ban.user, infraction_id).dispatch()

        # even if we don't have any permissions, mark any bans for this user as inactive
        # so we don't keep trying to unban.
        await self.bot.run_in_background(
            modlog.deactivate_infractions(guild.id, ban.user.id, 'ban'))

        return can_unban

    @commands.command()
    @checks.server_mod()
    async def warn(self, ctx, user: discord.Member, *, reason: RequiredReason):
        """Applies a warning to a user.

        Sends the user a DM and logs this action to the guild's modlog if configured to do so.
        """
        reason, note, _ = reason or (None, None, None)
        delivered = await self._do_warn(guild=ctx.guild, user=user, mod=ctx.author, reason=reason, note=note)
        await ctx.send(f"{THUMBS_UP} Warned **{user}**. {notified(delivered)}")

    @commands.command()
    @checks.server_mod()
    async def mute(self, ctx, user: discord.Member, duration: Optional[Duration], *, reason: Reason = None):
        """Mutes a user using the guild's configured mute role.

        Sends the user a DM and logs this action to the guild's modlog if configured to do so.
        """
        reason, note, audit_reason = reason or (None, None, None)
        audit_reason = audit_reason or Reason.format_reason(ctx)
        dt = exact_timedelta(duration) if duration else "permanent"

        try:
            muted_user, has_role = await MutedUser().convert(ctx, str(user.id))
        except commands.BadArgument:
            muted_user, has_role = None, None

        # if already muted, edit the duration
        if muted_user and has_role:
            # first make sure they have an infraction. it's hard to edit an infraction that doesn't exist.
            if await modlog.has_active_infraction(ctx.guild.id, user.id, 'mute'):
                i = await self._do_mute_duration_edit(
                    guild=ctx.guild, user=user, new_duration=duration, edited_by=ctx.author)
                await ctx.send(f"{TICK_YELLOW} User is already muted (#{i}), changed duration instead ({dt}).")

            # just kidding, we couldn't find an infraction. let's see if they want to create one.
            # note: we ask for a confirmation so things don't break when two infractions go through simultaneously
            else:
                await ctx.confirm_action(f"{TICK_YELLOW} This user appears to have this guild's mute role, "
                                         f"but does not have any active mute infractions. "
                                         f"Would you like to create an infraction?")
                await LogEvent('mute', ctx.guild, user, ctx.author, reason, note, duration).dispatch()
                await ctx.send(OK_HAND)

        # otherwise, mute the user like normal
        else:
            delivered = await self._do_mute(
                guild=ctx.guild, user=user, mod=ctx.author, reason=reason, note=note, audit_reason=audit_reason, duration=duration)
            await ctx.send(f"{OK_HAND} Muted **{user}** ({dt}). {notified(delivered)}")

    @commands.command()
    @checks.server_mod()
    async def unmute(self, ctx, user: MutedUser, *, reason: Reason = None):
        """Unmutes a user using the guild's configured mute role.

        Sends the user a DM and logs this action to the guild's modlog if configured to do so.
        """
        user, has_role = user
        reason, note, audit_reason = reason or (None, None, None)
        audit_reason = audit_reason or Reason.format_reason(ctx)

        # actually unmute them
        if has_role:
            delivered = await self._do_unmute(
                guild=ctx.guild, user=user, mod=ctx.author, reason=reason, note=note, audit_reason=audit_reason)
            await ctx.send(f"{PRAY} Unmuted **{user}**. {notified(delivered)}")

        # remove infraction from database if one was found but they're not muted.
        else:
            count = await modlog.deactivate_infractions(ctx.guild.id, user.id, 'mute')
            p = await self.bot.prefix(ctx.message)
            _s, _these = ('s', 'these') if count > 1 else ('', 'this')
            await ctx.send(f"{TICK_YELLOW} This user does not seem to have this guild's mute role, "
                           f"but I found {count} active mute infraction{_s} in my database.\n"
                           f"I marked {_these} infraction{_s} as inactive to account for this discrepancy. "
                           f"`{p}history {user.id}` should now show no active mutes.")

    @commands.command()
    @checks.server_mod()
    async def kick(self, ctx, user: discord.Member, *, reason: Reason = None):
        """Kicks a user from the guild.

        Sends the user a DM and logs this action to the guild's modlog if configured to do so.
        """
        reason, note, audit_reason = reason or (None, None, None)
        audit_reason = audit_reason or Reason.format_reason(ctx)
        delivered = await self._do_kick(
            guild=ctx.guild, user=user, mod=ctx.author, reason=reason, note=note, audit_reason=audit_reason)
        await ctx.send(f"{CLAP} Kicked **{user}**. {notified(delivered)}")

    @commands.command()
    @checks.server_mod()
    async def ban(self, ctx, user: UserID, duration: Optional[Duration], *, reason: Reason = None):
        """Bans a user from the guild.

        This will also work if the user is not in the server.

        Sends the user a DM and logs this action to the guild's modlog if configured to do so.
        """
        reason, note, audit_reason = reason or (None, None, None)
        audit_reason = audit_reason or Reason.format_reason(ctx)
        dt = exact_timedelta(duration) if duration else "permanent"

        try:
            banned_user, banned_in_guild = await BannedUser().convert(ctx, str(user.id))
        except commands.BadArgument:
            banned_user, banned_in_guild = None, None

        # if already banned, edit the duration
        if banned_user and banned_in_guild:
            # first make sure they have an infraction. it's hard to edit an infraction that doesn't exist.
            if await modlog.has_active_infraction(ctx.guild.id, user.id, 'ban'):
                i = await self._do_ban_duration_edit(
                    guild=ctx.guild, user=user, new_duration=duration, edited_by=ctx.author)
                await ctx.send(f"{TICK_YELLOW} User is already banned (#{i}), changed duration instead ({dt}).")

            # just kidding, we couldn't find an infraction. let's see if they want to create one.
            # note: we ask for a confirmation so things don't break when two infractions go through simultaneously
            else:
                ctx.confirm_action(f"{TICK_YELLOW} This user appears to be banned from this guild, "
                                   f"but does not have any active ban infractions. "
                                   f"Would you like to create an infraction?")
                await LogEvent('ban', ctx.guild, user, ctx.author, reason, note, duration).dispatch()
                await ctx.send(OK_HAND)

        # we didn't seem to find anything weird, so let's just ban!
        else:
            user, delivered, force = await self._do_ban(
                guild=ctx.guild, user=user, mod=ctx.author, reason=reason, note=note, audit_reason=audit_reason, duration=duration)
            banned = 'Forcebanned' if force else 'Banned'
            await ctx.send(f"{HAMMER} {banned} **{user}** ({dt}). {notified(delivered)}")

    @commands.command()
    @checks.server_mod()
    async def unban(self, ctx, user: BannedUser, *, reason: Reason = None):
        """Unbans a user previously banned in this guild.

        Sends the user a DM and logs this action to the guild's modlog if configured to do so.
        """
        ban, banned_in_guild = user
        user = ban.user
        reason, note, audit_reason = reason or (None, None, None)
        audit_reason = audit_reason or Reason.format_reason(ctx)

        # actually unban them
        if banned_in_guild:
            await self._do_unban(
                guild=ctx.guild, user=user, mod=ctx.author, reason=reason, note=note, audit_reason=audit_reason)
            await ctx.send(f"{PRAY} Unbanned **{user}**.")

        # remove infraction from database if one was found but they're not banned.
        else:
            count = await modlog.deactivate_infractions(ctx.guild.id, user.id, 'ban')
            p = await self.bot.prefix(ctx.message)
            s, these = ('s', 'these') if count != 1 else ('', 'this')
            await ctx.send(f"{TICK_YELLOW} This user does not seem to be in this guild's ban list, "
                           f"but I found {count} active ban infraction{s} in my database.\n"
                           f"I marked {these} infraction{s} as inactive to account for this discrepancy. "
                           f"`{p}history {user.id}` should now show no active bans.")

    async def _do_removal(self, ctx, limit, check=None, channel=None, **kwargs):
        if limit >= 200:
            await ctx.confirm_action(f"This will delete up to {limit} messages. Are you sure? (y/n)")
        if limit < 1:
            raise OuranosCommandError("Not enough messages to search!")
            
        def real_check(m):
            return m != ctx.message and (check(m) if check else True)

        messages = await (channel or ctx.channel).purge(limit=limit+1, check=real_check, **kwargs)

        count = len(messages)
        authors = defaultdict(lambda: 0)
        for m in messages:
            authors[str(m.author.name)] += 1

        s = 's'if count != 1 else ''
        response = f"{TICK_GREEN} Removed {count} message{s}."
        response += "```yaml\n" + '\n'.join((f"{a}: {n}" for a, n in authors.items())) + "\n```"
        await ctx.send(response, delete_after=10)

    @commands.group(aliases=['rm', 'purge', 'clean'], invoke_without_command=True)
    @checks.server_mod()
    async def remove(self, ctx, limit: int):
        """Bulk delete messages from a channel."""
        await self._do_removal(ctx, limit)

    @remove.command(name='user', aliases=['by'])
    @checks.server_mod()
    async def rm_user(self, ctx, user: UserID, limit: int):
        """Remove messages by a particular user."""
        await self._do_removal(ctx, limit, lambda m: m.author == user)

    @remove.command(name='channel', aliases=['in'])
    @checks.server_mod()
    async def rm_channel(self, ctx, channel: discord.TextChannel, limit: int):
        """Remove messages in another channel."""
        await self._do_removal(ctx, limit=limit, channel=channel)

    @remove.command(name='bot', aliases=['bots'])
    @checks.server_mod()
    async def rm_bot(self, ctx, prefix: typing.Optional[NotInt], limit: int):
        """Remove messages sent by bots."""
        await self._do_removal(ctx, limit=limit, check=lambda m: m.author.bot or (prefix and m.content.startswith(prefix)))

    @remove.command(name='files', aliases=['file', 'attachment', 'attachments'])
    @checks.server_mod()
    async def rm_files(self, ctx, limit: int):
        """Remove messages with attachments."""
        await self._do_removal(ctx, limit=limit, check=lambda m: len(m.attachments) > 0)

    @remove.command(name='embeds', aliases=['embed'])
    @checks.server_mod()
    async def rm_embeds(self, ctx, limit: int):
        """Remove messages with embeds."""
        await self._do_removal(ctx, limit=limit, check=lambda m: len(m.embeds) > 0)

    @remove.command(name='links', aliases=['link', 'url', 'urls'])
    @checks.server_mod()
    async def rm_links(self, ctx, limit: int):
        """Remove messages matching URL regex search."""
        def check(m):
            return re.search(r"https?://[^\s]{2,}", m.content)

        await self._do_removal(ctx, limit=limit, check=check)

    @remove.command(name='contains')
    @checks.server_mod()
    async def rm_contains(self, ctx, substring, case_insensitive: Optional[bool], limit: int):
        """Remove messages containing a substring."""
        def check(m):
            if case_insensitive:
                return substring.lower() in m.content.lower()
            else:
                return substring in m.content

        await self._do_removal(ctx, limit=limit, check=check)

    @remove.group(name='regex', aliases=['re'], invoke_without_command=True)
    @checks.server_mod()
    async def rm_regex(self, ctx, pattern, limit: int):
        """Remove messages matching a regex pattern. Be careful with this one!

        Uses `re.search()`.
        """
        pattern = re.compile(pattern)
        await self._do_removal(ctx, limit=limit, check=lambda m: bool(pattern.search(m.content)))

    @rm_regex.command(name='fullmatch', aliases=['full'])
    @checks.server_mod()
    async def rm_re_fullmatch(self, ctx, pattern, limit: int):
        """Regex removal, but uses `re.fullmatch()` instead."""
        pattern = re.compile(pattern)
        await self._do_removal(ctx, limit=limit, check=lambda m: bool(pattern.fullmatch(m.content)))

    @remove.command(name='custom')
    @checks.server_mod()
    async def rm_custom(self, ctx, *, args: str):
        """A more advanced purge command.

        This command uses a powerful "command line" syntax.
        Most options support multiple values to indicate 'any' match.
        If the value has spaces it must be quoted.

        The messages are only deleted if all options are met unless
        the `--or` flag is passed, in which case only if any is met.

        The following options are valid.

        `--user`: A mention or name of the user to remove.
        `--contains`: A substring to search for in the message.
        `--starts`: A substring to search if the message starts with.
        `--ends`: A substring to search if the message ends with.
        `--search`: How many messages to search. Default 100. Max 2000.
        `--after`: Messages must come after this message ID.
        `--before`: Messages must come before this message ID.

        Flag options (no arguments):

        `--bot`: Check if it's a bot user.
        `--embeds`: Check if the message has embeds.
        `--files`: Check if the message has attachments.
        `--emoji`: Check if the message has custom emoji.
        `--reactions`: Check if the message has reactions
        `--or`: Use logical OR for all options.
        `--not`: Use logical NOT for all options.
        """
        # custom purge command repurposed from R.Danny's mod cog: https://github.com/gearbot/GearBot

        parser = argparse.ArgumentParser(exit_on_error=False, add_help=False, allow_abbrev=False)
        parser.add_argument('--user', nargs='+')
        parser.add_argument('--contains', nargs='+')
        parser.add_argument('--starts', nargs='+')
        parser.add_argument('--ends', nargs='+')
        parser.add_argument('--or', action='store_true', dest='_or')
        parser.add_argument('--not', action='store_true', dest='_not')
        parser.add_argument('--emoji', action='store_true')
        parser.add_argument('--bot', action='store_const', const=lambda m: m.author.bot)
        parser.add_argument('--embeds', action='store_const', const=lambda m: len(m.embeds))
        parser.add_argument('--files', action='store_const', const=lambda m: len(m.attachments))
        parser.add_argument('--reactions', action='store_const', const=lambda m: len(m.reactions))
        parser.add_argument('--search', type=int)
        parser.add_argument('--after', type=int)
        parser.add_argument('--before', type=int)

        try:
            args = parser.parse_args(shlex.split(args))
        except Exception as e:
            await ctx.send(str(e))
            return

        predicates = []
        if args.bot:
            predicates.append(args.bot)

        if args.embeds:
            predicates.append(args.embeds)

        if args.files:
            predicates.append(args.files)

        if args.reactions:
            predicates.append(args.reactions)

        if args.emoji:
            custom_emoji = re.compile(r'<a?:(\w+):(\d+)>')
            predicates.append(lambda m: custom_emoji.search(m.content))

        if args.user:
            users = []
            converter = commands.MemberConverter()
            for u in args.user:
                try:
                    user = await converter.convert(ctx, u)
                    users.append(user)
                except Exception as e:
                    await ctx.send(str(e))
                    return

            predicates.append(lambda m: m.author in users)

        if args.contains:
            predicates.append(lambda m: any(sub in m.content for sub in args.contains))

        if args.starts:
            predicates.append(lambda m: any(m.content.startswith(s) for s in args.starts))

        if args.ends:
            predicates.append(lambda m: any(m.content.endswith(s) for s in args.ends))

        op = all if not args._or else any

        def predicate(m):
            r = op(p(m) for p in predicates)
            if args._not:
                return not r
            return r

        if args.after:
            if args.search is None:
                args.search = 2000

        if args.search is None:
            args.search = 100

        args.search = max(0, min(2000, args.search))  # clamp from 0-2000
        await self._do_removal(ctx, args.search, predicate, ctx.channel, before=args.before, after=args.after)



def setup(bot):
    bot.add_cog(Moderation(bot))
