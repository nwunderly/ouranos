import asyncio
import time
import discord

from collections import defaultdict, deque, namedtuple
from discord.ext import commands, tasks
from loguru import logger

from ouranos.cog import Cog
from ouranos.utils import database as db
from ouranos.utils import modlog_utils as modlog
from ouranos.utils.modlog_utils import LogEvent, SmallLogEvent, MassActionLogEvent
from ouranos.utils.checks import server_mod, server_admin
from ouranos.utils.converters import UserID, Duration
from ouranos.utils.constants import TICK_GREEN
from ouranos.utils.errors import OuranosCommandError, UnexpectedError, NotConfigured, InfractionNotFound, ModlogMessageNotFound, HistoryNotFound
from ouranos.utils.helpers import approximate_timedelta, exact_timedelta, WEEK


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


# TODO
# MASS_ACTION_LOGS = {
#     'massban': modlog.log_massban,
# }


MUTE = UNMUTE = discord.AuditLogAction.member_role_update
BAN = discord.AuditLogAction.ban
UNBAN = discord.AuditLogAction.unban
KICK = discord.AuditLogAction.kick


class FetchedAuditLogEntry:
    def __init__(self, guild_id, key, the_real_entry):
        self.guild_id = guild_id
        self.key = key
        self.the_real_entry = the_real_entry


