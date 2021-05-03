import asyncio

from discord.ext import commands

from ouranos.utils.errors import ActionTimedOut, ActionCanceled


class Context(commands.Context):
    """Custom context utilities."""
    async def confirm_action(self, message, timeout=10):
        """returns if good to go, otherwise raises an error that will cancel the action and cause the bot to respond."""
        await self.channel.send(message)

        def check(m):
            return (m.author == self.author) and m.content and (m.content.lower() in ('y', 'yes', 'n', 'no'))

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=timeout)
        except asyncio.TimeoutError:
            raise ActionTimedOut
        if msg and msg.content:
            if msg.content.lower() not in ('y', 'yes'):
                raise ActionCanceled
