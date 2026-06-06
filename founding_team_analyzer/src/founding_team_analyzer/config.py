"""Runtime configuration: env vars, model names, per-run caps."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_VALID_EFFORTS = {"none", "low", "medium", "high", "xhigh"}


def _effort_env(name: str, default: str) -> str:
    raw = (os.getenv(name) or "").strip().lower()
    return raw if raw in _VALID_EFFORTS else default


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    tavily_api_key: str | None
    model_reasoning: str
    model_extract: str
    reasoning_effort: str
    extract_effort: str
    max_founders: int
    max_tavily_per_founder: int
    max_extracts_per_founder: int
    max_llm_calls: int
    max_registry_runs: int
    http_timeout: int
    output_dir: Path

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            tavily_api_key=os.getenv("TAVILY_API_KEY"),
            model_reasoning=os.getenv("FTA_MODEL_REASONING", "gpt-5.5"),
            model_extract=os.getenv("FTA_MODEL_EXTRACT", "gpt-5.5"),
            reasoning_effort=_effort_env("FTA_REASONING_EFFORT", "medium"),
            extract_effort=_effort_env("FTA_EXTRACT_EFFORT", "low"),
            max_founders=_int_env("FTA_MAX_FOUNDERS", 5),
            max_tavily_per_founder=_int_env("FTA_MAX_TAVILY_PER_FOUNDER", 8),
            max_extracts_per_founder=_int_env("FTA_MAX_EXTRACTS_PER_FOUNDER", 4),
            max_llm_calls=_int_env("FTA_MAX_LLM_CALLS", 30),
            max_registry_runs=_int_env("FTA_MAX_REGISTRY_RUNS", 100),
            http_timeout=_int_env("FTA_HTTP_TIMEOUT", 15),
            output_dir=Path(os.getenv("FTA_OUTPUT_DIR", "./out")),
        )


SETTINGS = Settings.load()
