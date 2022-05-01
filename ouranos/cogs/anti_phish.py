import re
from urllib.parse import urlparse

import aiohttp
import discord
from auth import PHISH_API, PHISH_IDENTITY
from discord.ext import commands
from loguru import logger

from ouranos.dpy.cog import Cog
from ouranos.dpy.command import command, group
from ouranos.utils import db
from ouranos.utils.checks import is_server_mod, server_admin, server_mod
from ouranos.utils.errors import (
    BotMissingPermission,
    BotRoleHierarchyError,
    ModActionOnMod,
    OuranosCommandError,
)
from ouranos.utils.modlog import LogEvent


def _load_file(file):
    with open(file, "r") as f:
        return f.read().splitlines()


SHORTENERS_FILE = "shorteners.txt"
SHORTENERS = tuple(_load_file(SHORTENERS_FILE))

URL_PATTERN = re.compile(
    # r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
    r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
)


class AntiPhish(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    def cog_unload(self):
        self.bot.loop.create_task(self.cleanup())

    async def cleanup(self):
        await self.session.close()

    def get_domains(self, content):
        content = content.replace("\u0000", "")  # NUL char handling (temp fix) (TODO)
        urls = [match.group(0) for match in URL_PATTERN.finditer(content)]

        # domains = set(urlparse(url).netloc for url in urls)
        # bitly link handling (temp fix) (TODO)
        domains = set()
        to_follow = set()
        for url in urls:
            parsed = urlparse(url)
            if parsed.netloc:
                if parsed.netloc.startswith(SHORTENERS):
                    to_follow.add(url)
                else:
                    domains.add(parsed.netloc)

        if "" in domains:
            domains.remove("")

        return domains, to_follow

    async def is_phish_domain(self, domain):
        async with self.session.get(
            f"{PHISH_API}/check/{domain}", headers=PHISH_IDENTITY
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def follow_redirect(self, url):
        async with self.session.get(url, allow_redirects=False) as resp:
            if 300 <= resp.status < 400:
                return resp.headers["Location"]

    async def _do_auto_ban(self, guild, user, message, domain, from_redirect):
        """Automatically bans a user and dispatches the event to the modlog."""
        mod = guild.me
        duration = None
        member = message.author

        # some checks to make sure we can actually do this
        if not guild.me.guild_permissions.ban_members:
            raise BotMissingPermission("Ban Members")
        # member is assumed to exist (message is known)
        if not guild.me.top_role > member.top_role:
            raise BotRoleHierarchyError
        if await is_server_mod(member):
            raise ModActionOnMod

        # ban the user (and delete messages from that user)
        audit_reason = f"anti_phish: Phishing link detected ({domain})"
        if from_redirect:
            audit_reason += f" (from {from_redirect})"
        await guild.ban(user, reason=audit_reason, delete_message_days=1)

        # dispatch the modlog event
        reason_domain = f"{from_redirect} -> {domain}" if from_redirect else domain
        reason = f"Phishing link detected ({reason_domain})"
        await LogEvent("autoban", guild, user, mod, reason, None, duration).dispatch()

    async def process_phishing(self, content):
        # runs regex to find URLs and uses urlparse to extract domain for each
        domains, to_follow = self.get_domains(content)

        if not (domains or to_follow):
            return None, None

        # follow redirects and add those domains to the list
        # note: this implementation only follows redirects one level deep (intentional)
        domains_from_redirect = {}
        for url in to_follow:
            new_url = await self.follow_redirect(url)
            if new_url:
                new_domain = urlparse(new_url).netloc
                if new_domain:
                    if new_domain not in domains_from_redirect:
                        old_url_parsed = urlparse(url)
                        domains_from_redirect[new_domain] = (
                            old_url_parsed.netloc + old_url_parsed.path
                        )
                    domains.add(new_domain)

        # check API and ban if phishing
        for domain in domains:
            if await self.is_phish_domain(domain):
                from_redirect = domains_from_redirect.get(domain)
                return domain, from_redirect

        return None, None

    @commands.Cog.listener()
    async def on_message(self, message):
        config = await db.get_config(message.guild)
        if not (config and config.anti_phish):
            return

        # ignore server moderators
        if await is_server_mod(message.author):
            return

        domain, from_redirect = await self.process_phishing(message.content)

        if domain:
            try:
                return await self._do_auto_ban(
                    message.guild, message.author, message, domain, from_redirect
                )
            except OuranosCommandError:
                return

    @command()
    @server_mod()
    async def test_antiphish(self, ctx, *, content):
        """Test anti-phish system."""
        domain, from_redirect = await self.process_phishing(content)

        if domain:
            await ctx.send(
                f"{domain} is a phishing domain"
                + (f" (from {from_redirect})" if from_redirect else "")
            )
        else:
            await ctx.send("No phishing domains detected.")


def setup(bot):
    bot.add_cog(AntiPhish(bot))
