class Stats:
    messages_seen = 0
    commands_used = 0
    logs_sent = 0
    guilds = set()

    @classmethod
    def on_message(cls):
        cls.messages_seen += 1

    @classmethod
    def on_command(cls):
        cls.commands_used += 1

    @classmethod
    def on_log(cls, guild):
        cls.logs_sent += 1
        cls.guilds.add(guild)

    @classmethod
    def show(cls):
        return f"Stats(messages_seen={cls.messages_seen}, commands_used={cls.commands_used}, logs_sent={cls.logs_sent})"

    @classmethod
    def unique_guilds(cls):
        return len(cls.guilds)
