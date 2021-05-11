import re
import discord

from discord.ext import commands
from discord.ext.commands import Converter, BadArgument

from ouranos.utils import database as db
from ouranos.utils import modlog_utils as modlog
from ouranos.utils.errors import NotConfigured, BotMissingPermission
from ouranos.utils.helpers import DAY


class FetchedUser(Converter):
    async def convert(self, ctx, argument):
        if not argument.isdigit():
            raise BadArgument('Not a valid user ID.')
        try:
            return await ctx.bot.fetch_user(argument)
        except discord.NotFound:
            raise BadArgument('User not found.') from None
        except discord.HTTPException:
            raise BadArgument('An error occurred while fetching the user.') from None


class Command(Converter):
    async def convert(self, ctx, argument):
        command = ctx.bot.get_command(argument)
        if command:
            return command
        else:
            raise BadArgument("A command with this name could not be found.")


class Module(Converter):
    async def convert(self, ctx, argument):
        cog = ctx.bot.get_cog(argument)
        if cog:
            return cog
        else:
            raise BadArgument("A module with this name could not be found.")


duration_pattern = re.compile(r"(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")


class Duration(Converter):
    @classmethod
    def _real_convert(cls, argument):
        if argument.lower() in ('permanent', 'perm'):
            return None
        match = duration_pattern.match(argument)

        if not match or match.group(0) == "":
            raise BadArgument("Invalid duration.")

        try:
            w = int(match.group(1) or 0)
            d = int(match.group(2) or 0)
            h = int(match.group(3) or 0)
            m = int(match.group(4) or 0)
            s = int(match.group(5) or 0)
        except ValueError:
            raise BadArgument

        dur = w*7*24*60*60 + d*24*60*60 + h*60*60 + m*60 + s

        if dur >= DAY*365*5:  # ~5 years
            return None

        return dur

    async def convert(self, ctx, argument):
        return self.__class__._real_convert(argument)


class UserID(Converter):
    async def convert(self, ctx, argument):
        try:
            m = await commands.MemberConverter().convert(ctx, argument)
        except BadArgument:
            try:
                member_id = int(argument, base=10)
            except ValueError:
                raise BadArgument(f"{argument} is not a valid user or user ID.") from None
            else:
                m = await ctx.bot.get_or_fetch_member(ctx.guild, member_id)
                if m is None:
                    # hackban case
                    return type('_Hackban', (), {'id': member_id, '__str__': lambda s: f'User ID {s.id}'})()
        return m


userid_pattern = re.compile(r"<@!?(\d+)>")


class MBanUserID(Converter):
    async def convert(self, ctx, argument):
        try:
            match = userid_pattern.match(argument)
            if match:
                member_id = int(match.group(1))
            else:
                member_id = int(argument, base=10)
        except ValueError:
            raise BadArgument(f"{argument} is not a valid user or user ID.") from None
        else:
            return discord.Object(member_id)


class MutedUser(Converter):
    async def _from_guild(self, ctx, member):
        config = await db.get_config(ctx.guild)
        if config and config.mute_role_id:
            role = ctx.guild.get_role(config.mute_role_id)
            if role in member.roles:
                return member, True
            else:
                raise BadArgument('This user is not muted.')
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
        except BadArgument as _e:
            e = _e
        obj = await self._from_db(ctx, member.id if member else argument)
        if obj:
            return obj, False
        else:
            raise e


class BannedUser(Converter):
    async def _from_bans(self, ctx, argument):
        if not ctx.guild.me.guild_permissions.ban_members:
            raise BotMissingPermission("Ban Members")
        if argument.isdigit():
            member_id = int(argument, base=10)
            try:
                return await ctx.guild.fetch_ban(discord.Object(id=member_id)), True
            except discord.NotFound:
                raise BadArgument('This user is not banned.') from None

        ban_list = await ctx.guild.bans()
        entity = discord.utils.find(lambda u: str(u.user) == argument, ban_list)
        if entity is None:
            raise BadArgument('This user is not banned.')
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
        except BadArgument as _e:
            e = _e
        m = await self._from_db(ctx, argument)
        if m:
            return m, False
        else:
            raise e


class Reason(Converter):
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
            raise BadArgument(f'Reason is too long ({len(argument)}/{reason_max})')

        return reason, note, r

    @classmethod
    def format_reason(cls, ctx, reason=None, note=None):
        return f'{ctx.author} ({ctx.author.id}): {reason} (note: {note})'


class RequiredReason(Reason):
    async def convert(self, ctx, argument):
        reason, note, r = await super().convert(ctx, argument)
        if not reason:
            raise BadArgument('a reason is required for this command.')
        return reason, note, r


class NotInt(Converter):
    async def convert(self, ctx, argument):
        try:
            int(argument)
            raise BadArgument
        except ValueError:
            return argument


class A_OR_B(Converter):
    OPTION_A = None
    OPTION_B = None

    async def convert(self, ctx, argument):
        a = argument.lower()
        if a == self.OPTION_A:
            return True
        elif a == self.OPTION_B:
            return False
        else:
            raise BadArgument(f"Expected `{self.OPTION_A}` or `{self.OPTION_B}`, got `{argument}`.")


class Guild(Converter):
    async def convert(self, ctx, argument):
        if argument == '.':
            return ctx.guild
        else:
            return await commands.GuildConverter().convert(ctx, argument)


class TextChannel(Converter):
    async def convert(self, ctx, argument):
        if argument == '.':
            return ctx.channel
        else:
            return await commands.TextChannelConverter().convert(ctx, argument)


# TODO: more advanced query tools
# infraction_id_pattern = re.compile(r"(?:(?:(?P<what>user|mod)=)?(?P<who>\d+|me):)?(?P<id>-?\d+)")


class InfractionID(Converter):
    async def convert(self, ctx, argument):
        if argument.lower() in ('last', 'l'):
            argument = -1
        try:
            infraction_id = int(argument)
        except ValueError:
            raise BadArgument("Invalid infraction id.")

        # case negative id (look backwards)
        if infraction_id < 0:
            next_id = await modlog.get_case_id(ctx.guild.id, increment=False)
            infraction_id += next_id

        return infraction_id

