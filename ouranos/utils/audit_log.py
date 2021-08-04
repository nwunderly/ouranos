import discord

from discord.ext import commands

from ouranos.bot import Ouranos


class AuditLogFetcher:
    """Manages linear audit log requests for concurrent events."""
    def __init__(self):
        self.loops = []


