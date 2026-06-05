import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure server import sees test-friendly env values.
os.environ.setdefault("OPENAI_API_KEY", "test-openai")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FTA_OUTPUT_DIR", str(tmp_path))
    # Reload settings so the server reads our temp out dir.
    from founding_team_analyzer import config as cfg
    cfg.SETTINGS = cfg.Settings.load()

    from founding_team_analyzer.server import create_app

    app = create_app()
    return TestClient(app), tmp_path


def test_health_endpoint(client):
    c, _ = client
    r = c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_reasoning"]
    assert "reasoning_effort" in body


def test_runs_list_empty(client):
    c, _ = client
    r = c.get("/api/runs")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_runs_list_and_get(client):
    c, tmp = client
    run_dir = tmp / "acme"
    run_dir.mkdir()
    report = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "raw_input": "Acme",
        "company": {"name": "Acme", "website": "https://acme.test"},
        "founders": [],
        "overlaps": None,
        "score": {
            "criteria": [],
            "overall_0_100": 72.0,
            "tier": "Promising",
            "top_strengths": [],
            "top_risks": [],
            "open_questions": [],
        },
        "warnings": [],
        "cost": None,
    }
    (run_dir / "report.json").write_text(json.dumps(report))
    (run_dir / "report.md").write_text("# Acme report")

    listing = c.get("/api/runs").json()
    assert len(listing["items"]) == 1
    item = listing["items"][0]
    assert item["slug"] == "acme"
    assert item["company_name"] == "Acme"
    assert item["tier"] == "Promising"
    assert item["overall_0_100"] == 72.0

    detail = c.get("/api/runs/acme").json()
    assert detail["slug"] == "acme"
    assert detail["report"]["company"]["name"] == "Acme"
    assert detail["markdown"].startswith("# Acme")


def test_run_detail_404(client):
    c, _ = client
    r = c.get("/api/runs/does-not-exist")
    assert r.status_code == 404
