import sys
import time
import datetime
import discord
import psutil
import pygit2
import itertools

from ouranos.settings import Settings
from ouranos.dpy.cog import Cog
from ouranos.dpy.command import command
from ouranos.utils.format import approximate_timedelta
from ouranos.utils.checks import is_bot_admin, server_mod
from ouranos.utils.emojis import TICK_GREEN, PINGBOI, BOTDEV, PYTHON, GIT, CHART, STONKS, NOT_STONKS
from ouranos.utils.stats import Stats


# credit to https://github.com/Rapptz/RoboDanny/blob/rewrite/cogs/stats.py
# for pygit2 code


class General(Cog):
    """General bot commands."""
    def __init__(self, bot):
        self.bot = bot
        self.bot.help_command.cog = self

    def cog_unload(self):
        self.bot.help_command.cog = None

    @Cog.listener()
    async def on_message(self, _):
        Stats.on_message()

    @Cog.listener()
    async def on_command_completion(self, _):
        Stats.on_command()

    @Cog.listener()
    async def on_log(self, log):
        Stats.on_log(log.guild.id)

    @Cog.listener()
    async def on_small_log(self, log):
        Stats.on_log(log.guild.id)

    @Cog.listener()
    async def on_mass_action_log(self, log):
        Stats.on_log(log.guild.id)

    def format_commit(self, commit):
        short, _, _ = commit.message.partition('\n')
        short_sha2 = commit.hex[0:6]
        commit_tz = datetime.timezone(datetime.timedelta(minutes=commit.commit_time_offset))
        commit_time = datetime.datetime.fromtimestamp(commit.commit_time).astimezone(commit_tz)

        # [`hash`](url) message (offset)
        offset = approximate_timedelta(datetime.datetime.utcnow() - commit_time.astimezone(datetime.timezone.utc).replace(tzinfo=None))
        return f'[`{short_sha2}`]({Settings.repo_url}/commit/{commit.hex}) {short} ({offset} ago)'

    def get_last_commits(self, count=3):
        repo = pygit2.Repository('.git')
        commits = list(itertools.islice(repo.walk(repo.head.target, pygit2.GIT_SORT_TOPOLOGICAL), count))
        return '\n'.join(self.format_commit(c) for c in commits)

    @command()
    async def about(self, ctx):
        """Some info about me!"""
        embed = discord.Embed(color=Settings.embed_color, description=self.bot.description)
        embed.set_author(name=f"Ouranos", icon_url=Settings.bot_av_url)

        py_v = sys.version_info
        ver = f'{BOTDEV} Ouranos v{Settings.version}\n' \
              f'{PYTHON} Made with discord.py {discord.__version__}, Python {py_v.major}.{py_v.minor}.{py_v.micro}\n'\
              f'\u200b'
        embed.add_field(name='\u200b', value=ver, inline=False)

        uptime = datetime.datetime.now()-self.bot.started_at
        memory = int(psutil.Process().memory_info().rss // 10 ** 6)
        embed.add_field(name='Uptime', value=f'{approximate_timedelta(uptime)}\n')
        embed.add_field(name='Memory', value=f'{memory} MB\n')

        embed.add_field(name='ALOC', value=f"{self.bot.aloc} lines")
        embed.add_field(name='Source', value=f'[github]({Settings.repo_url})')
        embed.add_field(name='Support server', value=f'[join]({Settings.support_url})')
        # embed.add_field(name="Add me!", value=f'[invite]({Settings.invite_url})')
        embed.add_field(name="Add me!", value=f'soon:tm:')

        revision = self.get_last_commits(2)
        embed.add_field(name='\u200b', value=f'{GIT} Recent commits:\n{revision}', inline=False)

        owner = await self.bot.get_or_fetch_member(self.bot.get_guild(Settings.guild_id), Settings.owner_id)
        embed.set_footer(text=f'made with ❤ by {owner}', icon_url=owner.avatar_url)
        embed.timestamp = self.bot.user.created_at
        await ctx.send(embed=embed)

    @command()
    async def invite(self, ctx):
        """Get the bot's invite URL."""
        if await is_bot_admin(ctx.author):
            await ctx.send(f"<{Settings.invite_url}>")
        else:
            await ctx.send(f"This bot is currently private. Please contact {Settings.author} if interested in using it.")

    @command(aliases=['🏓'])
    async def ping(self, ctx):
        """Pong!"""
        t0 = time.monotonic()
        append = '🏓' if '🏓' in ctx.invoked_with else (PINGBOI if self.bot.user in ctx.message.mentions else '')
        msg = await ctx.send("Pong! " + append)
        dt = time.monotonic() - t0
        await msg.edit(content=msg.content+f"\n⌛ WS: {self.bot.latency*1000:.2f}ms\n⏱ API: {dt*1000:.2f}ms")

    @command()
    async def stats(self, ctx):
        """Show some bot stats."""
        uptime = datetime.datetime.now()-self.bot.started_at

        def s(n):
            return 's' if n != 1 else ''

        await ctx.send(
            f"In the {approximate_timedelta(uptime)} I have been online:\n"
            f"{CHART} I have seen {(_m := Stats.messages_seen):,} message{s(_m)}.\n"
            f"{STONKS} {(_c := Stats.commands_used):,} command{(_s := s(_c))} {'have' if _s else 'has'} been used.\n"
            f"{NOT_STONKS} I have sent {(_l := Stats.logs_sent):,} modlog message{s(_l)} in {(_g := Stats.unique_guilds())} guild{s(_g)}.")

    @command(name='cleanup')
    @server_mod()
    async def _cleanup(self, ctx, limit: int = 30):
        """Cleans up the bot's messages."""
        p = tuple([self.bot.user.mention, f'<@!{self.bot.user.id}>', await self.bot.prefix(ctx.message)])

        def check(m):
            return m.author == self.bot.user or m.content.startswith(p)

        messages = await ctx.channel.purge(limit=limit, check=check)
        await ctx.send(f"{TICK_GREEN} Removed {len(messages)} messages.")


def setup(bot):
    bot.add_cog(General(bot))
