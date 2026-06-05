"""Single helper for structured-output LLM calls (with retry + circuit breaker)."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from .config import SETTINGS
from .schemas import CostLedger

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

try:  # ChatOpenAI is required at runtime but optional at import time for tests.
    from langchain_openai import ChatOpenAI  # type: ignore
except Exception:  # pragma: no cover
    ChatOpenAI = None  # type: ignore[assignment]


_PROMPTS_DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


class LLMBudgetExceeded(RuntimeError):
    """Raised when the per-run LLM call cap is hit."""


_call_counter = {"value": 0}


def reset_llm_counter() -> None:
    _call_counter["value"] = 0


def llm_calls_made() -> int:
    return _call_counter["value"]


def _is_reasoning_family(model: str) -> bool:
    name = (model or "").lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


def _make_chat(model: str, effort: str | None = None) -> Any:
    if ChatOpenAI is None:
        raise RuntimeError("langchain-openai is not installed.")
    if not SETTINGS.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": SETTINGS.openai_api_key,
    }
    if _is_reasoning_family(model):
        # gpt-5 family ignores `temperature` and uses `reasoning_effort` instead.
        # langchain-openai exposes this via the model_kwargs / reasoning_effort param.
        kwargs["reasoning_effort"] = effort or SETTINGS.reasoning_effort
    else:
        kwargs["temperature"] = 0
    return ChatOpenAI(**kwargs)


@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    retry=retry_if_exception_type(ValidationError),
    reraise=True,
)
def _invoke_structured(chat: Any, schema: Type[T], prompt: str) -> T:
    bound = chat.with_structured_output(schema)
    suffix = (
        "\n\nRespond ONLY with valid JSON that strictly matches the provided "
        "schema. Do not include any commentary, markdown, or code fences."
    )
    return bound.invoke(prompt + suffix)


def call_structured(
    schema: Type[T],
    prompt: str,
    *,
    model: str | None = None,
    effort: str | None = None,
) -> tuple[T, CostLedger]:
    """Call an OpenAI chat model and parse its output into `schema`.

    Returns (model_instance, cost). On unrecoverable failure, returns a
    default-constructed schema instance with whatever fields are required.
    """
    if _call_counter["value"] >= SETTINGS.max_llm_calls:
        log.warning("LLM call budget reached (%d); returning empty result.", SETTINGS.max_llm_calls)
        # Best-effort: return a default-constructed instance (works when all fields optional).
        try:
            return schema(), CostLedger()
        except ValidationError:
            raise LLMBudgetExceeded(
                f"LLM budget exhausted and {schema.__name__} requires fields with no defaults."
            )

    _call_counter["value"] += 1
    chosen_model = model or SETTINGS.model_reasoning
    # Default effort: reasoning-tier for the reasoning model, low for the extraction model.
    if effort is None:
        if chosen_model == SETTINGS.model_extract and chosen_model != SETTINGS.model_reasoning:
            effort = SETTINGS.extract_effort
        else:
            effort = SETTINGS.reasoning_effort
    chat = _make_chat(chosen_model, effort=effort)
    try:
        result = _invoke_structured(chat, schema, prompt)
    except ValidationError as exc:
        log.error("Structured output validation failed: %s", exc)
        try:
            result = schema()  # type: ignore[call-arg]
        except ValidationError:
            raise
    cost = CostLedger(llm_calls=1)
    return result, cost
