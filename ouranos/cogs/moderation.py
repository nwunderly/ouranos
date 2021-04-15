import logging

from discord.ext import commands
from discord.ext import tasks

from ouranos.cog import Cog
from ouranos.utils.checks import server_mod, server_admin


logger = logging.getLogger(__name__)


class Moderation(Cog):
    """Moderation commands."""
    def __init__(self, bot):
        self.bot = bot
        self.check_timers.start()

    async def _do_auto_unmute(self, guild, user):
        pass

    async def _do_auto_unban(self, guild, user):
        pass

    @tasks.loop(seconds=10)
    async def check_timers(self):
        pass

    async def _do_auto_mute(self, guild, user):
        pass

    @Cog.listener()
    async def on_member_join(self, member):
        pass

    @commands.command()
    @server_mod()
    async def warn(self, ctx):
        pass

    @commands.command()
    @server_mod()
    async def mute(self, ctx):
        pass

    @commands.command()
    @server_mod()
    async def unmute(self, ctx):
        pass

    @commands.command()
    @server_mod()
    async def kick(self, ctx):
        pass

    @commands.command()
    @server_mod()
    async def ban(self, ctx):
        pass

    @commands.command()
    @server_mod()
    async def forceban(self, ctx):
        pass

    async def _do_removal(self):
        pass

    @commands.group(aliases=['rm'])
    @server_mod()
    async def remove(self, ctx):
        pass


def setup(bot):
    bot.add_cog(Moderation(bot))
