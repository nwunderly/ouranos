import asyncio
import datetime
import re

import discord
import logging
from typing import Union

from discord.ext import commands

from ouranos.cog import Cog
from ouranos.utils import db
from ouranos.utils.checks import server_mod
from ouranos.utils.constants import EMOJI_WARN, EMOJI_MUTE, EMOJI_UNMUTE, EMOJI_KICK, EMOJI_BAN, EMOJI_UNBAN
from ouranos.utils.converters import FetchedUser
from ouranos.utils.helpers import approximate_timedelta


logger = logging.getLogger(__name__)


def format_modlog_entry(emoji, title, infraction_id, duration, user, mod, reason, note):
    lines = [
        f"{emoji} **{title} (#{infraction_id})**\n",
        f"**User:** {user} (`{user.id}`)\n",
        f"**Duration:** {duration}\n" if duration else "",
        f"**Moderator:** {mod}\n",
        f"**Reason:** {reason}\n",
        f"**Note:** {note}\n",
    ]
    return "".join(lines)


def edit_modlog_entry(content, **kwargs):
    split = content.split('\n')
    first_line = split[0] + '\n'
    split = split[1:]

    entry = {}
    pattern = re.compile(r'\*\*(\w+):\*\* (.*)')
    for line in split:
        match = pattern.match(line)
        entry[match.group(1).lower()] = match.group(2)

    entry.update(kwargs)
    return first_line + "".join(f"**{key.upper()}:** {value}\n" for key, value in entry.items())


