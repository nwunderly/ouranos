import itertools
from discord.ext import commands as _commands


_command_init_order = ['help']


def _on_command_init(cmd):
    if cmd.qualified_name not in _command_init_order:
        _command_init_order.append(cmd.qualified_name)


def _sort_key(cmd):
    if cmd.qualified_name in _command_init_order:
        return _command_init_order.index(cmd.qualified_name)
    else:
        return 0


class HelpCommand(_commands.MinimalHelpCommand):
    def filter_commands(self, _commands, *, sort=False, key=None):
        for cmd in list(_commands):
            if cmd.name == '--help':
                _commands.remove(cmd)

        return super().filter_commands(_commands, sort=sort, key=key)

    async def send_bot_help(self, mapping):
        ctx = self.context
        bot = ctx.bot

        if bot.description:
            self.paginator.add_line(bot.description, empty=True)

        note = self.get_opening_note()
        if note:
            self.paginator.add_line(note, empty=True)

        no_category = '\u200b{0.no_category}'.format(self)

        def get_category(command, *, no_category=no_category):
            cog = command.cog
            return cog.qualified_name if cog is not None else no_category

        filtered = await self.filter_commands(bot.commands, sort=True, key=get_category)
        to_iterate = itertools.groupby(filtered, key=get_category)

        for category, commands in to_iterate:
            commands = sorted(commands, key=_sort_key) if self.sort_commands else list(commands)
            self.add_bot_commands_formatting(commands, category)

        note = self.get_ending_note()
        if note:
            self.paginator.add_line()
            self.paginator.add_line(note)

        await self.send_pages()


class Command(_commands.Group):
    """discord.py command subclass. Adds a '--help' subcommand to all commands."""
    def __init__(self, *args, add_help=False, **kwargs):
        super().__init__(*args, **kwargs)
        if add_help:
            self._try_add_help()
            self.__original_kwargs__['add_help'] = False
        _on_command_init(self)

    def _try_add_help(self):
        try:
            async def _help_subcommand(ctx):
                await ctx.send_help(ctx.command.parent)

            cmd = _commands.Command(
                _help_subcommand,
                name='--help', aliases=['-h'],
                help=f"Get help for the `{self.qualified_name}` command."
            )
            self.add_command(cmd)

        except _commands.CommandRegistrationError:
            pass

    def command(self, *args, **kwargs):
        kwargs.setdefault('cls', Command)
        kwargs.setdefault('invoke_without_command', True)
        kwargs.setdefault('add_help', True)
        return super().command(*args, **kwargs)

    def group(self, *args, **kwargs):
        return self.command(*args, **kwargs)


def command(name=None, **attrs):
    attrs.setdefault('cls', Command)
    attrs.setdefault('invoke_without_command', True)
    attrs.setdefault('add_help', True)
    return _commands.command(name, **attrs)


def group(*args, **kwargs):
    return command(*args, **kwargs)
