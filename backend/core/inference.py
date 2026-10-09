"""Runtime-agnostic LLM interface, the rest of the app only uses this"""
from abc import ABC, abstractmethod
from typing import Iterator


class LLM(ABC):
    @abstractmethod
    def generate(self, prompt: str, max_tokens: int = 256) -> str: ...

    @abstractmethod
    def stream(self, prompt: str, max_tokens: int = 256) -> Iterator[str]: ...


class LlamaCppLLM(LLM):
    def __init__(self, model_path: str, n_ctx: int = 4096):
        from llama_cpp import Llama  # imported lazily so the rest runs without it
        self.llm = Llama(model_path=model_path, n_ctx=n_ctx, verbose=False)

    def generate(self, prompt, max_tokens=256):
        out = self.llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens)
        return out["choices"][0]["message"]["content"]

    def stream(self, prompt, max_tokens=256):
        for chunk in self.llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens, stream=True):
            piece = chunk["choices"][0]["delta"].get("content")
            if piece:
                yield piece


class MockLLM(LLM):
    """Lets the frontend team build against the API before any model exists."""
    def generate(self, prompt, max_tokens=256):
        return f"[mock reply] You said: {prompt}"

    def stream(self, prompt, max_tokens=256):
        yield from (w + " " for w in self.generate(prompt).split())
