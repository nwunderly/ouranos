import csv

import disnake
from disnake.ext import commands

from auth import DB_URL_PROD, TOKEN_PROD
from ouranos.utils import db, modlog

bot = commands.Bot(command_prefix="===", intents=disnake.Intents.all())
bot.RUNNING = False
bot.GUILD = None
bot.ROLE = None
bot.BANS = None
infractions = []


GUILD = 00000000000000000
MUTED_ROLE = 00000000000000000
MODS = []


class Infraction:
    def __init__(self, aperture_infraction_id, user_id, mod_id, type, reason):
        self.aperture_infraction_id = aperture_infraction_id
        self.user_id = user_id
        self.mod_id = mod_id
        self.type = type
        self.reason = reason


@bot.event
async def on_ready():
    if not bot.RUNNING:
        print(f"Logged in as {bot.user}.")
        bot.RUNNING = True
        bot.GUILD = bot.get_guild(GUILD)
        bot.ROLE = bot.GUILD.get_role(MUTED_ROLE)
        bot.BANS = await bot.GUILD.bans()
        await main()


@bot.command()
async def test(ctx):
    await ctx.send("ONLINE.")


async def load_from_aperture():
    print("===== BEGINNING LOAD PHASE =====")

    print("Loading from aperture infractions.csv.")
    with open("../data/infractions.csv", errors="ignore") as fp:
        lines = fp.readlines()

    guild = bot.get_guild(GUILD)
    aperture = guild.get_member(330770985450078208)

    for line in csv.reader(lines):
        (
            infraction_id,
            user_id,
            user_username,
            mod_id,
            mod_username,
            infraction_type,
            reason,
        ) = line
        infraction_id = int(infraction_id)
        user_id = int(user_id)
        mod_id = int(mod_id)
        reason = reason.strip('"')

        mod = guild.get_member(mod_id) if mod_id != user_id else aperture

        if (
            (user_id in MODS)
            or (not mod)
            or (user_username.lower().startswith("deleted user"))
            or (infraction_type not in ["warning", "mute", "tempmute", "ban"])
        ):
            continue
        print(
            f"Processing infraction {infraction_id} for {user_id=} {infraction_type=}"
        )
        infraction_type = {"warning": "warn", "tempmute": "mute"}.get(
            infraction_type
        ) or infraction_type
        infractions.append(
            Infraction(infraction_id, user_id, mod_id, infraction_type, reason)
        )


async def dump_to_ouranos():
    print("===== BEGINNING DUMP PHASE =====")

    print(f"Sorting {len(infractions)} infractions")
    infractions_sorted = sorted(infractions, key=lambda _i: _i.aperture_infraction_id)

    print("Dumping to db.")
    for infraction in infractions_sorted:
        i = await modlog.new_infraction(
            GUILD,
            infraction.user_id,
            infraction.mod_id,
            infraction.type,
            infraction.reason,
            None,
            None,
            False,
        )
        print(f"#{i.infraction_id} created for {i.user_id=} {i.type=}")


async def main():
    await db.init(DB_URL_PROD)
    print("Connected to ouranos db.")

    print("===== BEGINNING MIGRATION =====")
    await load_from_aperture()
    await dump_to_ouranos()
    print("===== MIGRATION COMPLETE =====")
    await bot.close()


if __name__ == "__main__":
    bot.run(TOKEN_PROD)
