import re
import datetime
import discord
from discord.ext import commands


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


duration_pattern = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")


class Duration(commands.Converter):
    async def convert(self, ctx, argument):
        match = duration_pattern.match(argument)

        if not match or match.group(0) == "":
            raise commands.BadArgument("Invalid duration.")

        try:
            print("CONVERTING TO HR MIN SEC")
            h = int(match.group(1) or 0)
            m = int(match.group(2) or 0)
            s = int(match.group(3) or 0)
        except ValueError:
            raise commands.BadArgument

        return datetime.timedelta(hours=h, minutes=m, seconds=s)
