import asyncio
import datetime
import discord
import logging
import random
import signal
import traceback

from discord.ext import commands
from discord.ext import tasks

from ouranos.settings import Settings


logger = logging.getLogger(__name__)


async def prefix(_bot, message, only_guild_prefix=False):
    default = Settings.prefix
    return default
    # if not message.guild:
    #     return commands.when_mentioned(_bot, message) + [default]
    # config = await _bot.db.fetch_config(message.guild.id)
    # if config:
    #     p = config.prefix
    # else:
    #     p = default
    # if only_guild_prefix:
    #     return p
    # else:
    #     return commands.when_mentioned(_bot, message) + [p]



class Ouranos(commands.AutoShardedBot):
    def __init__(self, token, db_url, **kwargs):
        super().__init__(command_prefix=prefix, case_insensitive=True,
                         description='Ouranos by nwunder#4003', **kwargs)
        self.__token = token
        self.__db_url = db_url
        self._nwunder = None
        self._running = False
        self._exit_code = 0
        self.started_at = datetime.datetime.now()
        self.help_command = commands.MinimalHelpCommand()
        logger.info(f'Initialization complete.')

    def run(self):
        """Custom run method, automatically inserts token given on initialization."""
        super().run(self.__token)

    async def start(self, *args, **kwargs):
        """Custom start method, handles async setup before login."""
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
                logger.info(f"-> Loaded {cog}.")
            except Exception:
                logger.exception(f"-> Failed to load extension {cog}.")

    async def unload_cogs(self):
        # TODO
        pass

    async def setup(self):
        """Called when bot is started, before login.
        Use this for any async tasks to be performed before the bot starts.
        (THE BOT WILL NOT BE LOGGED IN WHEN THIS IS CALLED)
        """
        await self.load_cogs(Settings.cogs)
        # TODO: database stuff

    async def cleanup(self):
        """Called when bot is closed, before logging out.
        Use this for any async tasks to be performed before the bot exits.
        """
        pass

    async def on_ready(self):
        logger.info(f'Logged in as {self.user}.')
        self._nwunder = await self.fetch_user(204414611578028034)
        if not self._running:
            self.update_presence.start()
        self._running = True
        logger.info(f"Bot is ready, version {Settings.version}!")

    async def on_message(self, message):
        if message.author.bot:
            return
        if message.guild:
            await self.process_mention(message)
            await self.process_commands(message)

    async def process_mention(self, message):
        if message.content in [self.user.mention, '<@!%s>' % self.user.id]:
            e = await self.get_embed(message)
            await message.channel.send(embed=e)

    async def get_embed(self, message=None):
        p = await self.command_prefix(self, message, only_guild_prefix=True)
        e = discord.Embed(title=f"Ouranos v{Settings.version}",
                          color=Settings.embed_color,
                          description=f"Prefix: `{p}`")
        return e

    async def on_error(self, event_method, *args, **kwargs):
        logger.error(f"Ignoring exception in {event_method}:\n{traceback.format_exc()}")

    async def on_command_error(self, ctx, exception):
        if isinstance(exception, commands.CommandInvokeError):
            exc = traceback.format_exception(exception.__class__, exception, exception.__traceback__)
            exc = ''.join(exc) if isinstance(exc, list) else exc
            logger.error(f"Error invoking command '{ctx.command.qualified_name}' / "
                         f"author {ctx.author.id}, guild {ctx.guild.id if ctx.guild else None}, "
                         f"channel {ctx.channel.id}, "
                         f"message {ctx.message.id}\n"
                         f"{exc}")

    async def on_command_completion(self, ctx):
        logger.info(f"Command '{ctx.command.qualified_name}' invoked / "
                    f"author {ctx.author.id}, "
                    f"guild {ctx.guild.id if ctx.guild else None}, "
                    f"channel {ctx.channel.id}, "
                    f"message {ctx.message.id}")

    @tasks.loop(minutes=20)
    async def update_presence(self):
        activity = None
        name = random.choice(Settings.activities)
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
