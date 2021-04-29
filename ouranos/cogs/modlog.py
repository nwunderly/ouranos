import asyncio
import time
import discord
import logging

from discord.ext import commands

from ouranos.cog import Cog
from ouranos.utils import database as db
from ouranos.utils import modlog_utils as modlog
from ouranos.utils.modlog_utils import LogEvent, SmallLogEvent
from ouranos.utils.checks import server_mod, server_admin
from ouranos.utils.converters import UserID, Duration
from ouranos.utils.constants import TICK_GREEN
from ouranos.utils.errors import OuranosCommandError, UnexpectedError, NotConfigured, InfractionNotFound, ModlogMessageNotFound, HistoryNotFound
from ouranos.utils.helpers import approximate_timedelta, exact_timedelta, WEEK


logger = logging.getLogger(__name__)


LOGS = {
    'warn': modlog.log_warn,
    'mute': modlog.log_mute,
    'unmute': modlog.log_unmute,
    'kick': modlog.log_kick,
    'ban': modlog.log_ban,
    'forceban': modlog.log_forceban,
    'unban': modlog.log_unban,
}


SMALL_LOGS = {
    'mute-expire': modlog.log_mute_expire,
    'ban-expire': modlog.log_ban_expire,
    'mute-persist': modlog.log_mute_persist,
}


