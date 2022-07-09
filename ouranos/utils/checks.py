import disnake
from disnake.ext import commands

from ouranos.settings import Settings
from ouranos.utils import db


# checks that apply to every command invocation
async def global_checks(ctx):
    if await is_bot_admin(ctx.author):
        return True
    if not ctx.guild.me.guild_permissions.send_messages:
        return False
    if ctx.guild is None:
        return False
    if ctx.bot.blacklisted(ctx.author.id, ctx.guild.id, ctx.guild.owner.id):
        try:
            await ctx.send(
                "I won't respond to commands from blacklisted users or in blacklisted guilds!"
            )
        except disnake.Forbidden:
            pass
        return False
    return True


async def is_bot_admin(user):
    return user.id in Settings.admins


def bot_admin():
    async def pred(ctx):
        return await is_bot_admin(ctx.author)

    return commands.check(pred)


async def config_perm_check(member, permission):
    if await is_bot_admin(member):
        return True

    config = await db.get_config(member.guild)
    if config:
        role_id = {"admin": config.admin_role_id, "mod": config.mod_role_id}[permission]
        return member.guild.get_role(role_id) in member.roles
    return False


async def guild_perm_check(member, perms, *, check=all):
    if await is_bot_admin(member):
        return True

    resolved = member.guild_permissions
    return check(
        getattr(resolved, name, None) == value for name, value in perms.items()
    )


async def is_server_admin(member):
    return (
        await is_bot_admin(member)
        or await guild_perm_check(member, {"administrator": True})
        or await config_perm_check(member, "admin")
    )


async def is_server_mod(member):
    return (
        await is_server_admin(member)
        or await guild_perm_check(member, {"manage_guild": True})
        or await config_perm_check(member, "mod")
    )


def server_admin():
    async def pred(ctx):
        return await is_server_admin(ctx.author)

    return commands.check(pred)


def server_mod():
    async def pred(ctx):
        return await is_server_mod(ctx.author)

    return commands.check(pred)


def require_configured(option):
    async def pred(ctx):
        config = await db.get_config(ctx.guild)
        if config:
            return bool(config.__getattribute__(option))
        return False

    return commands.check(pred)
