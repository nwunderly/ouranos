import discord
from discord.ext import commands

from ouranos.settings import Settings
from ouranos.utils import db


# checks that apply to every command invocation
async def global_checks(ctx):
    if await is_bot_admin(ctx.author):
        return True
    if ctx.guild is None:
        return False
    if ctx.bot.blacklisted(ctx.author.id, ctx.guild.id, ctx.guild.owner.id):
        try:
            await ctx.send("I won't respond to commands from blacklisted users or in blacklisted guilds!")
        except discord.Forbidden:
            pass
        return False
    return True


async def is_bot_admin(user):
    return user.id in Settings.admins


def bot_admin():
    async def pred(ctx):
        return await is_bot_admin(ctx.author)
    return commands.check(pred)


async def config_perm_check(ctx, permission):
    if await is_bot_admin(ctx):
        return True

    config = await db.get_config(ctx.guild.id)
    return ctx.guild.get_role(config.get(f'{permission}_role_id')) in ctx.author.roles


async def guild_perm_check(ctx, perms, *, check=all):
    if await is_bot_admin(ctx.author):
        return True

    resolved = ctx.author.guild_permissions
    return check(getattr(resolved, name, None) == value for name, value in perms.items())


def server_admin():
    async def pred(ctx):
        if await guild_perm_check(ctx, {'administrator': True}):
            return True
        if await config_perm_check(ctx, 'admin'):
            return True
        return False

    return commands.check(pred)


def server_mod():
    async def pred(ctx):
        if await guild_perm_check(ctx, {'manage_guild': True}):
            return True
        if await config_perm_check(ctx, 'mod'):
            return True
        return False

    return commands.check(pred)
