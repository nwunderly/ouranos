import json

from typing import List, Union, Type, Optional, Any
from tortoise import fields, Tortoise
from tortoise.models import Model
from loguru import logger

from ouranos.settings import Settings


# infraction database schema heavily inspired by GearBot: https://github.com/gearbot/GearBot


config_cache = {}  # {guild_id: Config}
infraction_cache = {}  # {(guild_id, infraction_id): Infraction}
history_cache = {}  # {(guild_id, user_id): History}
last_case_id_cache = {}  # {guild_id: MiscData}
active_infraction_exists_cache = {}  # {(guild_id, user_id): bool}


async def edit_record(record, **kwargs):
    for key, value in kwargs.items():
        record.__setattr__(key, value)
    await record.save()
    if isinstance(record, Config):
        config_cache[record.guild_id] = record
    elif isinstance(record, Infraction):
        infraction_cache[record.guild_id, record.infraction_id] = record
    elif isinstance(record, History):
        history_cache[record.guild_id, record.user_id] = record
    elif isinstance(record, MiscData):
        last_case_id_cache[record.guild_id] = record
    return record


# TODO: optimize this
async def edit_records_bulk(records, **kwargs):
    ret = []
    for record in records:
        ret.append(await edit_record(record, **kwargs))
    return ret


class Config(Model):
    guild_id = fields.BigIntField(pk=True, generated=False)
    prefix = fields.TextField(default=Settings.prefix)
    modlog_channel_id = fields.BigIntField(default=0)
    mute_role_id = fields.BigIntField(default=0)
    admin_role_id = fields.BigIntField(default=0)
    mod_role_id = fields.BigIntField(default=0)
    dm_on_infraction = fields.BooleanField(default=True)


async def get_config(guild):
    if guild.id not in config_cache:
        config = await Config.get_or_none(guild_id=guild.id)
        config_cache[guild.id] = config
        return config
    return config_cache[guild.id]


async def create_config(guild):
    if config_cache.get(guild.id) or await Config.exists(guild_id=guild.id):
        return False
    config = await Config.create(guild_id=guild.id)
    config_cache[guild.id] = config
    return True


async def update_config(*, guild=None, config=None, **kwargs):
    if guild:
        config = await get_config(guild)
        guild_id = guild.id
    else:
        guild_id = config.guild_id
    for key, value in kwargs.items():
        config.__setattr__(key, value)
    await config.save()
    config_cache[guild_id] = config
    return config


class IntArrayField(fields.Field, list):
    SQL_TYPE = "int[]"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_db_value(self, value: List[int], instance: Union[Type[Model], Model]) -> Optional[List[int]]:
        return value

    def to_python_value(self, value: Any) -> Optional[List[int]]:
        if isinstance(value, str):
            array = json.loads(value.replace("'", '"'))
            return [int(x) for x in array]
        return value


class Infraction(Model):
    global_id = fields.IntField(pk=True, generated=True)
    guild_id = fields.BigIntField()
    infraction_id = fields.IntField()
    user_id = fields.BigIntField()
    mod_id = fields.BigIntField()
    message_id = fields.BigIntField(default=0)
    type = fields.TextField()
    reason = fields.TextField(null=True)
    note = fields.TextField(null=True)
    created_at = fields.BigIntField()
    ends_at = fields.BigIntField(null=True)
    active = fields.BooleanField()
    bulk_infraction_id_range = IntArrayField(null=True)  # added 5/14/21

    class Meta:
        unique_together = ("guild_id", "infraction_id")


class MiscData(Model):
    guild_id = fields.BigIntField(pk=True, generated=False)
    last_case_id = fields.IntField(default=0)


class History(Model):
    global_id = fields.IntField(pk=True, generated=True)
    guild_id = fields.BigIntField()
    user_id = fields.BigIntField()
    warn = IntArrayField()
    mute = IntArrayField()
    unmute = IntArrayField()
    kick = IntArrayField()
    ban = IntArrayField()
    unban = IntArrayField()
    active = IntArrayField()

    class Meta:
        unique_together = ("guild_id", "user_id")


async def init(db_url):
    logger.info("Connecting to database.")
    await Tortoise.init(
        db_url=db_url,
        modules={'models': ['ouranos.utils.database']}
    )
    await Tortoise.generate_schemas()
