"""Tests for F-BE-018: CORS allowed origins driven by FTA_CORS_ORIGINS env var."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "test-openai")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily")


@pytest.fixture()
def _make_client(tmp_path: Path, monkeypatch):
    """Factory fixture: returns a function that creates a TestClient
    after optionally setting FTA_CORS_ORIGINS and reloading Settings."""

    def _factory(cors_env: str | None = None) -> TestClient:
        monkeypatch.setenv("FTA_OUTPUT_DIR", str(tmp_path))
        if cors_env is not None:
            monkeypatch.setenv("FTA_CORS_ORIGINS", cors_env)
        else:
            monkeypatch.delenv("FTA_CORS_ORIGINS", raising=False)

        from founding_team_analyzer import config as cfg

        cfg.SETTINGS = cfg.Settings.load()

        from founding_team_analyzer import runs as runs_module
        from founding_team_analyzer import server as server_module

        runs_module.REGISTRY = runs_module.RunRegistry()
        server_module.REGISTRY = runs_module.REGISTRY

        app = server_module.create_app()
        return TestClient(app)

    return _factory


class TestDefaultCorsOrigins:
    """VAL-BE-022: Default origins include localhost:3000 and 127.0.0.1:3000."""

    def test_default_origins_include_localhost(self, _make_client):
        client = _make_client(cors_env=None)
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_default_origins_include_127(self, _make_client):
        client = _make_client(cors_env=None)
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"

    def test_default_origins_exclude_unknown(self, _make_client):
        client = _make_client(cors_env=None)
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in resp.headers


class TestCustomCorsOrigins:
    """VAL-BE-023: Custom origin via FTA_CORS_ORIGINS is honored."""

    def test_custom_origin_allowed(self, _make_client):
        client = _make_client(cors_env="http://localhost:3001,http://example.com")
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3001",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3001"

    def test_another_custom_origin_allowed(self, _make_client):
        client = _make_client(cors_env="http://localhost:3001,http://example.com")
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://example.com"

    def test_unconfigured_origin_rejected(self, _make_client):
        client = _make_client(cors_env="http://localhost:3001,http://example.com")
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in resp.headers

    def test_custom_overrides_defaults(self, _make_client):
        """When FTA_CORS_ORIGINS is set, the default origins are NOT allowed."""
        client = _make_client(cors_env="http://custom.host:9999")
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in resp.headers


class TestConfigParsing:
    """Unit tests for config.py cors_origins parsing."""

    def test_unset_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FTA_CORS_ORIGINS", raising=False)
        monkeypatch.setenv("FTA_OUTPUT_DIR", str(tmp_path))
        from founding_team_analyzer import config as cfg

        s = cfg.Settings.load()
        assert s.cors_origins == ("http://localhost:3000", "http://127.0.0.1:3000")

    def test_single_origin(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FTA_CORS_ORIGINS", "http://otherhost:3000")
        monkeypatch.setenv("FTA_OUTPUT_DIR", str(tmp_path))
        from founding_team_analyzer import config as cfg

        s = cfg.Settings.load()
        assert s.cors_origins == ("http://otherhost:3000",)

    def test_multiple_comma_separated(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FTA_CORS_ORIGINS", "http://a:3000,http://b:4000,http://c:5000")
        monkeypatch.setenv("FTA_OUTPUT_DIR", str(tmp_path))
        from founding_team_analyzer import config as cfg

        s = cfg.Settings.load()
        assert s.cors_origins == ("http://a:3000", "http://b:4000", "http://c:5000")

    def test_whitespace_trimmed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FTA_CORS_ORIGINS", "  http://a:3000 , http://b:4000  ")
        monkeypatch.setenv("FTA_OUTPUT_DIR", str(tmp_path))
        from founding_team_analyzer import config as cfg

        s = cfg.Settings.load()
        assert s.cors_origins == ("http://a:3000", "http://b:4000")

    def test_empty_string_falls_back_to_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FTA_CORS_ORIGINS", "  ")
        monkeypatch.setenv("FTA_OUTPUT_DIR", str(tmp_path))
        from founding_team_analyzer import config as cfg

        s = cfg.Settings.load()
        assert s.cors_origins == ("http://localhost:3000", "http://127.0.0.1:3000")
