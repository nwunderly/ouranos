import io
import discord
import asyncio
import subprocess
import traceback
import textwrap
import contextlib
import inspect

from discord.ext import commands
from contextlib import redirect_stdout
from loguru import logger

from ouranos.cog import Cog
from ouranos.utils import database as db
from ouranos.utils import modlog_utils as modlog
from ouranos.utils.checks import bot_admin
from ouranos.utils.converters import A_OR_B, Guild
from ouranos.utils.constants import OK_HAND
from ouranos.utils.errors import InfractionNotFound


class AddOrRemove(A_OR_B):
    OPTION_A = 'add'
    OPTION_B = 'remove'


class ActiveOrInactive(A_OR_B):
    OPTION_A = 'active'
    OPTION_B = 'inactive'


class Admin(Cog):
    """Bot admin utilities."""
    def __init__(self, bot):
        self.bot = bot
        self._last_result = None
        self.sessions = set()

    @commands.group(name='db', invoke_without_command=True)
    @bot_admin()
    async def _db(self, ctx):
        """Database admin actions."""
        await ctx.send_help(self._db)

    @_db.command(aliases=['clear-config'])
    @bot_admin()
    async def clear_config(self, ctx, guild_id: int):
        """Remove a guild's configuration from the database."""
        try:
            result = await db.Config.filter(guild_id=guild_id).delete()
        except Exception as e:
            result = f"{e.__class__.__name__}: {e}"
        db.config_cache.pop(guild_id)
        await ctx.send(f"```py\n{result}\n```")

    @_db.command(aliases=['clear-modlog'])
    @bot_admin()
    async def clear_modlog(self, ctx, guild_id: int):
        """Completely remove a guild's modlog data from the database."""
        # remove infractions
        try:
            result_1 = await db.Infraction.filter(guild_id=guild_id).delete()
        except Exception as e:
            result_1 = f"{e.__class__.__name__}: {e}"

        # remove user history
        try:
            result_2 = await db.History.filter(guild_id=guild_id).delete()
        except Exception as e:
            result_2 = f"{e.__class__.__name__}: {e}"

        try:
            misc = await db.MiscData.get_or_none(guild_id=guild_id)
            if misc:
                if guild_id in modlog.last_case_id_cache:
                    modlog.last_case_id_cache.pop(guild_id)
                misc.last_case_id = 0
                await misc.save()
                result_3 = True
            else:
                result_3 = False
        except Exception as e:
            result_3 = f"{e.__class__.__name__}: {e}"

        await ctx.send(
            f"Infractions:```py\n{result_1}\n```\n"
            f"History:```py\n{result_2}\n```\n"
            f"Misc (last_case_id):```py\n{result_3}\n```\n"
        )

    # @_db.command(aliases=['force-infraction-state'])
    # @bot_admin()
    # async def force_infraction_state(self, ctx, guild_id: int, infraction_id: int, active_or_inactive: ActiveOrInactive):
    #     """Force mark an infraction as either active or inactive in the database."""
    #     infraction = await modlog.get_infraction(guild_id, infraction_id)
    #     if not infraction:
    #         raise InfractionNotFound(infraction_id)
    #     await db.edit_record(infraction, active=active_or_inactive)
    #     modlog.infraction_cache[]
    #     await ctx.send(OK_HAND)

    @commands.command()
    @bot_admin()
    async def blacklist(self, ctx, add_or_remove: AddOrRemove = None, id: int = 0):
        """Add or remove a user or guild id from the bot's blacklist."""
        # view
        if add_or_remove is None or not id:
            return await ctx.send(f"```py\n{self.bot._blacklist}\n```")

        # add
        elif add_or_remove is True:
            if id not in self.bot._blacklist:
                self.bot._blacklist.add(id)
            else:
                return await ctx.send("That id is already blacklisted!")
        # remove
        else:
            if id in self.bot._blacklist:
                self.bot._blacklist.remove(id)
            else:
                return await ctx.send("That id is not blacklisted!")

        # confirm
        self.bot.dump_blacklist()
        await ctx.send("Done!")

    @commands.command()
    @bot_admin()
    async def load(self, ctx, cog):
        try:
            self.bot.load_extension(f"ouranos.cogs.{cog}")
            await ctx.send(f"Loaded {cog}!")
        except Exception as e:
            await ctx.send(f"```py\n{e.__class__.__name__}: {e}\n```")

    @commands.command()
    @bot_admin()
    async def unload(self, ctx, cog):
        try:
            self.bot.unload_extension(f"ouranos.cogs.{cog}")
            await ctx.send(f"Unloaded {cog}!")
        except Exception as e:
            await ctx.send(f"```py\n{e.__class__.__name__}: {e}\n```")

    @commands.command()
    @bot_admin()
    async def reload(self, ctx, cog):
        try:
            self.bot.reload_extension(f"ouranos.cogs.{cog}")
            await ctx.send(f"Reloaded {cog}!")
        except Exception as e:
            await ctx.send(f"```py\n{e.__class__.__name__}: {e}\n```")

    @staticmethod
    def cleanup_code(content):
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith('```') and content.endswith('```'):
            return '\n'.join(content.split('\n')[1:-1])

        # remove `foo`
        return content.strip('` \n')

    async def run_process(self, command):
        try:
            process = await asyncio.create_subprocess_shell(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = await process.communicate()
        except NotImplementedError:
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = await self.bot.loop.run_in_executor(None, process.communicate)

        return [output.decode() for output in result]

    def get_syntax_error(self, e):
        if e.text is None:
            return f'```py\n{e.__class__.__name__}: {e}\n```'
        return f'```py\n{e.text}{"^":>{e.offset}}\n{e.__class__.__name__}: {e}```'

    @commands.command(name='eval', aliases=['e'])
    @bot_admin()
    async def _eval(self, ctx, *, body: str):
        """Runs arbitrary python code"""

        env = {
            'bot': self.bot,
            'ctx': ctx,
            'channel': ctx.channel,
            'author': ctx.author,
            'guild': ctx.guild,
            'message': ctx.message,
            '_ret': self._last_result
        }

        env.update(globals())

        body = self.cleanup_code(body)
        stdout = io.StringIO()

        to_compile = f'async def func():\n{textwrap.indent(body, "  ")}'

        try:
            exec(to_compile, env)
        except Exception as e:
            return await ctx.send(f'```py\n{e.__class__.__name__}: {e}\n```')

        func = env['func']
        try:
            with contextlib.redirect_stdout(stdout):
                ret = await func()
        except Exception as e:
            value = stdout.getvalue()
            await ctx.send(f'```py\n{value}{traceback.format_exc()}\n```')
        else:
            value = stdout.getvalue()
            # try:
            #     await ctx.message.add_reaction('😎')
            # except:
            #     pass

            if ret is None:
                if value:
                    await ctx.send(f'```py\n{value}\n```')
            else:
                self._last_result = ret
                await ctx.send(f'```py\n{value}{ret}\n```')

    @commands.command()
    @bot_admin()
    async def repl(self, ctx):
        """Launches an interactive REPL session."""
        variables = {
            'ctx': ctx,
            'bot': self.bot,
            'message': ctx.message,
            'guild': ctx.guild,
            'channel': ctx.channel,
            'author': ctx.author,
            '_': None,
        }

        if ctx.channel.id in self.sessions:
            await ctx.send('Already running a REPL session in this channel. Exit it with `quit`.')
            return

        self.sessions.add(ctx.channel.id)
        await ctx.send('Enter code to execute or evaluate. `exit()` or `quit` to exit.')

        def check(m):
            return m.author.id == ctx.author.id and \
                   m.channel.id == ctx.channel.id and \
                   m.content.startswith('`')

        while True:
            try:
                response = await self.bot.wait_for('message', check=check, timeout=10.0 * 60.0)
            except asyncio.TimeoutError:
                await ctx.send('Exiting REPL session.')
                self.sessions.remove(ctx.channel.id)
                break

            cleaned = self.cleanup_code(response.content)

            if cleaned in ('quit', 'exit', 'exit()'):
                await ctx.send('Exiting.')
                self.sessions.remove(ctx.channel.id)
                return

            executor = exec
            if cleaned.count('\n') == 0:
                # single statement, potentially 'eval'
                try:
                    code = compile(cleaned, '<repl session>', 'eval')
                except SyntaxError:
                    pass
                else:
                    executor = eval

            if executor is exec:
                try:
                    code = compile(cleaned, '<repl session>', 'exec')
                except SyntaxError as e:
                    await ctx.send(self.get_syntax_error(e))
                    continue

            variables['message'] = response

            fmt = None
            stdout = io.StringIO()

            try:
                with redirect_stdout(stdout):
                    result = executor(code, variables)
                    if inspect.isawaitable(result):
                        result = await result
            except Exception as e:
                value = stdout.getvalue()
                fmt = f'```py\n{value}{traceback.format_exc()}\n```'
            else:
                value = stdout.getvalue()
                if result is not None:
                    fmt = f'```py\n{value}{result}\n```'
                    variables['_'] = result
                elif value:
                    fmt = f'```py\n{value}\n```'

            try:
                if fmt is not None:
                    if len(fmt) > 2000:
                        await ctx.send('Content too big to be printed.')
                    else:
                        await ctx.send(fmt)
            except discord.Forbidden:
                pass
            except discord.HTTPException as e:
                await ctx.send(f'Unexpected error: `{e}`')


def setup(bot):
    bot.add_cog(Admin(bot))
