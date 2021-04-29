import datetime
import traceback

import discord
import logging
import random
import signal
import asyncio
import json

from discord.ext import commands
from discord.ext import tasks

from ouranos.settings import Settings
from ouranos.utils import database as db
from ouranos.utils.constants import TICK_RED
from ouranos.utils.errors import OuranosCommandError, UnexpectedError


logger = logging.getLogger(__name__)


async def prefix(_bot, message, only_guild_prefix=False):
    default = Settings.prefix
    if not message.guild:
        return commands.when_mentioned(_bot, message) + [default]
    config = await db.get_config(message.guild)
    if config:
        p = config.prefix
    else:
        p = default
    if only_guild_prefix:
        return p
    else:
        return commands.when_mentioned(_bot, message) + [p]


class Ouranos(commands.AutoShardedBot):
    bot = None

    def __init__(self, token, db_url, **kwargs):
        super().__init__(
            command_prefix=prefix,
            case_insensitive=True,
            description=Settings.description,
            help_command=commands.MinimalHelpCommand(),
            intents=Settings.intents,
            allowed_mentions=Settings.allowed_mentions,
            **kwargs
        )
        self.__token = token
        self.__db_url = db_url
        self._running = False
        self._exit_code = 0
        self._blacklist = set()
        self.started_at = datetime.datetime.now()
        self.aloc = 0
        Ouranos.bot = self
        logger.info(f'Initialization complete.')

    async def run_safely(self, coro):
        try:
            await coro
        except Exception as e:
            return e

    async def run_in_background(self, coro):
        async def _task():
            try:
                await coro
            except Exception as e:
                logger.exception(f"Error in background task:")
        self.loop.create_task(_task())

    def run(self):
        """Custom run method, automatically inserts token given on initialization."""
        super().run(self.__token)

    async def start(self, *args, **kwargs):
        """Custom start method, handles async setup before login."""
        logger.debug("Start method called.")
        try:
            self.loop.remove_signal_handler(signal.SIGINT)
            self.loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(self.close()))
        except NotImplementedError:
            pass

        logger.info("Running bot setup.")
        await self.setup()

        logger.info("Running cog setup.")
        for name, cog in self.cogs.items():
            try:
                await cog.setup()
            except AttributeError:
                pass

        logger.info("Setup complete. Logging in.")
        await super().start(*args, **kwargs)

    async def close(self, exit_code=0):
        self._exit_code = exit_code

        logger.info("Running bot cleanup.")
        await self.cleanup()

        logger.info("Running cog cleanup.")
        for name, cog in self.cogs.items():
            try:
                await cog.cleanup()
            except AttributeError:
                pass

        logger.info("Closing connection to discord.")
        await super().close()

    async def load_cog(self, module, cog_name):
        # TODO
        pass

    async def load_cogs(self, cog_names):
        logger.info("Loading cogs.")
        for cog in cog_names:
            try:
                self.load_extension(cog)
                # await self.load_cog(cog)
                logger.info(f"Loaded {cog}.")
            except Exception:
                logger.exception(f"Failed to load extension {cog}.")

    async def unload_cogs(self):
        # TODO
        pass

    async def setup(self):
        """Called when bot is started, before login.
        Use this for any async tasks to be performed before the bot starts.
        (THE BOT WILL NOT BE LOGGED IN WHEN THIS IS CALLED)
        """
        self._aloc()
        await db.init(self.__db_url)
        await self.load_cogs(Settings.cogs)

    async def cleanup(self):
        """Called when bot is closed, before logging out.
        Use this for any async tasks to be performed before the bot exits.
        """
        await db.Tortoise.close_connections()

    async def on_ready(self):
        logger.info(f'Logged in as {self.user}.')
        if not self._running:
            self.update_presence.start()
        self._running = True
        logger.info(f"Bot is ready, version {Settings.version}!")

    async def on_message(self, message):
        if message.author.bot:
            return
        await self.process_mention(message)
        await self.process_commands(message)

    async def process_mention(self, message):
        if message.content in [self.user.mention, '<@!%s>' % self.user.id]:
            if not message.channel.permissions_for(message.guild.me).send_messages:
                try:
                    return await message.author.send("I don't have permission to send messages in that channel!")
                except discord.Forbidden:
                    return
                pass
            p = await self.prefix(message)
            e = discord.Embed(title=f"Ouranos v{Settings.version}",
                              color=Settings.embed_color,
                              description=f"Prefix: `{p}`")
            await message.channel.send(embed=e)

    async def prefix(self, message):
        return await self.command_prefix(self, message, only_guild_prefix=True)

    async def on_error(self, event_method, *args, **kwargs):
        logger.exception(f"Ignoring exception in {event_method}:")

    async def _respond_to_error(self, ctx, error):
        if isinstance(error, commands.UserInputError):
            await ctx.send(f"{TICK_RED} {str(error).capitalize()}")
        elif isinstance(error, UnexpectedError):
            await ctx.send(f'{TICK_RED} An unexpected error occurred:```\n{error.__class__.__name__}: {error}\n```')
        elif isinstance(error, OuranosCommandError):
            await ctx.send(f"{TICK_RED} {error}")
        elif isinstance(error, discord.Forbidden):
            await ctx.send(f'{TICK_RED} I do not have permission to execute this action.')
        elif isinstance(error, commands.CommandInvokeError):
            error = error.original or error
            if isinstance(error, discord.Forbidden):
                await ctx.send(f'{TICK_RED} I do not have permission to execute this action.')
            elif isinstance(error, discord.HTTPException):
                await ctx.send(f'{TICK_RED} An unexpected error occurred:```\n{error.__class__.__name__}: {error.text}\n```')

    async def on_command_error(self, ctx, exception):
        if isinstance(exception, commands.CommandInvokeError):
            logger.error(f"Error invoking command '{ctx.command.qualified_name}' / "
                         f"author {ctx.author.id}, self {ctx.guild.id if ctx.guild else None}, "
                         f"channel {ctx.channel.id}, "
                         f"message {ctx.message.id}\n"
                         f"{''.join(traceback.format_exception(exception.__class__, exception, exception.__traceback__))}")
        try:
            await self._respond_to_error(ctx, exception)
        except discord.DiscordException:
            pass

    async def on_command_completion(self, ctx):
        logger.info(f"Command '{ctx.command.qualified_name}' invoked / "
                    f"author {ctx.author.id}, "
                    f"self {ctx.guild.id if ctx.guild else None}, "
                    f"channel {ctx.channel.id}, "
                    f"message {ctx.message.id}")

    @tasks.loop(minutes=20)
    async def update_presence(self):
        activity = None
        name = random.choice(Settings.activities).format(
            version=Settings.version,
            random_guild_name=random.choice(self.guilds).name,
            user_count=len(self.users),
            guild_count=len(self.guilds),
        )
        if name.lower().startswith("playing "):
            activity = discord.Game(name.replace("playing ", ""))
        elif name.lower().startswith("watching "):
            activity = discord.Activity(type=discord.ActivityType.watching,
                                        name=name.replace("watching", ""))
        elif name.lower().startswith("listening to "):
            activity = discord.Activity(type=discord.ActivityType.listening,
                                        name=name.replace("listening to ", ""))
        if activity:
            await self.change_presence(activity=activity)

    def blacklisted(self, *ids):
        for i in ids:
            if i in self._blacklist:
                return True
        return False

    def load_blacklist(self):
        with open('./data/id_blacklist.json') as fp:
            data = json.load(fp)
            self._blacklist = set(data)

    def dump_blacklist(self):
        with open('./data/id_blacklist.json', 'w') as fp:
            data = list(self._blacklist)
            json.dump(data, fp)

    async def get_or_fetch_member(self, guild, member_id):
        member = guild.get_member(member_id)
        if member is not None:
            return member

        shard = self.get_shard(guild.shard_id)
        if shard.is_ws_ratelimited():
            try:
                member = await guild.fetch_member(member_id)
            except discord.HTTPException:
                return None
            else:
                return member

        members = await guild.query_members(limit=1, user_ids=[member_id], cache=True)
        if not members:
            return None
        return members[0]

    async def confirm_action(self, ctx, message, timeout=5):
        await ctx.channel.send(message)
        try:
            msg = await self.wait_for('message', check=lambda m: m.author == ctx.author, timeout=timeout)
        except asyncio.TimeoutError:
            msg = None
        return msg and msg.content.lower() in ('1', 'true', 'yes', 'y')

    def _aloc(self):
        try:
            with open('./data/aloc.txt') as fp:
                self.aloc = int(fp.read())
        except:
            pass
