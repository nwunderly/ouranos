import aiohttp
import re
import discord

from discord.ext import commands
from loguru import logger
from urllib.parse import urlparse

from auth import PHISH_API, PHISH_IDENTITY
from ouranos.dpy.cog import Cog
from ouranos.dpy.command import command, group
from ouranos.utils import db
from ouranos.utils.checks import server_mod, server_admin, is_server_mod
from ouranos.utils.modlog import LogEvent
from ouranos.utils.errors import OuranosCommandError, BotMissingPermission, BotRoleHierarchyError, ModActionOnMod


class AntiPhish(Cog):
    URL_PATTERN = re.compile(
        # r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
        r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
    )

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    async def cleanup(self):
        await self.session.close()

    def get_domains(self, content):
        urls = [match.group(0) for match in self.URL_PATTERN.finditer(content)]
        domains = set(urlparse(url).netloc for url in urls)
        if "" in domains:
            domains.remove("")
        return domains

    async def is_phish_domain(self, domain):
        async with self.session.get(f"{PHISH_API}/check/{domain}",
                                    headers=PHISH_IDENTITY) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _do_auto_ban(self, guild, user, message, domain):
        """Automatically bans a user and dispatches the event to the modlog."""
        mod = guild.me
        duration = None
        member = message.author

        # some checks to make sure we can actually do this
        if not guild.me.guild_permissions.ban_members:
            raise BotMissingPermission('Ban Members')
        # member is assumed to exist (message is known)
        if not guild.me.top_role > member.top_role:
            raise BotRoleHierarchyError
        if await is_server_mod(member):
            raise ModActionOnMod

        # ban the user (and delete messages from that user)
        audit_reason = f"anti_phish: Phishing link detected ({domain})"
        await guild.ban(user, reason=audit_reason, delete_message_days=1)

        # dispatch the modlog event
        reason = f"Phishing link detected ({domain})"
        await LogEvent('autoban', guild, user, mod, reason, None, duration).dispatch()

    async def process_phishing(self, message):
        # runs regex to find URLs and uses urlparse to extract domain for each
        domains = self.get_domains(message.content)

        if not domains or await is_server_mod(message.author):
            return

        for domain in domains:
            if await self.is_phish_domain(domain):
                try:
                    return await self._do_auto_ban(message.guild, message.author, message, domain)
                except OuranosCommandError:
                    return

    @commands.Cog.listener()
    async def on_message(self, message):
        config = await db.get_config(message.guild)
        if config and config.anti_phish:
            await self.process_phishing(message)


def setup(bot):
    bot.add_cog(AntiPhish(bot))
