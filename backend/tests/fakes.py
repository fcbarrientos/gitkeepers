"""Test doubles shared by the HTTP tests."""


class FakeLLM:
    """Stands in for the local model: returns a canned reply and records every prompt."""
    model_name = "fake-model"

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def chat_json(self, messages, schema, max_tokens=512):
        self.calls.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply(messages) if callable(self.reply) else self.reply
