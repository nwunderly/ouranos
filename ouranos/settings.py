import discord


class Settings:
    version = '1.1.1'
    prefix = "?"
    description = 'A simple and opinionated Discord mod bot.'
    author = "nwunder#4003"

    embed_color = discord.Color(0x7289da)

    logging_channel = 0000000000000000
    invite_permissions = 2110258423

    invite_url = 'https://discord.com/oauth2/authorize?client_id=831312219517091871&scope=bot+applications.commands&permissions=2110258423'
    support_url = 'https://discord.gg/d25W5PS'
    repo_url = 'https://github.com/nwunderly/ouranos'

    cogs = [
        'jishaku',
        'ouranos.cogs.admin',
        'ouranos.cogs.config',
        'ouranos.cogs.general',
        'ouranos.cogs.moderation',
        'ouranos.cogs.modlog',
    ]

    admins = [
        204414611578028034,  # nwunder
    ]

    activities = [
        'playing version {version}',
        'watching {random_guild_name}',
        'watching {user_count} users',
        'watching {guild_count} guilds',
    ]

    intents = discord.Intents(
        guilds=True,
        members=True,
        bans=True,
        emojis=True,
        integrations=False,
        webhooks=False,
        invites=False,
        voice_states=False,
        presences=False,
        guild_messages=True,
        dm_messages=False,
        guild_reactions=False,
        dm_reactions=False,
        guild_typing=False,
        dm_typing=False
    )

    allowed_mentions = discord.AllowedMentions(
        everyone=False,
        users=True,
        roles=False,
        replied_user=True
    )
