import logging
import re

import discord
from discord.ext import commands
from discord.ext import tasks
from typing import Optional

from ouranos.cog import Cog
from ouranos.utils import checks
from ouranos.utils import db
from ouranos.utils import modlog_utils as modlog
from ouranos.utils.modlog_utils import LogEvent
from ouranos.utils.constants import TICK_RED, TICK_GREEN, TICK_YELLOW
from ouranos.utils.constants import OK_HAND, THUMBS_UP, PRAY, HAMMER, CLAP
from ouranos.utils.converters import Duration
from ouranos.utils.helpers import exact_timedelta


logger = logging.getLogger(__name__)


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


async def try_send(user, message):
    try:
        await user.send(message)
        return True
    except discord.Forbidden:
        return False


class ModerationError(commands.CommandError):
    def __init__(self, message):
        self._msg = message
        super().__init__(message)


class UserNotInGuild(ModerationError):
    def __init__(self, user):
        super().__init__(f"User **{user}** is not in this guild.")


class NotConfigured(ModerationError):
    def __init__(self, option):
        super().__init__(f"This guild is missing the **{option}** configuration option.")


class BotMissingPermission(ModerationError):
    def __init__(self, permission):
        super().__init__(f"I could not perform that action because I'm missing the **{permission}** permission.")


class BotRoleHierarchyError(ModerationError):
    def __init__(self):
        super().__init__("I could not execute that action due to role hierarchy.")


class ModActionOnMod(ModerationError):
    def __init__(self):
        super().__init__("You cannot perform moderation actions on other server moderators!")


