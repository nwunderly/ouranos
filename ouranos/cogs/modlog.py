import io
import asyncio
import time
import discord
import shlex

from collections import defaultdict, deque
from discord.ext import commands, tasks
from loguru import logger
from tortoise.queryset import Q

from ouranos.dpy.cog import Cog
from ouranos.dpy.command import command, group
from ouranos.utils import db
from ouranos.utils import modlog
from ouranos.utils.better_argparse import Parser
from ouranos.utils.modlog import LogEvent, SmallLogEvent, MassActionLogEvent
from ouranos.utils.checks import server_mod, server_admin
from ouranos.utils.converters import UserID, Duration, InfractionID
from ouranos.utils.emojis import TICK_GREEN
from ouranos.utils.errors import OuranosCommandError, UnexpectedError, NotConfigured, InfractionNotFound, ModlogMessageNotFound, HistoryNotFound
from ouranos.utils.format import approximate_timedelta, exact_timedelta, WEEK, TableFormatter

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


MASS_ACTION_LOGS = {
    'ban': modlog.log_mass_ban,
    'mute': modlog.log_mass_mute,
}


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
    """Modlog related commands."""
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
        last_run = False

        while True:
            found, missed = await self._audit_log_fetcher()
            t = default_sleep + 2*(found > 0)*last_run + int(found/30) + 5*(missed > 0)
            last_run = bool(found + missed)
            if t != default_sleep:
                logger.info(f"sleeping {t} seconds")
            await asyncio.sleep(t)

    async def _audit_log_fetcher(self):
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

            async for entry in guild.audit_logs(limit=5+2*len(infractions)):
                if entry.action not in [KICK, MUTE, BAN, UNBAN]:
                    continue
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
            for action_type, user_id in infractions.copy():
                if action_type == KICK:
                    discarded += 1
                    infractions.pop((action_type, user_id))
                    self.bot.dispatch(f'fetched_audit_log_entry_{guild_id}', FetchedAuditLogEntry(guild_id, (action_type, user_id), None))
                else:
                    check = infractions[action_type, user_id]
                    key = (action_type, guild_id, user_id, check)
                    logger.debug(f"putting missed infraction {key[:3]} back in fetch queue.")
                    self._audit_log_queue.append(key)

        missed = sum(len(infs) for infs in to_check.values())
        dt = time.monotonic() - t0

        if found or missed:
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
                raise Exception(f"timed out for {tuple(str(i) for i in inf[:3])}.") from None
            return None

    async def mass_action_filter(self, type, guild, user, mod):
        # TODO: implement mass_action_filter (for automatically detecting mass actions by other bots)
        pass

    @Cog.listener()
    async def on_member_ban(self, guild, user):
        if not await self.guild_has_modlog_config(guild):
            return

        logger.debug("ban detected")
        moderator = reason = note = duration = None
        await asyncio.sleep(2)

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
        await asyncio.sleep(2)

        entry = await self.fetch_audit_log_entry(KICK, guild, member)

        if not entry:
            logger.debug("no audit log entry found. member left the server.")
            return

        else:
            # if it's a ban, ignore
            if entry.action == BAN:
                logger.debug("it's a ban. ignoring")
                return

            logger.debug("entry found, it's a kick. logging")
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
        await asyncio.sleep(2)

        if mute_role in before.roles and mute_role not in after.roles:  # unmute
            logger.debug("detected unmute")

            entry = await self.fetch_audit_log_entry(
                UNMUTE, guild, member,
                check=lambda e: mute_role in e.before.roles and mute_role not in e.after.roles)

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
                check=lambda e: mute_role in e.after.roles and mute_role not in e.before.roles)

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
        await asyncio.sleep(2)

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

        if isinstance(log, MassActionLogEvent):
            await MASS_ACTION_LOGS[log.type](log.guild, log.users, log.mod, log.reason, log.note, log.duration)

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

    async def _get_infractions_bulk(self, guild_id, infraction_ids):
        infractions = await modlog.get_infractions_bulk(guild_id, infraction_ids)
        not_found = infraction_ids.copy()

        for i in infractions:
            if i.infraction_id in infraction_ids:
                not_found.remove(i.infraction_id)

        if not_found:
            # only complain about the first one we can't find
            raise InfractionNotFound(not_found[0])

        return infractions

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

    @group(aliases=['case', 'inf'])
    @server_mod()
    async def infraction(self, ctx, infraction_id: InfractionID):
        """Base command for modlog. Passing an int will return the link to the message associated with a particular infraction."""
        message = await self._fetch_infraction_message(ctx, ctx.guild, infraction_id)
        await ctx.send(message.jump_url)

    @infraction.command(name='view')
    @server_mod()
    async def infraction_view(self, ctx, infraction_id: InfractionID):
        """View the logged message for an infraction."""
        message = await self._fetch_infraction_message(ctx, ctx.guild, infraction_id)
        await ctx.send(message.content)

    def infraction_to_dict(self, infraction):
        return {
            'infraction_id': infraction.infraction_id,
            'user_id': infraction.user_id,
            'mod_id': infraction.mod_id,
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
    async def infraction_json(self, ctx, infraction_id: InfractionID):
        """View the database entry for an infraction in JSON format."""
        infraction = await self._get_infraction(ctx.guild.id, infraction_id)
        serialized = str(self.infraction_to_dict(infraction))
        await ctx.send("```py\n" + serialized + "\n```")

    @infraction.command(name='info')
    @server_mod()
    async def infraction_info(self, ctx, infraction_id: InfractionID):
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

    @command(aliases=['edit-reason', 'editr'])
    @server_mod()
    async def reason(self, ctx, infraction_id: InfractionID, *, new_reason):
        """Edit the reason for an infraction."""
        infraction = await self._get_infraction(ctx.guild.id, infraction_id)

        # handle bulk edit
        if infraction.bulk_infraction_id_range:
            start, end = infraction.bulk_infraction_id_range
            await ctx.confirm_action(f"This will edit {end - start + 1} infractions. Are you sure? (y/n)")
            infraction_ids = list(range(start, end + 1))
            infractions = await self._get_infractions_bulk(ctx.guild.id, infraction_ids)
            m = await ctx.send("Editing...")
            _, message = await modlog.edit_infractions_and_messages_bulk(infractions, reason=new_reason, edited_by=ctx.author)
            await m.edit(content=message.jump_url)

        # edit normally
        else:
            _, message = await modlog.edit_infraction_and_message(infraction, reason=new_reason, edited_by=ctx.author)
            await ctx.send(message.jump_url)

    @command(aliases=['edit-note', 'editn'])
    @server_mod()
    async def note(self, ctx, infraction_id: InfractionID, *, new_note):
        """Edit the note for an infraction."""
        infraction = await self._get_infraction(ctx.guild.id, infraction_id)

        # handle bulk edit
        if infraction.bulk_infraction_id_range:
            start, end = infraction.bulk_infraction_id_range
            await ctx.confirm_action(f"This will edit {end - start + 1} infractions. Are you sure? (y/n)")
            infraction_ids = list(range(start, end + 1))
            infractions = await self._get_infractions_bulk(ctx.guild.id, infraction_ids)
            m = await ctx.send("Editing...")
            _, message = await modlog.edit_infractions_and_messages_bulk(infractions, note=new_note, edited_by=ctx.author)
            await m.edit(content=message.jump_url)

        # edit normally
        else:
            _, message = await modlog.edit_infraction_and_message(infraction, note=new_note, edited_by=ctx.author)
            await ctx.send(message.jump_url)

    @command(aliases=['edit-duration', 'editd'])
    @server_mod()
    async def duration(self, ctx, infraction_id: InfractionID, new_duration: Duration):
        """Edit the duration of an active infraction. Useful if the member is no longer in the server.

        Note: this only works for mute and ban infractions.
        """
        infraction = await self._get_infraction(ctx.guild.id, infraction_id)
        if infraction.type not in ('mute', 'ban'):
            raise OuranosCommandError("This command only works for mute and ban infractions.")
        elif not infraction.active:
            raise OuranosCommandError("This infraction is not active. Editing the duration will have no effect.")

        # handle bulk edit
        if infraction.bulk_infraction_id_range:
            start, end = infraction.bulk_infraction_id_range
            await ctx.confirm_action(f"This will edit {end - start + 1} infractions. Are you sure? (y/n)")
            infraction_ids = list(range(start, end + 1))
            infractions = await self._get_infractions_bulk(ctx.guild.id, infraction_ids)

            # make sure these infractions are valid
            for infraction in infractions:
                if infraction.type not in ('mute', 'ban'):
                    raise OuranosCommandError("This command only works for mute and ban infractions.")

            m = await ctx.send("Editing...")
            _, message = await modlog.edit_infractions_and_messages_bulk(infractions, duration=new_duration, edited_by=ctx.author)
            await m.edit(content=message.jump_url)

        # edit normally
        else:
            _, message = await modlog.edit_infraction_and_message(infraction, duration=new_duration, edited_by=ctx.author)
            await ctx.send(message.jump_url)

    @infraction.command(name='delete')
    @server_admin()
    async def infraction_delete(self, ctx, infraction_id: InfractionID):
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

    @infraction.command(name='search')
    @server_mod()
    async def infraction_search(self, ctx, *, args):
        """Advanced infraction database search command.

        This command uses a powerful "command line" syntax.
        If a value has spaces it must be quoted.

        Returns every infraction found matching all criteria
        unless the `--or` flag is passed, in which case it
        returns every infraction matching any criteria.

        The following options are valid. Any arguments passed
        without an option are treated as keywords to search.
        Keywords are searched for as individual substrings in
        each infraction's reason and note.

        `--user`: A mention or name of the user to query.
        `--mod`: A mention or name of the mod to query.
        `--type`: The type of infraction to query by.
        `--active`: Bool indicating whether to search for active
            or inactive infractions.

        Flag options (no arguments):

        `--or`: Use logical OR for all options.
        `--not`: Use logical NOT for all options.
        `--count`: Count the number of infractions instead of
            returning as a formatted table.
        """
        def infraction_type_converter(t):
            if t.lower() in ['warn', 'mute', 'unmute', 'kick', 'ban', 'unban']:
                return t
            else:
                raise OuranosCommandError('Invalid infraction type.')

        parser = Parser(add_help=False, allow_abbrev=False)
        parser.add_argument('keywords', nargs='*')
        parser.add_argument('--user')
        parser.add_argument('--mod')
        parser.add_argument('--type', type=infraction_type_converter)
        parser.add_argument('--active', type=commands.core._convert_to_bool, default=None)
        parser.add_argument('--or', action='store_true', dest='_or')
        parser.add_argument('--not', action='store_true', dest='_not')
        parser.add_argument('--count', action='store_true')

        try:
            args = parser.parse_args(shlex.split(args))
        except Exception as e:
            raise OuranosCommandError(str(e))

        query = []

        if args.keywords:
            query.append(Q(
                *[Q(reason__contains=kw, note__contains=kw, join_type='OR') for kw in args.keywords],
                join_type='OR'
            ))

        if args.user:
            converter = UserID()
            try:
                user = await converter.convert(ctx, args.user)
            except Exception as e:
                raise OuranosCommandError(str(e))
            query.append(Q(user_id=user.id))

        if args.mod:
            converter = UserID()
            try:
                mod = await converter.convert(ctx, args.mod)
            except Exception as e:
                await ctx.send(str(e))
                return
            query.append(Q(mod_id=mod.id))

        if args.type:
            query.append(Q(type=args.type))

        if args.active is not None:
            query.append(Q(active=args.active))

        the_real_query = Q(*query, join_type='OR' if args._or else 'AND')

        if args._not:
            the_real_query.negate()

        the_real_query = Q(the_real_query, guild_id=ctx.guild.id)
        infractions = db.Infraction.filter(the_real_query)

        if args.count:
            results = await infractions.count()
            await ctx.send(f"I found {results} infractions.")

        else:
            start = time.perf_counter()
            results = await infractions.all()
            dt = (time.perf_counter() - start) * 1000.0
            rows = len(results)
            if rows == 0:
                return await ctx.send(f'`{dt:.2f}ms: {results}`')

            results = sorted(results, key=lambda i: i.infraction_id)
            results = [self.infraction_to_dict(i) for i in results]
            headers = list(results[0].keys())
            table = TableFormatter()
            table.set_columns(headers)
            table.add_rows(list(r.values()) for r in results)
            render = table.render()

            _s = 's' if rows != 1 else ''
            fmt = f'```\n{render}\n```\n*Returned {rows} row{_s} in {dt:.2f}ms*'
            if len(fmt) > 2000:
                fp = io.BytesIO(fmt.encode('utf-8'))
                await ctx.send('Too many results...', file=discord.File(fp, 'results.txt'))
            else:
                await ctx.send(fmt)

    async def _get_history(self, guild_id, user_id):
        history = await modlog.get_history(guild_id, user_id)
        if not history:
            raise HistoryNotFound(user_id)
        return history

    @group(aliases=['h'])
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
