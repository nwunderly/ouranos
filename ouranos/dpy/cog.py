from disnake.ext import commands


class Cog(commands.Cog):
    """Cog class with async setup/cleanup methods."""

    async def setup(self):
        pass

    async def cleanup(self):
        pass