class Modlog(Cog):
    """Ouranos' custom built modlog."""
    def __init__(self, bot):
        self.bot = bot
        self._last_case_id_cache = {}
        self._last_audit_id_cache = {}

    async def get_case_id(self, guild_id):
        if guild_id in self._last_case_id_cache:
            misc = self._last_case_id_cache[guild_id]
        else:
            misc, _ = await db.MiscData.get_or_create(guild_id=guild_id)
        misc.last_case_id += 1
        await misc.save()
        infraction_id = misc.last_case_id
        self._last_case_id_cache[guild_id] = misc
        return infraction_id

    async def new_infraction(self, guild_id, user_id, mod_id, type, reason, note, duration):
        infraction_id = await self.get_case_id(guild_id)
        created_at = datetime.datetime.now()
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
            ends_at=ends_at
        )
        history, _ = await db.History.get_or_create(
            {'warn': [], 'mute': [], 'unmute': [], 'kick': [], 'ban': [], 'unban': []},
            guild_id=guild_id, user_id=user_id
        )
        history.__getattribute__(type).append(infraction_id)
        await history.save()
        return infraction_id, infraction

    async def set_message_id(self, infraction, message_id):
        infraction.message_id = message_id
        await infraction.save()

    async def dispatch_log_message(self, guild, content):
        config = await db.get_config(guild)
        channel = guild.get_channel(config.modlog_channel_id)
        message = await channel.send(content)
        return message.id

    async def log_warn(self, guild, user, mod, reason, note):
        infraction_id, infraction = await self.new_infraction(guild.id, user.id, mod.id, 'warn', reason, note, None)
        content = format_modlog_entry(EMOJI_WARN, 'MEMBER WARNED', infraction_id, None, user, mod, reason, note)
        message_id = await self.dispatch_log_message(guild, content)
        await self.set_message_id(infraction, message_id)

    async def log_mute(self, guild, user, mod, reason, note, duration):
        infraction_id, infraction = await self.new_infraction(guild.id, user.id, mod.id, 'mute', reason, note, duration)
        duration = approximate_timedelta(duration) if duration else None
        content = format_modlog_entry(EMOJI_MUTE, 'MEMBER MUTED', infraction_id, duration, user, mod, reason, note)
        message_id = await self.dispatch_log_message(guild, content)
        await self.set_message_id(infraction, message_id)

    async def log_unmute(self, guild, user, mod, reason, note):
        infraction_id, infraction = await self.new_infraction(guild.id, user.id, mod.id, 'unmute', reason, note, None)
        content = format_modlog_entry(EMOJI_UNMUTE, 'MEMBER UNMUTED', infraction_id, None, user, mod, reason, note)
        message_id = await self.dispatch_log_message(guild, content)
        await self.set_message_id(infraction, message_id)

    async def log_kick(self, guild, user, mod, reason, note):
        infraction_id, infraction = await self.new_infraction(guild.id, user.id, mod.id, 'kick', reason, note, None)
        content = format_modlog_entry(EMOJI_KICK, 'MEMBER KICKED', infraction_id, None, user, mod, reason, note)
        message_id = await self.dispatch_log_message(guild, content)
        await self.set_message_id(infraction, message_id)

    async def log_ban(self, guild, user, mod, reason, note):
        infraction_id, infraction = await self.new_infraction(guild.id, user.id, mod.id, 'ban', reason, note, None)
        content = format_modlog_entry(EMOJI_BAN, 'MEMBER BANNED', infraction_id, None, user, mod, reason, note)
        message_id = await self.dispatch_log_message(guild, content)
        await self.set_message_id(infraction, message_id)

    async def log_forceban(self, guild, user, mod, reason, note):
        infraction_id, infraction = await self.new_infraction(guild.id, user.id, mod.id, 'ban', reason, note, None)
        content = format_modlog_entry(EMOJI_BAN, 'USER FORCEBANNED', infraction_id, None, user, mod, reason, note)
        message_id = await self.dispatch_log_message(guild, content)
        await self.set_message_id(infraction, message_id)

    async def log_unban(self, guild, user, mod, reason, note):
        infraction_id, infraction = await self.new_infraction(guild.id, user.id, mod.id, 'unban', reason, note, None)
        content = format_modlog_entry(EMOJI_UNBAN, 'USER UNBANNED', infraction_id, None, user, mod, reason, note)
        message_id = await self.dispatch_log_message(guild, content)
        await self.set_message_id(infraction, message_id)

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

        await asyncio.sleep(2)

        async for entry in guild.audit_logs(limit=5):
            if entry.action == discord.AuditLogAction.ban and entry.target == user:
                logger.debug("audit log entry found")
                moderator = entry.user
                reason = entry.reason
                break

        # TODO: fix this
        # if isinstance(user, discord.User):  # forceban
        #     logger.debug("it's a forceban")
        #     await self.log_forceban(guild, user, moderator, reason, None)
        # else:  # regular ban
        #     logger.debug("it's a regular ban")
        await self.log_ban(guild, user, moderator, reason, None)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        if not await self.guild_has_modlog_config(guild):
            return

        logger.debug("possible kick detected")
        moderator = None
        reason = None

        await asyncio.sleep(2)

        async for entry in guild.audit_logs(limit=5):
            if entry.action == discord.AuditLogAction.kick and entry.target == member:
                logger.debug("audit log entry found, it's a kick. logging")
                moderator = entry.user
                reason = entry.reason
                break
            elif entry.action == discord.AuditLogAction.ban and entry.target == member:
                logger.debug("audit log entry found, it's a ban. ignoring")
                return

        if not moderator:
            logger.debug("no audit log entry found. member left the server.")
        else:
            await self.log_kick(guild, member, moderator, reason, None)

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
            await self.log_unmute(guild, member, moderator, reason, None)

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
            await self.log_mute(guild, member, moderator, reason, None, None)

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

        await self.log_unban(guild, user, moderator, reason, None)

    @commands.group(name='case', aliases=['inf'], invoke_without_command=True)
    @server_mod()
    async def infraction(self, ctx, infraction_id: int):
        """Base command for modlog. Passing an int will return the link to the message associated with a particular infraction."""
        try:
            config = await db.get_config(ctx.guild)
            modlog_channel = ctx.guild.get_channel(config.modlog_channel_id)
            infraction = await db.Infraction.get_or_none(guild_id=ctx.guild.id, infraction_id=infraction_id)
            message_id = infraction.message_id
            message = await modlog_channel.fetch_message(message_id)
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
            infraction = await db.Infraction.get_or_none(guild_id=ctx.guild.id, infraction_id=infraction_id)
            message_id = infraction.message_id
            message = await modlog_channel.fetch_message(message_id)
        except Exception as e:
            logger.exception(e)
            return await ctx.send(f'{e.__class__.__name__}: {e}')
        await ctx.send(message.content)

    def infraction_to_dict(self, infraction):
        return {
            'id': infraction.id,
            'guild_id': infraction.guild_id,
            'infraction_id': infraction.infraction_id,
            'user_id': infraction.user_id,
            'mod_id': infraction.message_id,
            'message_id': infraction.message_id,
            'type': infraction.type,
            'reason': infraction.reason,
            'note': infraction.note,
            'created_at': infraction.created_at,
            'ends_at': infraction.ends_at,
            'active': infraction.active,
        } if infraction else None

    @infraction.command()
    @server_mod()
    async def json(self, ctx, infraction_id: int):
        """View the database entry for an infraction in JSON format."""
        try:
            infraction = await db.Infraction.get_or_none(guild_id=ctx.guild.id, infraction_id=infraction_id)
            serialized = str(self.infraction_to_dict(infraction))
        except Exception as e:
            logger.exception(e)
            return await ctx.send(f'{e.__class__.__name__}: {e}')
        await ctx.send("```py\n" + serialized + "\n```")

    def history_to_dict(self, history):
        return {
            'warn': history.warn,
            'mute': history.mute,
            'unmute': history.unmute,
            'kick': history.kick,
            'ban': history.ban,
            'unban': history.unban,
        } if history else None

    @infraction.command()
    @server_mod()
    async def list(self, ctx, user: Union[discord.Member, discord.User, FetchedUser]):
        """View a user's infraction history."""
        try:
            history = await db.History.get_or_none(guild_id=ctx.guild.id, user_id=user.id)
            serialized = str(self.history_to_dict(history))
        except Exception as e:
            logger.exception(e)
            return await ctx.send(f'{e.__class__.__name__}: {e}')
        await ctx.send("```py\n" + serialized + "\n```")

    @infraction.command(aliases=['edit-reason'])
    @server_mod()
    async def edit_reason(self, ctx, infraction_id: int, field, *, new_reason):
        """Edit the reason for an infraction."""
        try:
            config = await db.get_config(ctx.guild)
            modlog_channel = ctx.guild.get_channel(config.modlog_channel_id)
            infraction = await db.Infraction.get_or_none(guild_id=ctx.guild.id, infraction_id=infraction_id)
            message = await modlog_channel.fetch_message(infraction.message_id)
            infraction.reason = f"{new_reason} (edited by {ctx.author})"
            content = edit_modlog_entry(message.content, reason=new_reason)
            await message.edit(content=content)
        except Exception as e:
            logger.exception(e)
            return await ctx.send(f'{e.__class__.__name__}: {e}')
        await ctx.send(message.jump_url)
        
    @infraction.command(aliases=['edit-note'])
    @server_mod()
    async def edit_note(self, ctx, infraction_id: int, field, *, new_note):
        """Edit the note for an infraction."""
        try:
            config = await db.get_config(ctx.guild)
            modlog_channel = ctx.guild.get_channel(config.modlog_channel_id)
            infraction = await db.Infraction.get_or_none(guild_id=ctx.guild.id, infraction_id=infraction_id)
            message = await modlog_channel.fetch_message(infraction.message_id)
            infraction.note = f"{new_note} (edited by {ctx.author})"
            content = edit_modlog_entry(message.content, note=new_note)
            await message.edit(content=content)
        except Exception as e:
            logger.exception(e)
            return await ctx.send(f'{e.__class__.__name__}: {e}')
        await ctx.send(message.jump_url)

    # @infraction.command()
    # @server_mod()
    # async def claim(self, ctx, infraction_id: int = None):
    #     """NOT YET IMPLEMENTED."""
    #     await ctx.send("NOT YET IMPLEMENTED.")


def setup(bot):
    bot.add_cog(Modlog(bot))
