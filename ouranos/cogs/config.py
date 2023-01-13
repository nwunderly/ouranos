from typing import Union

import disnake
from disnake.ext import commands

from ouranos.dpy.cog import Cog
from ouranos.dpy.command import command, group
from ouranos.settings import Settings
from ouranos.utils import db
from ouranos.utils.checks import is_bot_admin, server_admin
from ouranos.utils.emojis import TICK_GREEN, TICK_RED, TICK_YELLOW


def config_exists(exists=True):
    async def pred(ctx):
        if await is_bot_admin(ctx.author):
            return True
        config = await db.get_config(ctx.guild)
        return bool(config) == exists

    return commands.check(pred)


class Zero(commands.Converter):
    """Resets a configuration setting."""

    async def convert(self, ctx, argument):
        if argument == "0":
            return 0
        else:
            raise commands.BadArgument


class Config(Cog):
    """Bot configuration commands."""

    def __init__(self, bot):
        self.bot = bot

    @command()
    @server_admin()
    @config_exists(False)
    async def init(self, ctx):
        """Create a server config."""
        if await db.create_config(ctx.guild):
            await ctx.send(f"{TICK_GREEN} Successfully created a server config!")
        else:
            await ctx.send(f"{TICK_RED} This server is already set up!")

    @group(aliases=["config", "cfg"])
    @server_admin()
    async def configure(self, ctx):
        config = await db.get_config(ctx.guild)
        p = ctx.prefix
        if not config:
            return await ctx.send(
                f"{TICK_YELLOW} This server is not set up yet. Use `{p}init` to create a config."
            )
        custom_kick_message = f"<view with {p}config custom_kick_message>" if config.custom_kick_message else "<not defined>"
        custom_ban_message = f"<view with {p}config custom_ban_message>" if config.custom_ban_message else "<not defined>"
        await ctx.send(
            f"This server's configuration:```\n"
            f"prefix: {config.prefix}\n"
            f"modlog_channel: {config.modlog_channel_id}\n"
            f"mute_role: {config.mute_role_id}\n"
            f"admin_role: {config.admin_role_id}\n"
            f"mod_role: {config.mod_role_id}\n"
            f"dm_on_infraction: {config.dm_on_infraction}\n"
            f"anti_phish: {config.anti_phish}\n"
            f"custom_kick_message: {custom_kick_message}\n"
            f"custom_ban_message: {custom_ban_message}\n"
            f"```"
        )

    @configure.command()
    @server_admin()
    @config_exists(True)
    async def prefix(self, ctx, prefix=None):
        """Edit this server's prefix."""
        config = await db.get_config(ctx.guild)
        if not prefix:
            return await ctx.send(
                f"My prefix here is `{config.prefix if config else Settings.prefix}`."
            )
        elif len(prefix) > 10:
            return await ctx.send(
                f"{TICK_RED} That prefix is too long! Prefix must be <=10 characters."
            )
        await db.update_config(config=config, prefix=prefix)
        await ctx.send(f"{TICK_GREEN} Prefix updated.")

    @configure.command(aliases=["modlog-channel"])
    @server_admin()
    @config_exists(True)
    async def modlog_channel(
        self, ctx, channel: Union[disnake.TextChannel, Zero] = None
    ):
        """Edit this server's modlog channel. Passing 0 will disable this feature."""
        config = await db.get_config(ctx.guild)
        if channel is None:
            c = config.modlog_channel_id
            return await ctx.send(f"My modlog is set to <#{c}> (id `{c}`).")
        elif channel == 0:  # reset indicator
            channel_id = 0
        else:
            channel_id = channel.id
        await db.update_config(config=config, modlog_channel_id=channel_id)
        await ctx.send(f"{TICK_GREEN} Modlog channel updated.")

    @configure.command(aliases=["mute-role"])
    @server_admin()
    @config_exists(True)
    async def mute_role(self, ctx, role: Union[disnake.Role, Zero] = None):
        """Edit this server's mute role. Passing 0 will disable this feature."""
        config = await db.get_config(ctx.guild)
        if role is None:
            r = config.mute_role_id
            return await ctx.send(
                f"This server's mute role is set to <@&{r}> (id `{r}`).",
                allowed_mentions=disnake.AllowedMentions.none(),
            )
        elif role == 0:  # reset indicator
            role_id = 0
        else:
            role_id = role.id
        await db.update_config(config=config, mute_role_id=role_id)
        await ctx.send(f"{TICK_GREEN} Mute role updated.")

    @configure.command(aliases=["admin-role"])
    @server_admin()
    @config_exists(True)
    async def admin_role(self, ctx, role: Union[disnake.Role, Zero] = None):
        """Edit this server's admin role. Passing 0 will disable this feature."""
        config = await db.get_config(ctx.guild)
        if role is None:
            r = config.admin_role_id
            return await ctx.send(
                f"This server's admin role is set to <@&{r}> (id `{r}`).",
                allowed_mentions=disnake.AllowedMentions.none(),
            )
        elif role == 0:  # reset indicator
            role_id = 0
        else:
            role_id = role.id
        await db.update_config(config=config, admin_role_id=role_id)
        await ctx.send(f"{TICK_GREEN} Admin role updated.")

    @configure.command(aliases=["mod-role"])
    @server_admin()
    @config_exists(True)
    async def mod_role(self, ctx, role: Union[disnake.Role, Zero] = None):
        """Edit this server's mod role. Passing 0 will disable this feature."""
        config = await db.get_config(ctx.guild)
        if role is None:
            r = config.mod_role_id
            return await ctx.send(
                f"This server's mod role is set to <@&{r}> (id `{r}`).",
                allowed_mentions=disnake.AllowedMentions.none(),
            )
        elif role == 0:  # reset indicator
            role_id = 0
        else:
            role_id = role.id
        await db.update_config(config=config, mod_role_id=role_id)
        await ctx.send(f"{TICK_GREEN} Mod role updated.")

    @configure.command(aliases=["dm-on-infraction"])
    @server_admin()
    @config_exists(True)
    async def dm_on_infraction(self, ctx, new_setting: bool = None):
        """If this is enabled, I will DM users to notify them of moderation actions."""
        config = await db.get_config(ctx.guild)
        if new_setting is None:
            dm = config.dm_on_infraction
            return await ctx.send(f"dm_on_infraction is set to `{dm}` for this server.")
        await db.update_config(config=config, dm_on_infraction=new_setting)
        await ctx.send(f"{TICK_GREEN} dm_on_infraction updated.")

    @configure.command(aliases=["anti-phish"])
    @server_admin()
    @config_exists(True)
    async def anti_phish(self, ctx, new_setting: bool = None):
        """Toggle phishing link automod. Deletes message and bans user."""
        config = await db.get_config(ctx.guild)
        if new_setting is None:
            state = config.anti_phish
            return await ctx.send(f"anti_phish is set to `{state}` for this server.")
        await db.update_config(config=config, anti_phish=new_setting)
        await ctx.send(f"{TICK_GREEN} anti_phish updated.")

    @configure.command(aliases=["custom-kick-message"])
    @server_admin()
    @config_exists(True)
    async def custom_kick_message(self, ctx, *, message: str = ""):
        """Add custom content to the alert users are sent before being kicked."""
        config = await db.get_config(ctx.guild)
        if message == "":
            msg = ("\n\n" + config.custom_kick_message) or "<not defined>"
            return await ctx.send(f"custom_kick_message: {msg}")
        await db.update_config(config=config, custom_kick_message=message)
        await ctx.send(f"{TICK_GREEN} custom_kick_message updated.")

    @configure.command(aliases=["custom-ban-message"])
    @server_admin()
    @config_exists(True)
    async def custom_ban_message(self, ctx, *, message: str = ""):
        """Add custom content to the alert users are sent before being banned."""
        config = await db.get_config(ctx.guild)
        if message == "":
            msg = ("\n\n" + config.custom_ban_message) or "<not defined>"
            return await ctx.send(f"custom_ban_message: {msg}")
        await db.update_config(config=config, custom_ban_message=message)
        await ctx.send(f"{TICK_GREEN} custom_ban_message updated.")


def setup(bot):
    bot.add_cog(Config(bot))
