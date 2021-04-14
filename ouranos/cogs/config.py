import discord

from discord.ext import commands
from typing import Union

from ouranos.cog import Cog
from ouranos.utils import db
from ouranos.utils.checks import is_bot_admin, server_admin, server_mod
from ouranos.utils.constants import green_tick, red_tick, yellow_tick


def config_exists(exists):
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
    """Bot configuration."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @server_admin()
    @config_exists(False)
    async def init(self, ctx):
        """Create a server config."""
        if await db.create_config(ctx.guild):
            await ctx.send(f"{green_tick} Successfully created a server config!")
        else:
            await ctx.send(f"{red_tick} This server is already set up!")

    @commands.group(invoke_without_command=True)
    @server_admin()
    async def config(self, ctx):
        config = await db.get_config(ctx.guild)
        if not config:
            p = await ctx.bot.prefix(ctx.message)
            return await ctx.send(f"{yellow_tick} This server is not set up yet. Use {p}init to create a config.")
        await ctx.send(
            f"```\n"
            f"Configuration for {ctx.guild.name} ({ctx.guild.id})\n"
            f" - prefix: {config.prefix}\n"
            f" - modlog_channel: {config.modlog_channel_id}\n"
            f" - mute_role: {config.mute_role_id}\n"
            f" - admin_role: {config.admin_role_id}\n"
            f" - mod_role: {config.mod_role_id}\n"
            f" - dm_on_infraction: {config.dm_on_infraction}\n"
            f"```"
        )

    @config.command()
    @server_admin()
    @config_exists(True)
    async def prefix(self, ctx, prefix=None):
        """Edit this server's prefix."""
        config = await db.get_config(ctx.guild)
        if not prefix:
            return await ctx.send(f"My prefix here is `{config.prefix}`.")
        elif len(prefix) > 10:
            return await ctx.send(f"{red_tick} That prefix is too long! Prefix must be <=10 characters.")
        await db.update_config(config=config, prefix=prefix)
        await ctx.send(f"{green_tick} Prefix updated.")

    @config.command()
    @server_admin()
    @config_exists(True)
    async def modlog_channel(self, ctx, channel: Union[discord.TextChannel, Zero] = None):
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
        await ctx.send(f"{green_tick} Modlog channel updated.")

    @config.command()
    @server_admin()
    @config_exists(True)
    async def mute_role(self, ctx, role: Union[discord.Role, Zero] = None):
        """Edit this server's mute role. Passing 0 will disable this feature."""
        config = await db.get_config(ctx.guild)
        if role is None:
            r = config.mute_role_id
            return await ctx.send(f"This server's mute role is set to <@&{r}> (id `{r}`).",
                                  allowed_mentions=discord.AllowedMentions.none())
        elif role == 0:  # reset indicator
            role_id = 0
        else:
            role_id = role.id
        await db.update_config(config=config, mute_role_id=role_id)
        await ctx.send(f"{green_tick} Mute role updated.")

    @config.command()
    @server_admin()
    @config_exists(True)
    async def admin_role(self, ctx, role: Union[discord.Role, Zero] = None):
        """Edit this server's admin role. Passing 0 will disable this feature."""
        config = await db.get_config(ctx.guild)
        if role is None:
            r = config.admin_role_id
            return await ctx.send(f"This server's admin role is set to <@&{r}> (id `{r}`).",
                                  allowed_mentions=discord.AllowedMentions.none())
        elif role == 0:  # reset indicator
            role_id = 0
        else:
            role_id = role.id
        await db.update_config(config=config, admin_role_id=role_id)
        await ctx.send(f"{green_tick} Admin role updated.")

    @config.command()
    @server_admin()
    @config_exists(True)
    async def mod_role(self, ctx, role: Union[discord.Role, Zero] = None):
        """Edit this server's mod role. Passing 0 will disable this feature."""
        config = await db.get_config(ctx.guild)
        if role is None:
            r = config.mod_role_id
            return await ctx.send(f"This server's mod role is set to <@&{r}> (id `{r}`).",
                                  allowed_mentions=discord.AllowedMentions.none())
        elif role == 0:  # reset indicator
            role_id = 0
        else:
            role_id = role.id
        await db.update_config(config=config, mod_role_id=role_id)
        await ctx.send(f"{green_tick} Mod role updated.")

    @config.command()
    @server_admin()
    @config_exists(True)
    async def dm_on_infraction(self, ctx, new_setting: bool = None):
        """If this is enabled, I will DM users to notify them of moderation actions."""
        config = await db.get_config(ctx.guild)
        if new_setting is None:
            dm = config.dm_on_infraction
            return await ctx.send(f"dm_on_infraction is set to `{dm}` for this server.")
        await db.update_config(config=config, dm_on_infraction=new_setting)
        await ctx.send(f"{green_tick} dm_on_infraction updated.")


def setup(bot):
    bot.add_cog(Config(bot))