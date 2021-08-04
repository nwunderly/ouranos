import discord


class Settings:
    version = '1.6.1'
    prefix = "?"
    description = 'A simple and opinionated Discord moderation bot.'
    author = "nwunder#4003"

    embed_color = discord.Color(0x7289da)

    invite_permissions = 2110258423

    bot_id = 831312219517091871
    guild_id = 537043976562409482
    owner_id = 204414611578028034

    bot_av_url = 'https://cdn.discordapp.com/avatars/831312219517091871/524266a03aeb95ae122b4d1d2054fc17.webp'
    invite_url = 'https://discord.com/oauth2/authorize?client_id=831312219517091871&scope=bot+applications.commands&permissions=2110258423'
    support_url = 'https://discord.gg/d25W5PS'
    repo_url = 'https://github.com/nwunderly/ouranos'

    cogs = [
        'jishaku',
        'ouranos.cogs.admin',
        'ouranos.cogs.config',
        'ouranos.cogs.general',
        'ouranos.cogs.logging',
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
        'watching you',
        'listening to nwunder scream'
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
