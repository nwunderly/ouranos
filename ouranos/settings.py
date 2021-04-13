import discord


class Settings:
    version = '0.1.0'
    prefix = "?"

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
