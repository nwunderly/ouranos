import datetime
import time
import discord
import psutil

from discord.ext import commands
from loguru import logger

from ouranos.cog import Cog
from ouranos.settings import Settings
from ouranos.utils.helpers import approximate_timedelta
from ouranos.utils.checks import is_bot_admin
from ouranos.utils.constants import PINGBOI


class General(Cog):
    """General bot utilities."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def about(self, ctx):
        """Some info about me!"""
        embed = discord.Embed(color=Settings.embed_color)
        embed.description = self.bot.description
        embed.set_author(name="Ouranos")
        embed.add_field(name="Version", value=Settings.version)
        embed.add_field(name="Library", value='discord.py')
        embed.add_field(name="ALOC", value=f"{self.bot.aloc} lines")

        dt = datetime.datetime.now()-self.bot.started_at
        uptime = approximate_timedelta(dt)

        embed.add_field(name="Uptime", value=uptime)
        memory = int(psutil.Process().memory_info().rss//10**6)
        embed.add_field(name="Memory", value=f"{memory} MB")
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)))
        embed.add_field(name="Users", value=str(len(self.bot.users)))

        embed.add_field(name="Source", value=f'[github]({Settings.repo_url})')
        # embed.add_field(name="Add me!", value=f'[invite]({Settings.invite_url})')
        embed.add_field(name="Support server", value=f'[join]({Settings.support_url})')

        embed.set_footer(text=f'made with ❤ by {Settings.author}')
        embed.timestamp = self.bot.user.created_at
        await ctx.send(embed=embed)

    @commands.command()
    async def invite(self, ctx):
        """Get the bot's invite URL."""
        if await is_bot_admin(ctx.author):
            await ctx.send(f"<{Settings.invite_url}>")
        else:
            await ctx.send(f"This bot is currently private. Please contact {Settings.author} if interested in using it.")

    @commands.command(aliases=['🏓'])
    async def ping(self, ctx):
        """Pong!"""
        t0 = time.monotonic()
        append = '🏓' if '🏓' in ctx.invoked_with else (PINGBOI if self.bot.user in ctx.message.mentions else '')
        msg = await ctx.send("Pong! " + append)
        dt = time.monotonic() - t0
        await msg.edit(content=msg.content+f"\n⌛ WS: {self.bot.latency*1000:.2f}ms\n⏱ API: {dt*1000:.2f}ms")


def setup(bot):
    bot.add_cog(General(bot))
