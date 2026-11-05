"""Provider-configurable LLM client abstraction.

The five reasoning agents (Phases 5-9) all call through this one interface,
never a specific vendor SDK directly, so swapping providers is a config
change (PAYSHIFT_LLM_PROVIDER env var) rather than a code change. When no
provider is configured, NullLLMClient raises LLMNotConfiguredError loudly
instead of ever fabricating a plausible-looking response -- the project's
"do not invent results" rule applies to the agent layer too.
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Loaded once at import time so every entry point (CLI, Streamlit, pytest)
# picks up OPENAI_API_KEY / ANTHROPIC_API_KEY from the repo-root .env without
# each of them needing to remember to call load_dotenv() themselves.
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

logger = logging.getLogger("payshift.llm")


class LLMNotConfiguredError(RuntimeError):
    """Raised when an agent node needs a real LLM call but none is configured."""


@dataclass
class LLMUsage:
    prompt_tokens: int
    completion_tokens: int
    model: str


@dataclass
class LLMResponse:
    text: str
    usage: LLMUsage


class LLMClient(ABC):
    """Minimal interface every provider adapter implements."""

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.2) -> LLMResponse:
        ...

    def complete_json(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.1) -> dict:
        """Asks for a JSON object and parses it. Raises ValueError if the model's
        output isn't valid JSON -- callers must not silently fall back to guessing."""
        json_instruction = (
            "\n\nRespond with ONLY a single valid JSON object. No prose, no markdown "
            "code fences, no explanation before or after the JSON."
        )
        response = self.complete(system_prompt, user_prompt + json_instruction, temperature=temperature)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM did not return valid JSON: {e}\nRaw output: {text[:500]}") from e


class NullLLMClient(LLMClient):
    def complete(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.2) -> LLMResponse:
        raise LLMNotConfiguredError(
            "No LLM provider is configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY "
            "(and optionally PAYSHIFT_LLM_PROVIDER=openai|anthropic) in the environment "
            "or .env file before running any step that requires real reasoning."
        )


class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def complete(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.2) -> LLMResponse:
        completion = self._client.chat.completions.create(
            model=self._model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        choice = completion.choices[0].message.content or ""
        usage = completion.usage
        return LLMResponse(
            text=choice,
            usage=LLMUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                model=self._model,
            ),
        )


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, model: str = "claude-sonnet-5-5"):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.2) -> LLMResponse:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(block.text for block in message.content if hasattr(block, "text"))
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=message.usage.input_tokens,
                completion_tokens=message.usage.output_tokens,
                model=self._model,
            ),
        )


def get_llm_client() -> LLMClient:
    provider = os.environ.get("PAYSHIFT_LLM_PROVIDER", "").lower()

    if provider == "openai" or (not provider and os.environ.get("OPENAI_API_KEY")):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise LLMNotConfiguredError("PAYSHIFT_LLM_PROVIDER=openai but OPENAI_API_KEY is not set.")
        model = os.environ.get("PAYSHIFT_LLM_MODEL", "gpt-4o-mini")
        logger.info("Using OpenAI LLM client (model=%s)", model)
        return OpenAIClient(api_key=api_key, model=model)

    if provider == "anthropic" or (not provider and os.environ.get("ANTHROPIC_API_KEY")):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMNotConfiguredError("PAYSHIFT_LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set.")
        model = os.environ.get("PAYSHIFT_LLM_MODEL", "claude-sonnet-5-5")
        logger.info("Using Anthropic LLM client (model=%s)", model)
        return AnthropicClient(api_key=api_key, model=model)

    logger.warning("No LLM provider configured; reasoning steps will raise LLMNotConfiguredError when invoked.")
    return NullLLMClient()
