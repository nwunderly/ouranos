import logging

from discord.ext import commands

from ouranos.cog import Cog
from ouranos.utils import database as db
from ouranos.utils import modlog_utils as modlog
from ouranos.utils.checks import bot_admin

logger = logging.getLogger(__name__)


class AddOrRemove(commands.Converter):
    async def convert(self, ctx, argument):
        a = argument.lower()
        if a == 'add':
            return True
        elif a == 'remove':
            return False
        else:
            raise commands.BadArgument


class Admin(Cog):
    """Bot admin utilities."""
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name='db', invoke_without_command=True)
    @bot_admin()
    async def _db(self, ctx):
        """Database admin actions."""
        await ctx.send_help(self._db)

    @_db.command(aliases=['clear-config'])
    @bot_admin()
    async def clear_config(self, ctx, guild_id: int):
        """Remove a guild's configuration from the database."""
        try:
            result = await db.Config.filter(guild_id=guild_id).delete()
        except Exception as e:
            result = f"{e.__class__.__name__}: {e}"
        db.config_cache.pop(guild_id)
        await ctx.send(f"```py\n{result}\n```")

    @_db.command(aliases=['clear-modlog'])
    @bot_admin()
    async def clear_modlog(self, ctx, guild_id: int):
        """Completely remove a guild's modlog data from the database."""
        # remove infractions
        try:
            result_1 = await db.Infraction.filter(guild_id=guild_id).delete()
        except Exception as e:
            result_1 = f"{e.__class__.__name__}: {e}"

        # remove user history
        try:
            result_2 = await db.History.filter(guild_id=guild_id).delete()
        except Exception as e:
            result_2 = f"{e.__class__.__name__}: {e}"

        try:
            misc = await db.MiscData.get_or_none(guild_id=guild_id)
            if misc:
                if guild_id in modlog.last_case_id_cache:
                    modlog.last_case_id_cache.pop(guild_id)
                misc.last_case_id = 0
                await misc.save()
                result_3 = True
            else:
                result_3 = False
        except Exception as e:
            result_3 = f"{e.__class__.__name__}: {e}"

        await ctx.send(
            f"Infractions:```py\n{result_1}\n```\n"
            f"History:```py\n{result_2}\n```\n"
            f"Misc (last_case_id):```py\n{result_3}\n```\n"
        )

    @commands.command()
    @bot_admin()
    async def blacklist(self, ctx, add_or_remove: AddOrRemove = None, id: int = 0):
        """Add or remove a user or guild id from the bot's blacklist."""
        # view
        if add_or_remove is None or not id:
            return await ctx.send(f"```py\n{self.bot._blacklist}\n```")

        # add
        elif add_or_remove is True:
            if id not in self.bot._blacklist:
                self.bot._blacklist.add(id)
            else:
                return await ctx.send("That id is already blacklisted!")
        # remove
        else:
            if id in self.bot._blacklist:
                self.bot._blacklist.remove(id)
            else:
                return await ctx.send("That id is not blacklisted!")

        # confirm
        self.bot.dump_blacklist()
        await ctx.send("Done!")

    @commands.command()
    @bot_admin()
    async def load(self, ctx, cog):
        try:
            self.bot.load_extension(f"ouranos.cogs.{cog}")
            await ctx.send(f"Loaded {cog}!")
        except Exception as e:
            await ctx.send(f"```py\n{e.__class__.__name__}: {e}\n```")

    @commands.command()
    @bot_admin()
    async def unload(self, ctx, cog):
        try:
            self.bot.unload_extension(f"ouranos.cogs.{cog}")
            await ctx.send(f"Unloaded {cog}!")
        except Exception as e:
            await ctx.send(f"```py\n{e.__class__.__name__}: {e}\n```")

    @commands.command()
    @bot_admin()
    async def reload(self, ctx, cog):
        try:
            self.bot.reload_extension(f"ouranos.cogs.{cog}")
            await ctx.send(f"Reloaded {cog}!")
        except Exception as e:
            await ctx.send(f"```py\n{e.__class__.__name__}: {e}\n```")


def setup(bot):
    bot.add_cog(Admin(bot))
