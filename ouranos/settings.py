import discord


class Settings:
    version = '0.1.0'
    prefix = "?"
    description = 'Ouranos by nwunder#4003'

    embed_color = discord.Color(0x7289da)

    logging_channel = 0000000000000000
    invite_permissions = 2110258423

    cogs = [
        'jishaku',
    ]

    bot_perms = {
        'options': [
            'admin',      # all
            'root',       # eval, shell
            'manager',    # manage this bot (everything but eval/shell, permissions)
            'config',     # global config access
            'moderator',  # global server_admin permissions
        ],
        204414611578028034: [  # nwunder
            'admin'
        ]
    }

    activities = [
        f'playing version {version}!',
    ]

    intents = {
        'guilds': True,
        'members': True,
        'bans': True,
        'emojis': True,
        'integrations': False,
        'webhooks': False,
        'invites': False,
        'voice_states': False,
        'presences': False,
        'guild_messages': True,
        'dm_messages': False,
        'guild_reactions': False,
        'dm_reactions': False,
        'guild_typing': False,
        'dm_typing': False
    }
