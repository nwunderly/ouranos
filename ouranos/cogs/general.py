import datetime
import sys
import time
import discord
import psutil
import pygit2
import itertools

from discord.ext import commands
from loguru import logger

from ouranos.cog import Cog
from ouranos.settings import Settings
from ouranos.utils.helpers import approximate_timedelta
from ouranos.utils.checks import is_bot_admin
from ouranos.utils.constants import PINGBOI, BOTDEV, PYTHON, GIT
from ouranos.utils.stats import Stats


class General(Cog):
    """General bot utilities."""
    def __init__(self, bot):
        self.bot = bot

    @Cog.listener()
    async def on_message(self, _):
        Stats.on_message()

    @Cog.listener()
    async def on_command_completion(self, _):
        Stats.on_command()

    @Cog.listener()
    async def on_log(self, _):
        Stats.on_log()

    def format_commit(self, commit):
        short, _, _ = commit.message.partition('\n')
        short_sha2 = commit.hex[0:6]
        commit_tz = datetime.timezone(datetime.timedelta(minutes=commit.commit_time_offset))
        commit_time = datetime.datetime.fromtimestamp(commit.commit_time).astimezone(commit_tz)

        # [`hash`](url) message (offset)
        offset = approximate_timedelta(datetime.datetime.utcnow() - commit_time.astimezone(datetime.timezone.utc).replace(tzinfo=None))
        return f'[`{short_sha2}`](https://github.com/nwunderly/ouranos/commit/{commit.hex}) {short} ({offset})'

    def get_last_commits(self, count=3):
        repo = pygit2.Repository('.git')
        commits = list(itertools.islice(repo.walk(repo.head.target, pygit2.GIT_SORT_TOPOLOGICAL), count))
        return '\n'.join(self.format_commit(c) for c in commits)

    @commands.command()
    async def about(self, ctx):
        """Some info about me!"""
        embed = discord.Embed(color=Settings.embed_color)
        embed.set_author(name=f"Ouranos", icon_url=Settings.bot_av_url)

        py_v = sys.version_info
        revision = self.get_last_commits()
        description = f'{self.bot.description}\n\n' \
                      f'{BOTDEV} Ouranos v{Settings.version}\n' \
                      f'{PYTHON} Made with discord.py {discord.__version__}, Python {py_v.major}.{py_v.minor}.{py_v.micro}\n\n' \
                      f'{GIT} Recent commits:\n{revision}\n\n'
        embed.description = description

        uptime = datetime.datetime.now()-self.bot.started_at
        memory = int(psutil.Process().memory_info().rss // 10 ** 6)
        embed.add_field(name='Uptime', value=f'{approximate_timedelta(uptime)}\n')
        embed.add_field(name='Memory', value=f'{memory} MB\n')

        embed.add_field(name='ALOC', value=f"{self.bot.aloc} lines")
        embed.add_field(name='Source', value=f'[github]({Settings.repo_url})')
        embed.add_field(name='Support server', value=f'[join]({Settings.support_url})')
        # embed.add_field(name="Add me!", value=f'[invite]({Settings.invite_url})')
        embed.add_field(name="Add me!", value=f'soon:tm:')

        owner = await self.bot.get_or_fetch_member(self.bot.get_guild(Settings.guild_id), Settings.owner_id)
        embed.set_footer(text=f'made with ❤ by {owner}', icon_url=owner.avatar_url)
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
