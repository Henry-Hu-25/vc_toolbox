"""Typer CLI entrypoint."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from . import config as config_module
from .graph import run_analysis

app = typer.Typer(add_completion=False, help="Founding Team Analyzer", no_args_is_help=True)
console = Console()


@app.callback()
def _root() -> None:
    """Founding Team Analyzer - multi-agent analysis of a startup's founders."""
    # Presence of a callback forces typer into multi-command mode so `analyze`
    # is dispatched as a real subcommand (matches the spec's CLI usage).


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("founding_team_analyzer").setLevel(level)
    for noisy in ("markdown_it", "httpcore", "httpx", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@app.command()
def analyze(
    raw_input: str = typer.Argument(..., help="Company URL, LinkedIn URL, or company name."),
    out: Path = typer.Option(Path("./out"), "--out", "-o", help="Output directory root."),
    max_founders: int = typer.Option(5, "--max-founders", help="Cap researcher fan-out."),
    model: Optional[str] = typer.Option(None, "--model", help="Override the reasoning model."),
    no_self_critique: bool = typer.Option(
        False, "--no-self-critique", help="Skip the TeamScorer self-critique pass."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging."),
    save_state: Optional[Path] = typer.Option(
        None, "--save-state", help="Dump full AnalyzerState (JSON) for debugging."
    ),
) -> None:
    """Analyze the founding team for a single company."""
    _configure_logging(verbose)

    os.environ["FTA_OUTPUT_DIR"] = str(out)
    os.environ["FTA_MAX_FOUNDERS"] = str(max_founders)
    if model:
        os.environ["FTA_MODEL_REASONING"] = model

    # Refresh the cached Settings now that env vars are set.
    config_module.SETTINGS = config_module.Settings.load()

    if not config_module.SETTINGS.openai_api_key or not config_module.SETTINGS.tavily_api_key:
        console.print(
            "[bold red]Missing API keys.[/bold red] Set OPENAI_API_KEY and TAVILY_API_KEY in .env."
        )
        raise typer.Exit(code=2)

    console.print(Panel.fit(f"Analyzing: [bold]{raw_input}[/bold]", title="Founding Team Analyzer"))

    try:
        state = run_analysis(raw_input, no_self_critique=no_self_critique)
    except Exception as exc:
        console.print(f"[red]Run failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    report_md = state.get("report_md") or "_No report produced._"
    console.print(Markdown(report_md))

    if state.get("warnings"):
        console.print(Panel(
            "\n".join(f"- {w}" for w in state["warnings"]),
            title="Warnings",
            border_style="yellow",
        ))

    if save_state:
        try:
            save_state.parent.mkdir(parents=True, exist_ok=True)
            serializable = {
                "raw_input": state.get("raw_input"),
                "company": state["company"].model_dump() if state.get("company") else None,
                "founders": [f.model_dump() for f in (state.get("founders") or [])],
                "profiles": [p.model_dump() for p in (state.get("profiles") or [])],
                "overlaps": state["overlaps"].model_dump() if state.get("overlaps") else None,
                "score": state["score"].model_dump() if state.get("score") else None,
                "warnings": list(state.get("warnings") or []),
                "cost": state["cost"].model_dump() if state.get("cost") else None,
                "report_md": state.get("report_md"),
            }
            save_state.write_text(json.dumps(serializable, ensure_ascii=False, indent=2))
            console.print(f"[green]State saved to[/green] {save_state}")
        except Exception as exc:
            console.print(f"[yellow]Could not save state:[/yellow] {exc}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind."),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging."),
) -> None:
    """Start the FastAPI server (for the web UI)."""
    _configure_logging(verbose)

    if not config_module.SETTINGS.openai_api_key or not config_module.SETTINGS.tavily_api_key:
        console.print(
            "[bold red]Missing API keys.[/bold red] Set OPENAI_API_KEY and TAVILY_API_KEY in .env."
        )
        raise typer.Exit(code=2)

    try:
        import uvicorn  # type: ignore
    except ImportError as exc:
        console.print(
            "[bold red]uvicorn not installed.[/bold red] "
            "Run: pip install -e '.[server]'"
        )
        raise typer.Exit(code=2) from exc

    console.print(Panel.fit(
        f"FastAPI on [bold]http://{host}:{port}[/bold]\n"
        f"Model: [cyan]{config_module.SETTINGS.model_reasoning}[/cyan] "
        f"(effort: {config_module.SETTINGS.reasoning_effort})",
        title="Founding Team Analyzer - Server",
    ))
    uvicorn.run(
        "founding_team_analyzer.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info" if not verbose else "debug",
    )


def main() -> None:  # pragma: no cover - CLI entrypoint
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
