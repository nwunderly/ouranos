import datetime
import discord
import logging
import psutil
import sys

from discord.ext import commands

from ouranos.cog import Cog
from ouranos.settings import Settings
from ouranos.utils.helpers import approximate_timedelta


logger = logging.getLogger(__name__)


class General(Cog):
    """General bot utilities."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def about(self, ctx):
        """Some info about me!"""
        embed = discord.Embed(color=Settings.embed_color)
        embed.description = self.bot.description
        embed.set_author(name=str(self.bot.user), icon_url=self.bot.user.avatar_url)
        embed.add_field(name="Version", value=Settings.version)
        embed.add_field(name="Library", value='discord.py')
        embed.add_field(name="OS", value='Ubuntu' if sys.platform == 'linux' else 'Windows')

        dt = datetime.datetime.now()-self.bot.started_at
        uptime = approximate_timedelta(dt)

        embed.add_field(name="Uptime", value=uptime)
        memory = int(psutil.Process().memory_info().rss//10**6)
        embed.add_field(name="Memory", value=f"{memory} MB")
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)))
        embed.add_field(name="Users", value=str(len(self.bot.users)))

        embed.add_field(name="Source", value=f'[github]({Settings.repo_url})')
        # embed.add_field(name="Add me!", value=f'[invite]({self.bot.properties.bot_url})')
        # embed.add_field(name="Support server", value=f'[join]({self.bot.properties.server_url})')

        embed.set_footer(text=f'created by {Settings.author}')
        embed.timestamp = self.bot.user.created_at
        await ctx.send(embed=embed)

    @commands.command()
    async def invite(self, ctx):
        """Get the bot's invite URL."""
        url = Settings.invite_url
        await ctx.send(f"This bot is currently private. Please contact {Settings.author} if interested in using it.")


def setup(bot):
    bot.add_cog(General(bot))
