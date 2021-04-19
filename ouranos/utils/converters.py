import re
import datetime
import time

import discord
from discord.ext import commands

from ouranos.utils import database as db
from ouranos.utils import modlog_utils as modlog
from ouranos.utils.errors import NotConfigured, BotMissingPermission, BotRoleHierarchyError, ModActionOnMod


class FetchedUser(commands.Converter):
    async def convert(self, ctx, argument):
        if not argument.isdigit():
            raise commands.BadArgument('Not a valid user ID.')
        try:
            return await ctx.bot.fetch_user(argument)
        except discord.NotFound:
            raise commands.BadArgument('User not found.') from None
        except discord.HTTPException:
            raise commands.BadArgument('An error occurred while fetching the user.') from None


class Command(commands.Converter):
    async def convert(self, ctx, argument):
        command = ctx.bot.get_command(argument)
        if command:
            return command
        else:
            raise commands.BadArgument("A command with this name could not be found.")


class Module(commands.Converter):
    async def convert(self, ctx, argument):
        cog = ctx.bot.get_cog(argument)
        if cog:
            return cog
        else:
            raise commands.BadArgument("A module with this name could not be found.")


duration_pattern = re.compile(r"(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")


class Duration(commands.Converter):
    async def convert(self, ctx, argument):
        match = duration_pattern.match(argument)

        if not match or match.group(0) == "":
            raise commands.BadArgument("Invalid duration.")

        try:
            w = int(match.group(1) or 0)
            d = int(match.group(2) or 0)
            h = int(match.group(3) or 0)
            m = int(match.group(4) or 0)
            s = int(match.group(5) or 0)
        except ValueError:
            raise commands.BadArgument

        return w*7*24*60*60 + d*24*60*60 + h*60*60 + m*60 + s


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


class Reason(commands.Converter):
    # pattern = re.compile(r"^(?:([\w ]*\w) *)?(?:--note|-n) +(.+)")

    async def convert(self, ctx, argument):
        split = argument.split('--', 1)
        if len(split) == 1:
            reason, note = argument, None
        else:
            reason, note = (x.strip() for x in split)

        r = Reason.format_reason(ctx, reason, note)
        if len(r) > 512:
            reason_max = 512 - len(r) + len(argument)
            raise commands.BadArgument(f'Reason is too long ({len(argument)}/{reason_max})')

        return reason, note, r

    @classmethod
    def format_reason(cls, ctx, reason=None, note=None):
        return f'{ctx.author} (id: {ctx.author.id}): {reason} (note: {note})'


class RequiredReason(Reason):
    async def convert(self, ctx, argument):
        reason, note, r = await super().convert(ctx, argument)
        if not reason:
            raise commands.BadArgument('a reason is required for this command.')
        return reason, note, r


class NotInt(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            int(argument)
            raise commands.BadArgument
        except ValueError:
            return argument
