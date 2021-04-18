from discord.ext import commands


class OuranosCommandError(commands.CommandError):
    def __init__(self, message):
        self._msg = message
        super().__init__(message)


class UnexpectedError(OuranosCommandError):
    pass


class ModerationError(OuranosCommandError):
    pass


class UserNotInGuild(ModerationError):
    def __init__(self, user):
        super().__init__(f"User **{user}** is not in this guild.")


class NotConfigured(ModerationError):
    def __init__(self, option):
        super().__init__(f"This guild is missing the **{option}** configuration option.")


class BotMissingPermission(ModerationError):
    def __init__(self, permission):
        super().__init__(f"I could not perform that action because I'm missing the **{permission}** permission.")


class BotRoleHierarchyError(ModerationError):
    def __init__(self):
        super().__init__("I could not execute that action due to role hierarchy.")


class ModActionOnMod(ModerationError):
    def __init__(self):
        super().__init__("You cannot perform moderation actions on other server moderators!")
