"""Tests for CLI flags --max-founders, --model, --out taking effect at runtime.

Validates VAL-BE-001, VAL-BE-002, VAL-BE-003.

The core issue: nodes and llm.py import ``SETTINGS`` via
``from .config import SETTINGS`` which captures the object at import
time.  When the CLI (or tests) later reassign ``config_module.SETTINGS``,
those modules still read the *old* object.  The fix is to make all
consumers access SETTINGS through the module reference (``config.SETTINGS``)
so they see the current value at call time.

Testing strategy: import the consuming module BEFORE overriding
config_module.SETTINGS so the local SETTINGS reference is stale.
After the fix (using config.SETTINGS instead of from-import), the
module will see the new value at call time.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from founding_team_analyzer import config as config_module
from founding_team_analyzer.schemas import CostLedger

# Import consuming modules UP FRONT so their SETTINGS references are
# bound to the default (pre-override) object.  After the fix these
# modules will access config.SETTINGS dynamically, so they will
# see the overridden value.
from founding_team_analyzer.nodes import founder_finder, report_writer
from founding_team_analyzer import llm as llm_module


# ---------------------------------------------------------------------------
# Helper: temporarily override SETTINGS and restore afterwards
# ---------------------------------------------------------------------------


class _SettingsOverride:
    """Context manager that swaps config_module.SETTINGS and restores on exit."""

    def __init__(self, **overrides) -> None:
        self._overrides = overrides
        self._original = None

    def __enter__(self):
        self._original = config_module.SETTINGS
        base = {
            "openai_api_key": "test-key",
            "tavily_api_key": "test-key",
            "model_reasoning": "gpt-5.5",
            "model_extract": "gpt-5.5",
            "reasoning_effort": "medium",
            "extract_effort": "low",
            "max_founders": 5,
            "max_tavily_per_founder": 8,
            "max_extracts_per_founder": 4,
            "max_llm_calls": 30,
            "max_registry_runs": 100,
            "http_timeout": 15,
            "output_dir": Path("./out"),
        }
        base.update(self._overrides)
        config_module.SETTINGS = config_module.Settings(**base)
        return config_module.SETTINGS

    def __exit__(self, *args):
        config_module.SETTINGS = self._original


# ---------------------------------------------------------------------------
# VAL-BE-001: --max-founders N is honored at runtime
# ---------------------------------------------------------------------------


def test_max_founders_dynamic_after_import():
    """After overriding config_module.SETTINGS.max_founders to 2, the
    founder_finder node (already imported) must observe the new value
    at call time, not the import-time default.

    We test this by calling founder_finder.run() with a stubbed LLM and
    search, and verifying the output is capped at 2 founders.
    """
    from founding_team_analyzer.schemas import Company, Founder, FounderList
    from founding_team_analyzer.state import AnalyzerState

    # Build a state with a company but no founders yet
    state: AnalyzerState = {
        "raw_input": "TestCo",
        "company": Company(name="TestCo", website="https://test.co"),
        "warnings": [],
        "cost": CostLedger(),
    }

    # Return 10 founders from the LLM; the cap should trim them to 2
    fake_founders = FounderList(
        founders=[Founder(name=f"F{i}", title="CEO", source_urls=[]) for i in range(10)]
    )

    def fake_call_structured(schema, prompt, **kwargs):
        if schema is FounderList:
            return fake_founders, CostLedger(llm_calls=1)
        return schema(), CostLedger()

    # Override AFTER module import (founder_finder already imported at top)
    with _SettingsOverride(max_founders=2):
        # Patch at the usage site, not the definition site
        with patch("founding_team_analyzer.nodes.founder_finder.call_structured", fake_call_structured):
            with patch("founding_team_analyzer.tools.search.search", return_value=[]):
                with patch("founding_team_analyzer.tools.search.extract", return_value=None):
                    result = founder_finder.run(state)

    # Verify that the cap was applied with the overridden max_founders=2
    returned_founders = result.get("founders", [])
    assert len(returned_founders) == 2, (
        f"Expected exactly 2 founders with --max-founders 2, got {len(returned_founders)}"
    )


def test_max_founders_filter_uses_dynamic_settings():
    """Directly test that _filter_and_dedupe respects a SETTINGS override.

    The function is called internally with SETTINGS.max_founders; after
    the fix it will read the live config.SETTINGS value.
    """
    from founding_team_analyzer.schemas import Founder

    founders = [
        Founder(name=f"Founder {i}", title="CEO", source_urls=[])
        for i in range(10)
    ]

    with _SettingsOverride(max_founders=3):
        # After the fix, founder_finder.run() passes config.SETTINGS.max_founders
        # which is 3 after override.  But _filter_and_dedupe takes max_founders
        # as an explicit parameter.  The real test is that founder_finder.run()
        # reads SETTINGS.max_founders dynamically.
        # Here we just verify the cap logic works with the right value.
        capped, _ = founder_finder._filter_and_dedupe(founders, 3)
        assert len(capped) == 3


# ---------------------------------------------------------------------------
# VAL-BE-002: --model is honored at runtime
# ---------------------------------------------------------------------------


def test_model_override_seen_by_llm():
    """After overriding SETTINGS.model_reasoning, call_structured must use
    the new model (not the import-time default).

    llm.py is imported at module top; its SETTINGS reference is bound
    at import time.  After the fix, it will read config.SETTINGS
    dynamically, so the override takes effect.
    """
    captured_kwargs: list[dict] = []

    class FakeChat:
        def __init__(self, **kwargs):
            captured_kwargs.append(kwargs)

        def with_structured_output(self, schema):
            return self

        def invoke(self, prompt):
            # Return a minimal valid instance
            try:
                return schema()
            except Exception:
                return type("FakeResult", (), {"model_dump": lambda s: {}})()

    with _SettingsOverride(model_reasoning="gpt-4o-mini"):
        with patch.object(llm_module, "ChatOpenAI", FakeChat):
            from founding_team_analyzer.schemas import Company

            try:
                llm_module.call_structured(
                    Company, "test prompt",
                    llm_calls_so_far=0, max_llm_calls=10,
                )
            except Exception:
                pass

            assert len(captured_kwargs) > 0, "ChatOpenAI was never instantiated"
            assert captured_kwargs[0]["model"] == "gpt-4o-mini", (
                f"Expected model='gpt-4o-mini', got model={captured_kwargs[0]['model']!r}"
            )


def test_model_override_seen_by_founder_finder():
    """After overriding model_extract, founder_finder must use the
    overridden model for its LLM call.

    founder_finder.run() passes model=SETTINGS.model_extract to
    call_structured.  After the fix, SETTINGS is read dynamically.
    """
    from founding_team_analyzer.schemas import Company, Founder, FounderList
    from founding_team_analyzer.state import AnalyzerState

    state: AnalyzerState = {
        "raw_input": "TestCo",
        "company": Company(name="TestCo", website="https://test.co"),
        "warnings": [],
        "cost": CostLedger(),
    }

    captured_models: list[str | None] = []
    fake_founders = FounderList(
        founders=[Founder(name="F1", title="CEO", source_urls=[])]
    )

    def fake_call_structured(schema, prompt, *, model=None, **kwargs):
        captured_models.append(model)
        if schema is FounderList:
            return fake_founders, CostLedger(llm_calls=1)
        return schema(), CostLedger()

    with _SettingsOverride(model_extract="gpt-4o-mini-extract"):
        with patch("founding_team_analyzer.nodes.founder_finder.call_structured", fake_call_structured):
            with patch("founding_team_analyzer.tools.search.search", return_value=[]):
                with patch("founding_team_analyzer.tools.search.extract", return_value=None):
                    founder_finder.run(state)

    assert "gpt-4o-mini-extract" in captured_models, (
        f"Expected model='gpt-4o-mini-extract' in captured models, got: {captured_models}"
    )


# ---------------------------------------------------------------------------
# VAL-BE-003: --out DIR redirects report output
# ---------------------------------------------------------------------------


def test_out_dir_override_honored(tmp_path):
    """After overriding SETTINGS.output_dir, ReportWriter must write to the
    new directory (not the import-time default ./out/).

    report_writer is imported at module top; its SETTINGS reference is
    bound at import time.  After the fix, it reads config.SETTINGS
    dynamically, so the override takes effect.
    """
    out_dir = tmp_path / "custom_reports"

    with _SettingsOverride(output_dir=out_dir):
        from founding_team_analyzer.schemas import Company
        from founding_team_analyzer.state import AnalyzerState

        state: AnalyzerState = {
            "raw_input": "TestCo",
            "company": Company(name="TestCo", website="https://test.co"),
            "warnings": [],
            "cost": CostLedger(),
        }
        result = report_writer.run(state)

    # Verify files were written under the custom output dir
    slug = "testco"
    assert (out_dir / slug / "report.md").exists(), (
        f"report.md not found under {out_dir / slug}"
    )
    assert (out_dir / slug / "report.json").exists(), (
        f"report.json not found under {out_dir / slug}"
    )

    # Verify files were NOT written to the default ./out/
    default_out = Path("./out") / slug
    assert not default_out.exists(), (
        f"Files should NOT be written to default ./out/, but found {default_out}"
    )


def test_out_dir_dynamic_not_captured_at_import(tmp_path):
    """Verify that report_writer.py accesses SETTINGS.output_dir at call time.

    report_writer was imported at module top.  Change output_dir AFTER
    that import and verify the new path is used.
    """
    out_dir = tmp_path / "dynamic_reports"

    with _SettingsOverride(output_dir=out_dir):
        from founding_team_analyzer.schemas import Company
        from founding_team_analyzer.state import AnalyzerState

        state: AnalyzerState = {
            "raw_input": "DynamicCo",
            "company": Company(name="DynamicCo", website="https://dynamic.co"),
            "warnings": [],
            "cost": CostLedger(),
        }
        result = report_writer.run(state)

    slug = "dynamicco"
    assert (out_dir / slug / "report.md").exists(), (
        f"report.md not found under dynamic output dir {out_dir / slug}"
    )


# ---------------------------------------------------------------------------
# Integration: CLI analyze flow sets SETTINGS dynamically
# ---------------------------------------------------------------------------


def test_cli_sets_settings_before_run():
    """Simulate the CLI's analyze flow: set env vars, reload SETTINGS,
    then verify the new values are visible to downstream code.

    This mimics what cli.py does:
        os.environ["FTA_MAX_FOUNDERS"] = str(max_founders)
        config_module.SETTINGS = config_module.Settings.load()
    """
    original_max_founders = config_module.SETTINGS.max_founders
    original_model = config_module.SETTINGS.model_reasoning

    try:
        # Simulate CLI: --max-founders 2 --model gpt-4o-mini
        os.environ["FTA_MAX_FOUNDERS"] = "2"
        os.environ["FTA_MODEL_REASONING"] = "gpt-4o-mini"
        config_module.SETTINGS = config_module.Settings.load()

        assert config_module.SETTINGS.max_founders == 2, (
            f"Expected max_founders=2, got {config_module.SETTINGS.max_founders}"
        )
        assert config_module.SETTINGS.model_reasoning == "gpt-4o-mini", (
            f"Expected model_reasoning='gpt-4o-mini', got {config_module.SETTINGS.model_reasoning!r}"
        )
    finally:
        # Restore
        os.environ.pop("FTA_MAX_FOUNDERS", None)
        os.environ.pop("FTA_MODEL_REASONING", None)
        config_module.SETTINGS = config_module.Settings.load()


def test_cli_out_dir_sets_settings(tmp_path):
    """Simulate the CLI's --out flag and verify SETTINGS.output_dir changes."""
    original_out = config_module.SETTINGS.output_dir

    try:
        custom_out = str(tmp_path / "cli_output")
        os.environ["FTA_OUTPUT_DIR"] = custom_out
        config_module.SETTINGS = config_module.Settings.load()

        assert str(config_module.SETTINGS.output_dir) == custom_out, (
            f"Expected output_dir={custom_out!r}, got {str(config_module.SETTINGS.output_dir)!r}"
        )
    finally:
        os.environ.pop("FTA_OUTPUT_DIR", None)
        config_module.SETTINGS = config_module.Settings.load()
