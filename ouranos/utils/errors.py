from discord.ext import commands


class OuranosCommandError(commands.CommandError):
    def __init__(self, message):
        self._msg = message
        super().__init__(message)


class UnexpectedError(OuranosCommandError):
    pass


class NotConfigured(OuranosCommandError):
    def __init__(self, option):
        super().__init__(f"This guild is missing the **{option}** configuration option.")


class ModerationError(OuranosCommandError):
    pass


class UserNotInGuild(ModerationError):
    def __init__(self, user):
        super().__init__(f"User **{user}** is not in this guild.")


class BotMissingPermission(ModerationError):
    def __init__(self, permission):
        super().__init__(f"I could not perform that action because I'm missing the **{permission}** permission.")


class BotRoleHierarchyError(ModerationError):
    def __init__(self):
        super().__init__("I could not execute that action due to role hierarchy.")


class ModActionOnMod(ModerationError):
    def __init__(self):
        super().__init__("You cannot perform moderation actions on other server moderators!")


class ModlogError(OuranosCommandError):
    pass


class InfractionNotFound(ModlogError):
    def __init__(self, infraction_id):
        super().__init__(f"I couldn't find infraction #{infraction_id} for this guild.")


class ModlogMessageNotFound(ModlogError):
    def __init__(self, infraction_id, p='?'):
        super().__init__(f"I couldn't find a message for infraction #{infraction_id}. "
                         f"Try `{p}infraction info {infraction_id}` instead.")


class HistoryNotFound(ModlogError):
    def __init__(self, user=None):
        if user:
            msg = f"I couldn't find any past infractions for user {user}."
        else:
            msg = "That user has no past infractions."
        super().__init__(msg)
