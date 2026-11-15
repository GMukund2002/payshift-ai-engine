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
    truncated: bool = False  # the provider stopped because it hit the output-token limit


@dataclass
class LLMCallRecord:
    step: str
    model: str
    prompt_tokens: int
    completion_tokens: int


class LLMClient(ABC):
    """Minimal interface every provider adapter implements.

    A client instance also keeps a per-instance log of every call it made
    (`usage_records`), so whoever runs one pipeline with one client can report
    real token usage for that run. Entry points create one client per run.
    """

    def __init__(self) -> None:
        self.usage_records: list[LLMCallRecord] = []

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.2,
                 json_mode: bool = False) -> LLMResponse:
        ...

    def complete_json(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.1,
                      step: str = "unspecified") -> dict:
        """Asks for a JSON object and parses it. Raises ValueError if the model's
        output isn't a valid JSON object -- callers must not silently fall back to
        guessing."""
        json_instruction = (
            "\n\nRespond with ONLY a single valid JSON object. No prose, no markdown "
            "code fences, no explanation before or after the JSON."
        )
        response = self.complete(system_prompt, user_prompt + json_instruction,
                                 temperature=temperature, json_mode=True)
        self._record(step, response.usage)
        if response.truncated:
            raise ValueError(
                f"LLM output was cut off at the output-token limit ({response.usage.completion_tokens} tokens) "
                f"during '{step}'; the JSON is incomplete."
            )
        return parse_json_object(response.text)

    def _record(self, step: str, usage: LLMUsage) -> None:
        if not hasattr(self, "usage_records"):  # subclass that skipped super().__init__()
            self.usage_records = []
        self.usage_records.append(LLMCallRecord(
            step=step, model=usage.model,
            prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens,
        ))

    def usage_summary(self) -> dict:
        records = getattr(self, "usage_records", [])
        by_step: dict[str, dict] = {}
        for r in records:
            s = by_step.setdefault(r.step, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
            s["calls"] += 1
            s["prompt_tokens"] += r.prompt_tokens
            s["completion_tokens"] += r.completion_tokens
        return {
            "calls": len(records),
            "prompt_tokens": sum(r.prompt_tokens for r in records),
            "completion_tokens": sum(r.completion_tokens for r in records),
            "models": sorted({r.model for r in records}),
            "by_step": by_step,
        }


def parse_json_object(raw_text: str) -> dict:
    """Parses a model response that should be one JSON object. Tolerates a
    markdown code fence or stray prose around the object (some models add it
    even when told not to); anything that still isn't a JSON object raises."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        value = json.loads(text)
    except json.JSONDecodeError as first_error:
        start = text.find("{")
        if start == -1:
            raise ValueError(f"LLM did not return valid JSON: {first_error}\nRaw output: {raw_text[:500]}") from first_error
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM did not return valid JSON: {e}\nRaw output: {raw_text[:500]}") from e
    if not isinstance(value, dict):
        raise ValueError(f"LLM returned JSON but not an object (got {type(value).__name__})")
    return value


class NullLLMClient(LLMClient):
    def complete(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.2,
                 json_mode: bool = False) -> LLMResponse:
        raise LLMNotConfiguredError(
            "No LLM provider is configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY "
            "(and optionally PAYSHIFT_LLM_PROVIDER=openai|anthropic) in the environment "
            "or .env file before running any step that requires real reasoning."
        )


class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        super().__init__()
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def complete(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.2,
                 json_mode: bool = False) -> LLMResponse:
        kwargs = {}
        if json_mode:
            # Constrains the model to emit a syntactically valid JSON object.
            kwargs["response_format"] = {"type": "json_object"}
        completion = self._client.chat.completions.create(
            model=self._model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **kwargs,
        )
        choice = completion.choices[0]
        usage = completion.usage
        return LLMResponse(
            text=choice.message.content or "",
            usage=LLMUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                model=self._model,
            ),
            truncated=choice.finish_reason == "length",
        )


class AnthropicClient(LLMClient):
    # Large enough for a complete multi-hundred-line Java file inside a JSON
    # envelope; 4096 truncated real generations mid-file.
    MAX_OUTPUT_TOKENS = 8192

    def __init__(self, api_key: str, model: str = "claude-sonnet-5-5"):
        super().__init__()
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.2,
                 json_mode: bool = False) -> LLMResponse:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=self.MAX_OUTPUT_TOKENS,
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
            truncated=message.stop_reason == "max_tokens",
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
