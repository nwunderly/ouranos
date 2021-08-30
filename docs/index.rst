Ouranos Documentation
=====================

.. toctree::
   :maxdepth: 2
   :caption: Contents:


Ouranos
-------

A simple, opinionated Discord moderation bot.


Features
--------

Ouranos has been developed with an intentionally minimalist approach to features:

- Simple setup and configuration.
- Basic mod utility commands.
- Pollr-inspired modlog, supports manual and command-based actions.


Why?
----

Like many other bots, this is a project I started due to my dissatisfaction with the available moderation bots on Discord.

- I don't like embeds.
- Massive bot configuration files when I don't use most of the features anyway.
- Most mod bots don't like manual actions, while audit-log-based mod bots like to treat reassigned mute roles as a new infraction.
- Editing mute/ban duration can be a pain in the ass with a lot of bots.
- Bots like to touch my channel perms. I don't like people messing with my channel perms.

Every server is run differently, and has different needs, so it makes sense that the current trend is highly configurable
bots with many features. However, from what I've seen, this can cause several problems. The bots can have stability issues,
the configuration can be extremely complicated. On top of this, often the moderation features themselves, such as infraction
tracking or even basic mod commands, don't behave the way I like. As such, I've chosen to take a different approach.

Ouranos is, as I like to put it, an opinionated bot. While it's configurable, the configuration is intentionally minimalist.
Its features are similarly limited: modlog, and the most basic moderation commands. That's it.
Instead of a highly configurable bot, I've chosen to provide a bot that, once set up, *just works*.
No bells and whistles, just the classic mod utilities and a clean, readable mod action log.


Adding the bot
--------------

The bot is currently private. Contact `nwunder#4003` on Discord if interested in using it.


Self-hosting
------------

I really wouldn't recommend self-hosting this bot in its current state. While one of my goals for this project is to make it 
easy for others to use, that's probably a ways off.
Currently, this repository is structured for the bot to be run easily with my personal system, so ease of use isn't yet 
factored into the framework.


Setup
-----

Once the bot has been added to your server, configuration is relatively quick and easy.

To initialize the server's config, use the `?init` command. The server's configuration should now be accessible through the `?config` command.
`?help config` gives a breakdown of the subcommands used to edit the server's configuration.

The server's modlog channel can be set using the `?config modlog-channel <channel>` command.

Little to no permission setup should be required. There are only two permission levels: mod and admin. Admins can edit the server's configuration, while 
mods have access to everything else (they have full access to moderation commands).
By default, server admins are anyone with the `Administrator` permission, while mods are anyone with the `Manage Server` permission.
A role can be set as moderator or administrator with the `?config mod-role <role>` command. Only one role can be set for each of these configuration options.


Using the bot
-------------

The bot's moderation features work exactly as you'd expect.
- `?warn <user> <reason>` - Warns a user. A reason is required for this command.
- `?mute <user> [duration] [reason]` - Mutes a user. Permanent if a duration is not specified.
- `?kick <user> [reason]` - Kicks a user from the server.
- `?ban <user> [duration] [reason]` - Bans a user. Permanent if a duration is not specified. Works with ID even if the user is not in the server.
- `?unmute <user> [reason]` - Unmutes a user. Manual unmutes like this are treated as a modlog event (expired mutes aren't).
- `?unban <user> [reason]` - Unbans a user. Manual unbans like this are treated as a modlog event (expired mutes aren't).

Some additional behavior worth noting:
- The mute/ban command, if the user is already muted/banned, will instead edit the duration of the infraction.
- Manually-assigned mute roles are treated as a permanent mute, and logged as if the user had used a command.
- Right-click kicks and bans are treated as a permanent ban, and logged as if a command had been used, including audit log reason.
- The `reason` argument in mod commands is parsed such that `--` is treated as a separator,
  with the remainder of the string logged as a mod note (and not included in the DM to the user).
  
For example, `?mute nwunder#4003 1h spamming -- spammed pictures of bulbasaur in #general` would (if dm-on-infraction is enabled in config) send a DM informing
me that I was muted for "spamming", while other server moderators reading the modlog would be able to see in the `Note` section that I was spamming pictures of
bulbasaur in general chat.


Credits
-------

In addition to Ouranos' modlog being heavily inspired by Pollr, a lot of ideas and code were drawn from
[RoboDanny](https://github.com/Rapptz/RoboDanny) by Danny#0007 and [GearBot](https://github.com/gearbot/GearBot) by AEnterprise#4693.
Particularly, the admin cog is built on top of Danny's code, and Ouranos' infraction database is heavily based on AEnterprise's design.


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