class UserID(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            m = await commands.MemberConverter().convert(ctx, argument)
        except commands.BadArgument:
            try:
                member_id = int(argument, base=10)
            except ValueError:
                raise commands.BadArgument(f"{argument} is not a valid user or user ID.") from None
            else:
                m = await ctx.bot.get_or_fetch_member(ctx.guild, member_id)
                if m is None:
                    # hackban case
                    return type('_Hackban', (), {'id': member_id, '__str__': lambda s: f'User ID {s.id}'})()
        return m


class BannedUser(commands.Converter):
    async def _from_bans(self, ctx, argument):
        if not ctx.guild.me.guild_permissions.ban_members:
            raise BotMissingPermission("Ban Members")
        if argument.isdigit():
            member_id = int(argument, base=10)
            try:
                return await ctx.guild.fetch_ban(discord.Object(id=member_id)), True
            except discord.NotFound:
                raise commands.BadArgument('This user is not banned.') from None

        ban_list = await ctx.guild.bans()
        entity = discord.utils.find(lambda u: str(u.user) == argument, ban_list)
        if entity is None:
            raise commands.BadArgument('This user is not banned.')
        return entity, True

    async def _from_db(self, ctx, argument):
        try:
            member_id = int(argument, base=10)
        except ValueError:
            return None
        history = await modlog.get_history(ctx.guild.id, member_id)
        if history and history.active:
            for i in history.active:
                if i in history.ban:
                    return discord.Object(id=member_id)
        return None

    async def convert(self, ctx, argument):
        try:
            return await self._from_bans(ctx, argument)
        except commands.BadArgument as _e:
            e = _e
        m = await self._from_db(ctx, argument)
        if m:
            return m, False
        else:
            raise e


class MutedUser(commands.Converter):
    async def _from_guild(self, ctx, member):
        config = await db.get_config(ctx.guild)
        if config and config.mute_role_id:
            role = ctx.guild.get_role(config.mute_role_id)
            if role in member.roles:
                return member, True
            else:
                raise commands.BadArgument('This user is not muted.')
        else:
            raise NotConfigured('mute_role')

    async def _from_db(self, ctx, member_id):
        if not isinstance(member_id, int):
            try:
                member_id = int(member_id, base=10)
            except ValueError:
                return None
        history = await modlog.get_history(ctx.guild.id, member_id)
        if history and history.active:
            for i in history.active:
                if i in history.mute:
                    return discord.Object(id=member_id)
        return None

    async def convert(self, ctx, argument):
        member = None
        try:
            member = await commands.MemberConverter().convert(ctx, argument)
            return await self._from_guild(ctx, member)
        except commands.BadArgument as _e:
            e = _e
        obj = await self._from_db(ctx, member.id if member else argument)
        if obj:
            return obj, False
        else:
            raise e


class Reason(commands.Converter):
    pattern = re.compile(r"^(?:([\w ]*\w) *)?(?:--note|-n) +(.+)")

    async def convert(self, ctx, argument):
        match = Reason.pattern.fullmatch(argument)
        if not match or match.group(0) == '':
            reason, note = argument, None
        else:
            reason, note = match.group(1) or None, match.group(2)

        r = Reason.format_reason(ctx, reason, note)
        if len(r) > 512:
            reason_max = 512 - len(r) + len(argument)
            raise commands.BadArgument(f'Reason is too long ({len(argument)}/{reason_max})')

        return reason, note, r

    @classmethod
    def format_reason(cls, ctx, reason=None, note=None):
        return f'{ctx.author} (id: {ctx.author.id}): {reason} (note: {note})'


async def send_error(ctx, error):
    message = f"{TICK_RED} {error}"
    await ctx.send(message)


class Moderation(Cog):
    """Moderation commands."""
    def __init__(self, bot):
        self.bot = bot
        self.check_timers.start()

    def cog_unload(self):
        self.check_timers.stop()

    async def cog_command_error(self, ctx, error):
        logger.exception("moderation cog command error")
        if isinstance(error, commands.BadArgument):
            await send_error(ctx, error)
        elif isinstance(error, ModerationError):
            await send_error(ctx, error)
        elif isinstance(error, discord.Forbidden):
            await send_error(ctx, 'I do not have permission to execute this action.')
        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            if isinstance(original, discord.Forbidden):
                await send_error(ctx, 'I do not have permission to execute this action.')
            elif isinstance(original, discord.HTTPException):
                await ctx.send(f'An unexpected error occurred:```\n{error.__class__.__name__}: {error}\n```')

    async def _do_warn(self, guild, user, mod, reason, note=None):
        """Applies a warn to a user and dispatches the event to the modlog."""
        config = await db.get_config(guild)

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

    async def _do_mute_duration_edit(self, infraction, new_duration):
        """Edits the duration of an existing mute infraction."""
        await modlog.edit_infraction_and_message(infraction, duration=new_duration)

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
                delivered = False
        else:
            delivered = None

        # ban the user
        await guild.ban(user, reason=audit_reason, delete_message_days=0)

        # dispatch the modlog event and return to the command
        type = ('force' if not member else '') + 'ban'
        await LogEvent(type, guild, user, mod, reason, note, duration).dispatch()
        return delivered, not bool(member)

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

    async def _do_auto_mute(self, guild, user):
        """Applies a mute to a user without dispatching the modlog event.
        Used for reassigning mute role when a user rejoins the server before their mute expires.
        """
        pass

    async def _do_auto_unmute(self, guild, user):
        """Removes a mute from a user without dispatching the modlog event.
        Used for handling expired mutes without creating an infraction.
        """

    async def _do_auto_unban(self, guild, user):
        """Applies a mute role to a user without dispatching the modlog event.
        Used for handling expired mutes without creating an infraction.
        """

    @tasks.loop(seconds=10)
    async def check_timers(self):
        pass

    @Cog.listener()
    async def on_member_join(self, member):
        pass

    @commands.command()
    @checks.server_mod()
    async def warn(self, ctx, user: discord.Member, *, reason: Reason = None):
        """Applies a warning to a user.

        Sends the user a DM and logs this action to the guild's modlog if configured to do so.
        """
        reason, note, _ = reason or (None, None, None)
        delivered = await self._do_warn(guild=ctx.guild, user=user, mod=ctx.author, reason=reason, note=note)
        delivered = f"*User was {'' if delivered else 'not '}notified.*" if delivered is not None else ""
        await ctx.send(f"{THUMBS_UP} warned **{user}**. {delivered}")

    @commands.command()
    @checks.server_mod()
    async def mute(self, ctx, user: discord.Member, duration: Optional[Duration], *, reason: Reason = None):
        """Mutes a user using the guild's configured mute role.

        Sends the user a DM and logs this action to the guild's modlog if configured to do so.
        """
        reason, note, audit_reason = reason or (None, None, None)
        audit_reason = audit_reason or Reason.format_reason(ctx)
        delivered = await self._do_mute(guild=ctx.guild, user=user, mod=ctx.author, reason=reason, note=note, audit_reason=audit_reason, duration=duration)
        delivered = f"*User was {'' if delivered else 'not '}notified.*" if delivered is not None else ""
        dt = exact_timedelta(duration) if duration else "permanent"
        await ctx.send(f"{OK_HAND} muted **{user}** ({dt}). {delivered}")

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
            delivered = await self._do_unmute(guild=ctx.guild, user=user, mod=ctx.author, reason=reason, note=note, audit_reason=audit_reason)
            delivered = f"User was {'' if delivered else 'not '}notified." if delivered is not None else ""
            await ctx.send(f"{PRAY} unmuted **{user}**. *{delivered}*")

        # remove infraction from database if one was found but they're not muted.
        else:
            count = await modlog.deactivate_infractions(ctx.guild.id, user.id, 'mute')
            p = await self.bot.prefix(ctx.message)
            await ctx.send(f"{TICK_YELLOW} This user does not seem to have this server's mute role, "
                           f"but I found {count} active mute infraction(s) in my database.\n"
                           f"I marked these infractions as inactive to account for this discrepancy. "
                           f"`{p}history {user.id}` should now show no active mutes.")

    @commands.command()
    @checks.server_mod()
    async def kick(self, ctx, user: discord.Member, *, reason: Reason = None):
        """Kicks a user from the guild.

        Sends the user a DM and logs this action to the guild's modlog if configured to do so.
        """
        reason, note, audit_reason = reason or (None, None, None)
        audit_reason = audit_reason or Reason.format_reason(ctx)
        delivered = await self._do_kick(guild=ctx.guild, user=user, mod=ctx.author, reason=reason, note=note, audit_reason=audit_reason)
        delivered = f"*User was {'' if delivered else 'not '}notified.*" if delivered is not None else ""
        await ctx.send(f"{CLAP} kicked **{user}**. {delivered}")

    @commands.command()
    @checks.server_mod()
    async def ban(self, ctx, user: UserID, duration: Optional[Duration], *, reason: Reason = None):
        """Bans a user from the guild.

        This will also work if the user is not in the server.

        Sends the user a DM and logs this action to the guild's modlog if configured to do so.
        """
        reason, note, audit_reason = reason or (None, None, None)
        audit_reason = audit_reason or Reason.format_reason(ctx)
        delivered, force = await self._do_ban(guild=ctx.guild, user=user, mod=ctx.author, reason=reason, note=note, audit_reason=audit_reason, duration=duration)
        delivered = f"*User was {'' if delivered else 'not '}notified.*" if delivered is not None else ""
        force = 'force' if force else ''
        dt = exact_timedelta(duration) if duration else "permanent"
        await ctx.send(f"{HAMMER} {force}banned **{user}** ({dt}). {delivered}")

    @commands.command()
    @checks.server_mod()
    async def unban(self, ctx, user: BannedUser, *, reason: Reason = None):
        """Unbans a user previously banned in this guild.

        Sends the user a DM and logs this action to the guild's modlog if configured to do so.
        """
        user, banned_in_guild = user
        user = user.user
        reason, note, audit_reason = reason or (None, None, None)
        audit_reason = audit_reason or Reason.format_reason(ctx)

        # actually unban them
        if banned_in_guild:
            await self._do_unban(guild=ctx.guild, user=user, mod=ctx.author, reason=reason, note=note, audit_reason=audit_reason)
            await ctx.send(f"{PRAY} unbanned **{user}**.")

        # remove infraction from database if one was found but they're not banned.
        else:
            count = await modlog.deactivate_infractions(ctx.guild.id, user.id, 'ban')
            p = await self.bot.prefix(ctx.message)
            await ctx.send(f"{TICK_YELLOW} This user does not seem to be in this server's ban list, "
                           f"but I found {count} active ban infraction(s) in my database.\n"
                           f"I marked these infractions as inactive to account for this discrepancy. "
                           f"`{p}history {user.id}` should now show no active bans.")

    async def _do_removal(self):
        pass

    @commands.group(aliases=['rm'])
    @checks.server_mod()
    async def remove(self, ctx):
        """NOT IMPLEMENTED"""
        pass


def setup(bot):
    bot.add_cog(Moderation(bot))
