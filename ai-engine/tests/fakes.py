"""Test double for LLMClient. Lets us exercise agent node logic (guardrails,
state wiring, conditional routing) deterministically, without a real API key.
Not used anywhere outside tests/.
"""
from __future__ import annotations

from collections import deque
from typing import Callable

from llm.client import LLMClient, LLMResponse, LLMUsage


class FakeLLMClient(LLMClient):
    def __init__(self, responses: list[str] | None = None, responder: Callable[[str, str], str] | None = None):
        self._queue = deque(responses or [])
        self._responder = responder
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.2) -> LLMResponse:
        self.calls.append((system_prompt, user_prompt))
        if self._responder:
            text = self._responder(system_prompt, user_prompt)
        elif self._queue:
            text = self._queue.popleft()
        else:
            raise AssertionError("FakeLLMClient ran out of queued responses")
        return LLMResponse(text=text, usage=LLMUsage(prompt_tokens=0, completion_tokens=0, model="fake"))
