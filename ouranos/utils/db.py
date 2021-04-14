import json
import logging

from typing import List, Union, Type, Optional, Any
from tortoise import fields, Tortoise
from tortoise.models import Model

from ouranos.settings import Settings


logger = logging.getLogger(__name__)


class Config(Model):
    guild_id = fields.BigIntField(pk=True, generated=False)
    prefix = fields.TextField(default=Settings.prefix)
    modlog_channel_id = fields.BigIntField(default=0)
    mute_role_id = fields.BigIntField(default=0)
    admin_role_id = fields.BigIntField(default=0)
    mod_role_id = fields.BigIntField(default=0)
    dm_on_infraction = fields.BooleanField(default=True)

    
config_cache = {}


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


class Infraction(Model):
    id = fields.IntField(pk=True, generated=True)
    guild_id = fields.BigIntField()
    infraction_id = fields.IntField()
    user_id = fields.BigIntField()
    mod_id = fields.BigIntField()
    message_id = fields.BigIntField(default=0)
    type = fields.TextField()
    reason = fields.TextField(null=True)
    note = fields.TextField(null=True)
    created_at = fields.DatetimeField()
    ends_at = fields.DatetimeField(null=True)
    active = fields.BooleanField(default=True)

    class Meta:
        unique_together = ("guild_id", "infraction_id")


class MiscData(Model):
    guild_id = fields.BigIntField(pk=True, generated=False)
    last_case_id = fields.IntField(default=0)


class IntArrayField(fields.Field, list):
    SQL_TYPE = "int[]"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_db_value(self, value: List[int], instance: "Union[Type[Model], Model]") -> Optional[List[int]]:
        return value

    def to_python_value(self, value: Any) -> Optional[List[int]]:
        if isinstance(value, str):
            array = json.loads(value.replace("'", '"'))
            return [int(x) for x in array]
        return value


class History(Model):
    id = fields.IntField(pk=True, generated=True)
    guild_id = fields.BigIntField()
    user_id = fields.BigIntField()
    warns = IntArrayField()
    mutes = IntArrayField()
    unmutes = IntArrayField()
    kicks = IntArrayField()
    bans = IntArrayField()
    unbans = IntArrayField()

    class Meta:
        unique_together = ("guild_id", "user_id")


async def init(db_url):
    logger.info("Connecting to database.")
    await Tortoise.init(
        db_url=db_url,
        modules={'models': ['ouranos.utils.db']}
    )
    await Tortoise.generate_schemas()
