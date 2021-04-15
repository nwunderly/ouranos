import asyncio
import datetime
import re

import discord
import logging
from typing import Union

from discord.ext import commands

from ouranos.cog import Cog
from ouranos.utils import db
from ouranos.utils import infractions
from ouranos.utils.checks import server_mod, server_admin
from ouranos.utils.constants import TICK_RED
from ouranos.utils.converters import FetchedUser


logger = logging.getLogger(__name__)


class LogEvent:
    def __init__(self, type, guild, user, mod, reason, note, duration):
        self.type = type
        self.guild = guild
        self.user = user
        self.mod = mod
        self.reason = reason
        self.note = note
        self.duration = duration


class Modlog(Cog):
    """Ouranos' custom built modlog."""
    def __init__(self, bot):
        self.bot = bot
        self._last_case_id_cache = {}
        self._last_audit_id_cache = {}

    async def guild_has_modlog_config(self, guild):
        config = await db.get_config(guild)
        return config and config.modlog_channel_id

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        if not await self.guild_has_modlog_config(guild):
            return

        logger.debug("ban detected")

        moderator = None
        reason = None
        note = None

        await asyncio.sleep(2)

        async for entry in guild.audit_logs(limit=5):
            if entry.action == discord.AuditLogAction.ban and entry.target == user:
                logger.debug("audit log entry found")
                moderator = entry.user
                reason = entry.reason
                # TODO: parse note from audit log
                break

        if moderator == self.bot.user:  # action was done by me
            return

        # TODO: fix this
        # if isinstance(user, discord.User):  # forceban
        #     logger.debug("it's a forceban")
        #     await infractions.log_forceban(guild, user, moderator, reason, None)
        # else:  # regular ban
        #     logger.debug("it's a regular ban")
        #     await infractions.log_ban(guild, user, moderator, reason, None)

        log = LogEvent('ban', guild, user, moderator, reason, note, None)
        self.bot.dispatch('log', log)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        if not await self.guild_has_modlog_config(guild):
            return

        logger.debug("possible kick detected")
        moderator = None
        reason = None
        note = None

        await asyncio.sleep(2)

        async for entry in guild.audit_logs(limit=5):
            if entry.action == discord.AuditLogAction.kick and entry.target == member:
                logger.debug("audit log entry found, it's a kick. logging")
                moderator = entry.user
                reason = entry.reason
                # TODO: parse note from audit log
                break
            elif entry.action == discord.AuditLogAction.ban and entry.target == member:
                logger.debug("audit log entry found, it's a ban. ignoring")
                return

        if not moderator:
            logger.debug("no audit log entry found. member left the server.")

        else:
            if moderator == self.bot.user:  # action was done by me
                return

            log = LogEvent('kick', guild, member, moderator, reason, note, None)
            self.bot.dispatch('log', log)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        guild = before.guild
        if not await self.guild_has_modlog_config(guild):
            return

        config = await db.get_config(guild)
        if not (config and config.mute_role_id):
            return

        member = before
        moderator = None
        reason = None
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
                    reason = entry.reason
                    break

            if moderator == self.bot.user:  # action was done by me
                return

            # disable currently-active mute(s) for this user in this guild, if there are any
            await infractions.deactivate_infractions(guild.id, member.id, 'mute')

            log = LogEvent('unmute', guild, member, moderator, reason, None, None)
            self.bot.dispatch('log', log)

        elif mute_role in after.roles and mute_role not in before.roles:  # mute
            logger.debug("detected mute")
            async for entry in guild.audit_logs(limit=5):
                if entry.action == discord.AuditLogAction.member_role_update and mute_role in entry.after.roles and mute_role not in entry.before.roles:
                    if entry.id == self._last_audit_id_cache.get(guild.id):
                        return
                    self._last_audit_id_cache[guild.id] = entry.id
                    logger.debug("mute audit log entry found")
                    moderator = entry.user
                    reason = entry.reason
                    break

            if moderator == self.bot.user:  # action was done by me
                return

            log = LogEvent('mute', guild, member, moderator, reason, None, None)
            self.bot.dispatch('log', log)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        if not await self.guild_has_modlog_config(guild):
            return

        logger.debug("unban detected")
        moderator = None
        reason = None

        await asyncio.sleep(2)

        async for entry in guild.audit_logs(limit=5):
            if entry.action == discord.AuditLogAction.unban and entry.target == user:
                logger.debug("audit log entry found")
                moderator = entry.user
                reason = entry.reason
                break

        if moderator == self.bot.user:  # action was done by me
            return

        # disable currently-active ban(s) for this user in this guild, if there are any
        await infractions.deactivate_infractions(guild.id, user.id, 'ban')

        # dispatch the event
        log = LogEvent('unban', guild, user, moderator, reason, None, None)
        self.bot.dispatch('log', log)

    @commands.Cog.listener()
    async def on_log(self, log):
        if not await self.guild_has_modlog_config(log.guild):
            return
        logs = {
            'warn': infractions.log_warn,
            'mute': infractions.log_mute,
            'unmute': infractions.log_unmute,
            'kick': infractions.log_kick,
            'ban': infractions.log_ban,
            'forceban': infractions.log_forceban,
            'unban': infractions.log_unban,
        }
        if log.type in logs:
            await logs[log.type](log.guild, log.user, log.mod, log.reason, log.note, log.duration)

    @commands.group(name='case', aliases=['infraction'], invoke_without_command=True)
    @server_mod()
    async def infraction(self, ctx, infraction_id: int):
        """Base command for modlog. Passing an int will return the link to the message associated with a particular infraction."""
        try:
            config = await db.get_config(ctx.guild)
            modlog_channel = ctx.guild.get_channel(config.modlog_channel_id)
            infraction = await infractions.get_infraction(ctx.guild.id, infraction_id)
            if not infraction:
                return await ctx.send(f"{TICK_RED} I couldn't find infraction #{infraction_id} for this guild.")
            message_id = infraction.message_id
            message = await modlog_channel.fetch_message(message_id)
            if not message:
                return await ctx.send(f"{TICK_RED} I couldn't find a message for infraction #{infraction_id}. "
                                      f"Try `{await self.bot.prefix(ctx.message)}infraction json {infraction_id}` instead.")
        except Exception as e:
            logger.exception(e)
            return await ctx.send(f'{e.__class__.__name__}: {e}')
        await ctx.send(message.jump_url)

    @infraction.command()
    @server_mod()
    async def view(self, ctx, infraction_id: int):
        """View the logged message for an infraction."""
        try:
            config = await db.get_config(ctx.guild)
            modlog_channel = ctx.guild.get_channel(config.modlog_channel_id)
            infraction = await infractions.get_infraction(ctx.guild.id, infraction_id)
            if not infraction:
                return await ctx.send(f"{TICK_RED} I couldn't find infraction #{infraction_id} for this guild.")
            message_id = infraction.message_id
            message = await modlog_channel.fetch_message(message_id)
            if not message:
                return await ctx.send(f"{TICK_RED} I couldn't find a message for infraction #{infraction_id}. "
                                      f"Try `{await self.bot.prefix(ctx.message)}infraction json {infraction_id}` instead.")
        except Exception as e:
            logger.exception(e)
            return await ctx.send(f'{e.__class__.__name__}: {e}')
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
        } if infraction else None

    @infraction.command()
    @server_mod()
    async def json(self, ctx, infraction_id: int):
        """View the database entry for an infraction in JSON format."""
        try:
            infraction = await infractions.get_infraction(ctx.guild.id, infraction_id)
            if not infraction:
                return await ctx.send(f"{TICK_RED} I couldn't find infraction #{infraction_id} for this guild.")
            serialized = str(self.infraction_to_dict(infraction))
        except Exception as e:
            logger.exception(e)
            return await ctx.send(f'{e.__class__.__name__}: {e}')
        await ctx.send("```py\n" + serialized + "\n```")

    @infraction.command(aliases=['edit-reason'])
    @server_mod()
    async def edit_reason(self, ctx, infraction_id: int, *, new_reason):
        """Edit the reason for an infraction."""
        try:
            infraction = await infractions.get_infraction(ctx.guild.id, infraction_id)
            if not infraction:
                return await ctx.send(f"{TICK_RED} I couldn't find infraction #{infraction_id} for this guild.")
            new_reason = f"{new_reason} (edited by {ctx.author})"
            _, message = await infractions.edit_infraction_and_message(infraction, reason=new_reason)
        except Exception as e:
            logger.exception(e)
            return await ctx.send(f'{e.__class__.__name__}: {e}')
        await ctx.send(message.jump_url)
        
    @infraction.command(aliases=['edit-note'])
    @server_mod()
    async def edit_note(self, ctx, infraction_id: int, *, new_note):
        """Edit the note for an infraction."""
        try:
            infraction = await infractions.get_infraction(ctx.guild.id, infraction_id)
            if not infraction:
                return await ctx.send(f"{TICK_RED} I couldn't find infraction #{infraction_id} for this guild.")
            new_note = f"{new_note} (edited by {ctx.author})"
            _, message = infractions.edit_infraction_and_message(infraction, note=new_note)
        except Exception as e:
            logger.exception(e)
            return await ctx.send(f'{e.__class__.__name__}: {e}')
        await ctx.send(message.jump_url)

    def history_to_dict(self, history):
        return {
            'warn': history.warn,
            'mute': history.mute,
            'unmute': history.unmute,
            'kick': history.kick,
            'ban': history.ban,
            'unban': history.unban,
            'active': history.active,
        } if history else None

    @commands.group(invoke_without_command=True)
    @server_mod()
    async def history(self, ctx, *, user: Union[discord.Member, discord.User, FetchedUser]):
        """View a user's infraction history."""
        try:
            history = await db.History.get_or_none(guild_id=ctx.guild.id, user_id=user.id)
            serialized = str(self.history_to_dict(history))
        except Exception as e:
            logger.exception(e)
            return await ctx.send(f'{e.__class__.__name__}: {e}')
        await ctx.send("```py\n" + serialized + "\n```")

    @history.command()
    @server_admin()
    async def clear(self, ctx, *, user: Union[discord.Member, discord.User, FetchedUser]):
        """Reset a user's infraction history.
        This does not delete any infractions, just cleans the references to them in their history.
        """
        try:
            await db.History.filter(guild_id=ctx.guild.id, user_id=user.id).delete()
        except Exception as e:
            logger.exception(e)
            return await ctx.send(f'{e.__class__.__name__}: {e}')
        await ctx.send(f"Removed infraction history for {user}.")


def setup(bot):
    bot.add_cog(Modlog(bot))
