class Stats:
    messages_seen = 0
    commands_used = 0
    logs_sent = 0

    @classmethod
    def on_message(cls):
        cls.messages_seen += 1

    @classmethod
    def on_command(cls):
        cls.commands_used += 1

    @classmethod
    def on_log(cls):
        cls.logs_sent += 1

    @classmethod
    def show(cls):
        return f"Stats(messages_seen={cls.messages_seen}, commands_used={cls.commands_used}, logs_sent={cls.logs_sent})"
