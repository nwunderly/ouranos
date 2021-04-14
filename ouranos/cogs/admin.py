import logging

from ouranos.cog import Cog


logger = logging.getLogger(__name__)


class Admin(Cog):
    """Bot admin utilities."""
    def __init__(self, bot):
        self.bot = bot



def setup(bot):
    bot.add_cog(Admin(bot))