class Modlog(Cog):
    """Ouranos' custom built modlog."""
    def __init__(self, bot):
        self.bot = bot
        self._last_case_id_cache = {}
        self._last_audit_id_cache = {}

    async def guild_has_modlog_config(self, guild):
        config = await db.get_config(guild)
        return config and config.modlog_channel_id

    def maybe_duration_from_audit_reason(self, reason):
        if not reason:
            return None, None
        duration = None
        s = reason.split(maxsplit=1)
        d, r = (s[0], s[1]) if len(s) == 2 else (None, None)
        try:
            if d:
                duration = Duration._real_convert(d)
                reason = r
        except commands.BadArgument:
            pass
        return duration, reason

    def maybe_note_from_audit_reason(self, reason):
        if not reason:
            return None, None
        s = reason.split('--', 1)
        reason, note = (s[0], s[1]) if len(s) == 2 else (reason, None)
        return reason, note

    @Cog.listener()
    async def on_member_ban(self, guild, user):
        if not await self.guild_has_modlog_config(guild):
            return

        logger.debug("ban detected")

        moderator = reason = note = duration = None

        await asyncio.sleep(2)

        async for entry in guild.audit_logs(limit=5):
            if entry.action == discord.AuditLogAction.ban and entry.target == user:
                logger.debug("audit log entry found")
                moderator = entry.user
                duration, reason = self.maybe_duration_from_audit_reason(entry.reason)
                reason, note = self.maybe_note_from_audit_reason(reason)
                break

        if (moderator == self.bot.user  # action was done by me
                or moderator.id == 515067662028636170):  # Beemo (special support coming soontm)
            return

        # disable currently-active ban(s) for this user in this guild, if there are any
        await self.bot.run_in_background(
            modlog.deactivate_infractions(guild.id, user.id, 'ban'))

        await LogEvent('ban', guild, user, moderator, reason, note, duration).dispatch()

    @Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        if not await self.guild_has_modlog_config(guild):
            return

        logger.debug("possible kick detected")
        moderator = reason = note = None

        await asyncio.sleep(2)

        async for entry in guild.audit_logs(limit=5):
            if entry.action == discord.AuditLogAction.kick and entry.target == member:
                logger.debug("audit log entry found, it's a kick. logging")
                moderator = entry.user
                reason, note = self.maybe_note_from_audit_reason(entry.reason)
                break
            elif entry.action == discord.AuditLogAction.ban and entry.target == member:
                logger.debug("audit log entry found, it's a ban. ignoring")
                return

        if not moderator:
            logger.debug("no audit log entry found. member left the server.")

        else:
            if moderator == self.bot.user:  # action was done by me
                return

            await LogEvent('kick', guild, member, moderator, reason, note, None).dispatch()

    @Cog.listener()
    async def on_member_update(self, before, after):
        guild = before.guild
        if not await self.guild_has_modlog_config(guild):
            return

        config = await db.get_config(guild)
        if not (config and config.mute_role_id):
            return

        member = before
        moderator = reason = note = duration = None
        mute_role = guild.get_role(config.mute_role_id)

        await asyncio.sleep(2)

        if mute_role in before.roles and mute_role not in after.roles:  # unmute
            logger.debug("detected unmute")
            async for entry in guild.audit_logs(limit=5):
                if entry.action == discord.AuditLogAction.member_role_update and mute_role in entry.before.roles and mute_role not in entry.after.roles:
                    if entry.id == self._last_audit_id_cache.get(guild.id):
                        return
                    self._last_audit_id_cache[guild.id] = entry.id
                    logger.debug("unmute audit log entry found")
                    moderator = entry.user
                    reason, note = self.maybe_note_from_audit_reason(entry.reason)
                    break

            if moderator == self.bot.user:  # action was done by me
                return

            # disable currently-active mute(s) for this user in this guild, if there are any
            await self.bot.run_in_background(
                modlog.deactivate_infractions(guild.id, member.id, 'mute'))

            await LogEvent('unmute', guild, member, moderator, reason, note, None).dispatch()

        elif mute_role in after.roles and mute_role not in before.roles:  # mute
            logger.debug("detected mute")
            async for entry in guild.audit_logs(limit=5):
                if entry.action == discord.AuditLogAction.member_role_update and mute_role in entry.after.roles and mute_role not in entry.before.roles:
                    if entry.id == self._last_audit_id_cache.get(guild.id):
                        return
                    self._last_audit_id_cache[guild.id] = entry.id
                    logger.debug("mute audit log entry found")
                    moderator = entry.user
                    duration, reason = self.maybe_duration_from_audit_reason(entry.reason)
                    reason, note = self.maybe_note_from_audit_reason(reason)
                    break

            if moderator == self.bot.user:  # action was done by me
                return

            # disable currently-active mute(s) for this user in this guild, if there are any
            await self.bot.run_in_background(
                modlog.deactivate_infractions(guild.id, member.id, 'mute'))

            await LogEvent('mute', guild, member, moderator, reason, note, duration).dispatch()

    @Cog.listener()
    async def on_member_unban(self, guild, user):
        if not await self.guild_has_modlog_config(guild):
            return

        logger.debug("unban detected")
        moderator = reason = note = None

        await asyncio.sleep(2)

        async for entry in guild.audit_logs(limit=5):
            if entry.action == discord.AuditLogAction.unban and entry.target == user:
                logger.debug("audit log entry found")
                moderator = entry.user
                reason, note = self.maybe_note_from_audit_reason(entry.reason)
                break

        if moderator == self.bot.user:  # action was done by me
            return

        # disable currently-active ban(s) for this user in this guild, if there are any
        await self.bot.run_in_background(
            modlog.deactivate_infractions(guild.id, user.id, 'ban'))

        # dispatch the event
        await LogEvent('unban', guild, user, moderator, reason, note, None).dispatch()

    @Cog.listener()
    async def on_log(self, log):
        if not await self.guild_has_modlog_config(log.guild):
            return
        if isinstance(log, LogEvent):
            await LOGS[log.type](log.guild, log.user, log.mod, log.reason, log.note, log.duration)

    @Cog.listener()
    async def on_small_log(self, log):
        if not await self.guild_has_modlog_config(log.guild):
            return
        if isinstance(log, SmallLogEvent):
            await SMALL_LOGS[log.type](log.guild, log.user, log.infraction_id)

    async def _get_modlog_channel(self, guild):
        config = await db.get_config(guild)
        modlog_channel = guild.get_channel(config.modlog_channel_id if config else 0)
        if not modlog_channel:
            raise NotConfigured('modlog_channel')
        return modlog_channel

    async def _get_infraction(self, guild_id, infraction_id):
        infraction = await modlog.get_infraction(guild_id, infraction_id)
        if not infraction:
            raise InfractionNotFound(infraction_id)
        return infraction

    async def _fetch_infraction_message(self, ctx, guild, infraction_id):
        modlog_channel = await self._get_modlog_channel(guild)
        infraction = await self._get_infraction(guild.id, infraction_id)
        message_id = infraction.message_id
        if message_id:
            try:
                return await modlog_channel.fetch_message(message_id)
            except discord.NotFound:
                pass
        raise ModlogMessageNotFound(infraction_id, ctx.prefix)

    @commands.group(aliases=['i', 'case'], invoke_without_command=True)
    @server_mod()
    async def infraction(self, ctx, infraction_id: int):
        """Base command for modlog. Passing an int will return the link to the message associated with a particular infraction."""
        message = await self._fetch_infraction_message(ctx, ctx.guild, infraction_id)
        await ctx.send(message.jump_url)

    @infraction.command(name='view')
    @server_mod()
    async def infraction_view(self, ctx, infraction_id: int):
        """View the logged message for an infraction."""
        message = await self._fetch_infraction_message(ctx, ctx.guild, infraction_id)
        await ctx.send(message.content)

    def infraction_to_dict(self, infraction):
        return {
            'infraction_id': infraction.infraction_id,
            'user_id': infraction.user_id,
            'mod_id': infraction.message_id,
            'message_id': infraction.message_id,
            'type': infraction.type,
            'reason': infraction.reason,
            'note': infraction.note,
            'created_at': str(infraction.created_at) if infraction.created_at else None,
            'ends_at': str(infraction.ends_at) if infraction.ends_at else None,
            'active': infraction.active
        }

    @infraction.command(name='json')
    @server_mod()
    async def infraction_json(self, ctx, infraction_id: int):
        """View the database entry for an infraction in JSON format."""
        infraction = await self._get_infraction(ctx.guild.id, infraction_id)
        serialized = str(self.infraction_to_dict(infraction))
        await ctx.send("```py\n" + serialized + "\n```")

    @infraction.command(name='info')
    @server_mod()
    async def infraction_info(self, ctx, infraction_id: int):
        """View the database entry for an infraction."""
        infraction = await self._get_infraction(ctx.guild.id, infraction_id)
        if infraction.ends_at:
            dt_tot = infraction.ends_at - infraction.created_at
            dt_rem = infraction.ends_at - time.time()
            duration = f"Duration: {exact_timedelta(dt_tot)}\n" if dt_tot else ""
            remaining = f"Remaining: {exact_timedelta(dt_rem)}\n" if dt_rem > 0 else ""
        else:
            duration = remaining = ""

        user = await self.bot.get_or_fetch_member(ctx.guild, infraction.user_id) or infraction.user_id
        mod = await self.bot.get_or_fetch_member(ctx.guild, infraction.mod_id) or infraction.mod_id

        await ctx.send(
            f"Infraction #{infraction.infraction_id} ({infraction.type}):```\n"
            f"User: {user}\n"
            f"Moderator: {mod}\n"
            f"{duration}"
            f"{remaining}"
            f"Reason: {infraction.reason}\n"
            f"Note: {infraction.note}\n"
            f"Active: {infraction.active}\n"
            f"```")

    @infraction.command(aliases=['edit-reason', 'editr'])
    @server_mod()
    async def edit_reason(self, ctx, infraction_id: int, *, new_reason):
        """Edit the reason for an infraction."""
        infraction = await self._get_infraction(ctx.guild.id, infraction_id)
        new_reason = f"{new_reason} (edited by {ctx.author})"
        _, message = await modlog.edit_infraction_and_message(infraction, reason=new_reason)
        await ctx.send(message.jump_url)
        
    @infraction.command(aliases=['edit-note', 'editn'])
    @server_mod()
    async def edit_note(self, ctx, infraction_id: int, *, new_note):
        """Edit the note for an infraction."""
        infraction = await self._get_infraction(ctx.guild.id, infraction_id)
        new_note = f"{new_note} (edited by {ctx.author})"
        _, message = await modlog.edit_infraction_and_message(infraction, note=new_note)
        await ctx.send(message.jump_url)

    @infraction.command(name='delete')
    @server_admin()
    async def infraction_delete(self, ctx, infraction_id: int):
        """Remove all references to an infraction from a user's history.

        This does not actually delete the infraction, so it can still be viewed and edited if the id is known.
        """
        infraction = await self._get_infraction(ctx.guild.id, infraction_id)
        history = await self._get_history(ctx.guild.id, infraction.user_id)
        for _list in [getattr(history, infraction.type), history.active]:
            if infraction_id in _list:
                _list.remove(infraction_id)
        await history.save()
        user = (await self.bot.get_or_fetch_member(ctx.guild, infraction.user_id)) or infraction.user_id
        await ctx.send(f"{TICK_GREEN} Removed infraction #{infraction_id} ({infraction.type}) for user {user}.")

    async def _get_history(self, guild_id, user_id):
        history = await modlog.get_history(guild_id, user_id)
        if not history:
            raise HistoryNotFound(user_id)
        return history

    @commands.group(aliases=['h'], invoke_without_command=True)
    @server_mod()
    async def history(self, ctx, *, user: UserID):
        """Returns useful info on a user's recent infractions."""
        history = await self._get_history(ctx.guild.id, user.id)
        now = time.time()
        s = ""

        h_by_type = {}
        for _type in ['warn', 'mute', 'unmute', 'kick', 'ban', 'unban']:
            h_by_type.update({i: _type for i in getattr(history, _type)})
        infraction_ids = sorted(h_by_type.keys(), reverse=True)
        infractions = [await modlog.get_infraction(ctx.guild.id, i) for i in infraction_ids]
        recent = []
        for infraction in infractions:
            if infraction.created_at - now < WEEK:
                recent.append(infraction)

        # if history.active:
        #     s += f"Active infractions for {user}:```\n"
        #     for a in history.active:
        #         infraction = await modlog.get_infraction(ctx.guild.id, a)
        #         mod = await self.bot.get_or_fetch_member(ctx.guild, infraction.mod_id) or infraction.mod_id
        #         s += f"#{a}: {infraction.type} by {mod} ({infraction.reason or 'no reason'})\n"
        #         if infraction.ends_at:
        #             dt_tot = infraction.ends_at - infraction.created_at
        #             dt_rem = infraction.ends_at - now
        #             s += f"\tduration: {exact_timedelta(dt_tot)} (about {approximate_timedelta(dt_rem)} remaining)\n"
        #     s += "```"

        # else:
        #     s += "*No active infractions found.*\n"

        if recent:
            _recent = recent[:5]
            s += f"\nRecent infractions for {user} (showing {len(_recent)}/{len(recent)}):```\n"
            for infraction in _recent:
                mod = await self.bot.get_or_fetch_member(ctx.guild, infraction.mod_id) or infraction.mod_id
                dt = now - infraction.created_at
                dt_tot = exact_timedelta(infraction.ends_at - infraction.created_at) if infraction.ends_at else None
                dt_rem = approximate_timedelta(infraction.ends_at - now) if infraction.ends_at else None
                s += f"#{infraction.infraction_id}: {'active ' if infraction.active else ''}{infraction.type} by {mod} ({infraction.reason})\n" \
                     f"\tabout {approximate_timedelta(dt)} ago\n"
                if dt_tot:
                    rem = f" (about {approximate_timedelta(dt_rem)} remaining)" if infraction.active else ''
                    s += f"\tduration: {exact_timedelta(dt_tot)}{rem}\n"
                if infraction.reason:
                    s += f"\treason: {infraction.reason}\n"
            s += "```"

        else:
            if not recent:
                s += f"\nNo currently active or recent infractions."

        await ctx.send(s)

    @history.command(name='delete')
    @server_admin()
    async def history_delete(self, ctx, *, user: UserID):
        """Reset a user's infraction history.
        This does not delete any infractions, just cleans the references to them in their history.
        """
        if await self.bot.confirm_action(ctx, f'Are you sure you want to wipe infraction history for {user}? '
                                              f'This could result in currently-active infractions behaving unexpectedly.'):
            try:
                await db.History.filter(guild_id=ctx.guild.id, user_id=user.id).delete()
            except Exception as e:
                raise UnexpectedError(f'{e.__class__.__name__}: {e}')
            await ctx.send(f"{TICK_GREEN} Removed infraction history for {user}.")
        else:
            raise OuranosCommandError("Canceled!")

    @history.command(name='all')
    @server_mod()
    async def history_all(self, ctx, *, user: UserID):
        """View a user's complete infraction history."""
        history = await self._get_history(ctx.guild.id, user.id)
        await ctx.send(
            f"Infraction history for {user}:```\n"
            f"warn: {history.warn}\n"
            f"mute: {history.mute}\n"
            f"unmute: {history.unmute}\n"
            f"kick: {history.kick}\n"
            f"ban: {history.ban}\n"
            f"unban: {history.unban}\n"
            f"active: {history.active}\n"
            f"```")


def setup(bot):
    bot.add_cog(Modlog(bot))
