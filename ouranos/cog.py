import logging
from discord.ext import commands


logger = logging.getLogger(__name__)


class Cog(commands.Cog):
    """Cog class with async setup/cleanup methods."""

    async def setup(self):
        pass

    async def cleanup(self):
        pass