class Modlog(Cog):
    """Ouranos' custom built modlog."""
    def __init__(self, bot):
        self.bot = bot
        self._last_case_id_cache = {}
        self._last_audit_id_cache = {}

        # (guild_id, user_id)
        self._audit_log_queue = deque()
        # {guild_id: {}}
        self._mod_action_cache = defaultdict(lambda: defaultdict(dict))

        self._audit_log_fetcher_task = None
        self._ensure_audit_log_fetcher_alive.start()

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

    @tasks.loop(seconds=10)
    async def _ensure_audit_log_fetcher_alive(self):
        if not self._audit_log_fetcher_task or self._audit_log_fetcher_task.done():
            self._audit_log_fetcher_task = asyncio.create_task(self._audit_log_fetcher_loop())

    async def _audit_log_fetcher_loop(self):
        await self.bot.wait_until_ready()
        logger.info("starting audit log fetcher loop")
        default_sleep = 1.5
        t = default_sleep

        while True:
            found, missed = await self._audit_log_fetcher(int(t))
            t = default_sleep + 2*(found > 0) + found + 5*(missed > 0)
            if t != default_sleep:
                logger.info(f"sleeping {t} seconds")
            await asyncio.sleep(t)

    async def _audit_log_fetcher(self, limit=1):
        to_check = defaultdict(dict)
        t0 = time.monotonic()

        # clear the queue
        while True:
            try:
                action_type, guild_id, user_id, check = self._audit_log_queue.pop()
                to_check[guild_id][action_type, user_id] = check
            except IndexError:
                break

        # make audit requests
        found = discarded = 0
        for guild_id, infractions in to_check.items():
            guild = self.bot.get_guild(guild_id)

            async for entry in guild.audit_logs(limit=limit+2*len(infractions)):
                key = (entry.action, entry.target.id)
                if key in infractions and infractions[key](entry):  # we found it, dispatch the event
                    found += 1
                    infractions.pop(key)
                    self.bot.dispatch(f'fetched_audit_log_entry_{guild_id}', FetchedAuditLogEntry(guild_id, key, entry))

                # if it's a ban, make sure we don't have any events looking for a kick that doesn't exist.
                if entry.action == BAN:
                    if (k := KICK, entry.user.id) in infractions:
                        discarded += 1
                        infractions.pop(k)
                        self.bot.dispatch(f'fetched_audit_log_entry_{guild_id}', FetchedAuditLogEntry(guild_id, k, entry))

                if not infractions:
                    break

        for guild_id, infractions in to_check.items():
            for action_type, user_id in infractions:
                check = infractions[action_type, user_id]
                key = (action_type, guild_id, user_id, check)
                logger.debug(f"putting missed infraction {key[:3]} back in fetch queue.")
                self._audit_log_queue.append(key)

        missed = sum(len(infs) for infs in to_check.values())
        dt = time.monotonic() - t0

        if found or missed or discarded:
            logger.info(f"fetched {found} audit log entries, unable to find {missed}, discarded {discarded}. task ran in {dt} seconds.")
            
        return found, missed

    async def fetch_audit_log_entry(self, action_type, guild, user, check=lambda _: True):
        inf = (action_type, guild.id, user.id, check)
        key = (action_type, user.id)
        self._audit_log_queue.append(inf)
        try:
            entry = await self.bot.wait_for(
                f'fetched_audit_log_entry_{guild.id}',
                check=lambda e: e.key == key,
                timeout=30
            )
            return entry.the_real_entry
        except asyncio.TimeoutError:
            if action_type != KICK:
                logger.error(f"timed out for {tuple(str(i) for i in inf[:3])}.")
            return None

    async def mass_action_filter(self, type, guild, user, mod):
        # TODO
        pass

    @Cog.listener()
    async def on_member_ban(self, guild, user):
        if not await self.guild_has_modlog_config(guild):
            return

        logger.debug("ban detected")
        moderator = reason = note = duration = None
        # await asyncio.sleep(2)

        entry = await self.fetch_audit_log_entry(BAN, guild, user)
        if entry:
            moderator = entry.user
            duration, reason = self.maybe_duration_from_audit_reason(entry.reason)
            reason, note = self.maybe_note_from_audit_reason(reason)

        if (moderator == self.bot.user  # action was done by me
                or (moderator and moderator.id == 515067662028636170)):  # Beemo (special support coming soontm)
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
        # await asyncio.sleep(2)

        entry = await self.fetch_audit_log_entry(KICK, guild, member)

        if not entry:
            logger.debug("no audit log entry found. member left the server.")
            return

        else:
            # if it's a ban, ignore
            if entry.action == BAN:
                logger.debug("it's a ban. ignoring")
                return

            logger.debug("entry found, it's a ban. logging")
            moderator = entry.user
            duration, reason = self.maybe_duration_from_audit_reason(entry.reason)
            reason, note = self.maybe_note_from_audit_reason(reason)

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
        mute_role = guild.get_role(config.mute_role_id)
        # await asyncio.sleep(2)

        if mute_role in before.roles and mute_role not in after.roles:  # unmute
            logger.debug("detected unmute")

            entry = await self.fetch_audit_log_entry(
                UNMUTE, guild, member,
                check=lambda e: mute_role in e.after.roles and mute_role not in e.before.roles)

            if entry.id == self._last_audit_id_cache.get(guild.id):
                return
            self._last_audit_id_cache[guild.id] = entry.id

            moderator = entry.user
            reason, note = self.maybe_note_from_audit_reason(entry.reason)

            if moderator == self.bot.user:  # action was done by me
                return

            # disable currently-active mute(s) for this user in this guild, if there are any
            await self.bot.run_in_background(
                modlog.deactivate_infractions(guild.id, member.id, 'mute'))

            await LogEvent('unmute', guild, member, moderator, reason, note, None).dispatch()

        elif mute_role in after.roles and mute_role not in before.roles:  # mute
            logger.debug("detected mute")

            entry = await self.fetch_audit_log_entry(
                MUTE, guild, member,
                check=lambda e: mute_role in e.before.roles and mute_role not in e.after.roles)

            if entry.id == self._last_audit_id_cache.get(guild.id):
                return
            self._last_audit_id_cache[guild.id] = entry.id

            moderator = entry.user
            duration, reason = self.maybe_duration_from_audit_reason(entry.reason)
            reason, note = self.maybe_note_from_audit_reason(reason)

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
        # await asyncio.sleep(2)

        entry = await self.fetch_audit_log_entry(UNBAN, guild, user)

        moderator = entry.user
        reason, note = self.maybe_note_from_audit_reason(entry.reason)

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

    @Cog.listener()
    async def on_mass_action_log(self, log):
        if not await self.guild_has_modlog_config(log.guild):
            return
        # TODO
        # if isinstance(log, MassActionLogEvent):
        #     await MASS_ACTION_LOGS[log.type](log.guild, log.users, log.infraction_id_range)

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

    @infraction.command(aliases=['edit-duration', 'editd'])
    @server_mod()
    async def edit_duratiion(self, ctx, infraction_id: int, new_duration: Duration):
        """Edit the duration of a running infraction. Useful if the member is no longer in the server.

        Note: this only works for mute and ban infractions.
        """
        infraction = await self._get_infraction(ctx.guild.id, infraction_id)
        if infraction.type not in ('mute', 'ban'):
            raise OuranosCommandError("This command only works for mute and ban infractions.")
        elif not infraction.active:
            raise OuranosCommandError("This command is not active. Editing the duration will have no effect.")
        _, message = await modlog.edit_infraction_and_message(infraction, duration=new_duration, edited_by=ctx.author)
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
        await db.edit_record(history)  # runs save() and ensures cache is updated
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

        if recent:
            _recent = recent[:5]
            s += f"\nRecent infractions for {user} (showing {len(_recent)}/{len(recent)}):```\n"
            for infraction in _recent:
                mod = await self.bot.get_or_fetch_member(ctx.guild, infraction.mod_id) or infraction.mod_id
                dt = approximate_timedelta(now - infraction.created_at)
                dt_tot = exact_timedelta(infraction.ends_at - infraction.created_at) if infraction.ends_at else None
                dt_rem = approximate_timedelta(infraction.ends_at - now) if infraction.ends_at else None
                active = 'active ' if infraction.active else ''
                s += f"#{infraction.infraction_id}: {active}{infraction.type} by {mod} (about {dt} ago)\n"
                if dt_tot:
                    rem = f" (about {dt_rem} remaining)" if infraction.active else ''
                    s += f"\tduration: {dt_tot}{rem}\n"
                if infraction.reason:
                    s += f"\treason: {infraction.reason}\n"
            s += "```"

        else:
            if not recent:
                s += f"\nNo recent infractions."

        await ctx.send(s)

    @history.command(name='delete')
    @server_admin()
    async def history_delete(self, ctx, *, user: UserID):
        """Reset a user's infraction history.
        This does not delete any infractions, just cleans the references to them in their history.
        """
        await ctx.confim_action(f'Are you sure you want to wipe infraction history for {user}? '
                                f'This could result in currently-active infractions behaving unexpectedly.')
        try:
            await db.History.filter(guild_id=ctx.guild.id, user_id=user.id).delete()
            if (key := (ctx.guild.id, user.id)) in db.history_cache:
                db.history_cache.pop(key)
        except Exception as e:
            raise UnexpectedError(f'{e.__class__.__name__}: {e}')
        await ctx.send(f"{TICK_GREEN} Removed infraction history for {user}.")

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
