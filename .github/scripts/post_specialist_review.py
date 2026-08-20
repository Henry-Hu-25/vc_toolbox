#!/usr/bin/env python3
"""Submit one specialist droid's findings as a GitHub pull request review.

Findings arrive as JSON from the droid. Each becomes an inline review comment
anchored to a line, mirroring how the built-in reviewer posts, rather than a single
issue comment nobody can resolve.

Two constraints drive the design:

1. GitHub rejects the whole review with a 422 if any inline comment targets a line
   that is not addressable in the diff. Every anchor is therefore validated against
   the diff hunks first, and anything unaddressable is demoted into the review body
   instead of being dropped or taking the review down with it.
2. `synchronize` re-runs this on every push, so findings already posted are skipped
   to keep a long-lived PR from accumulating the same comment repeatedly.

Stdlib only: this runs on a bare runner with no pip install step.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
SEVERITY_ORDER = {"P1": 0, "P2": 1, "P3": 2}
MAX_COMMENTS = 3


def fail(msg: str) -> None:
    print(f"::error title=Specialist review post failed::{msg}")
    sys.exit(1)


def warn(title: str, msg: str) -> None:
    print(f"::warning title={title}::{msg}")


def api(method: str, path: str, token: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:800]
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def addressable_lines(diff_text: str) -> dict[str, set[int]]:
    """Map each path to the new-file line numbers a review comment may target.

    Only lines present in a hunk are addressable, and only on the RIGHT side, so
    added and context lines count while removed lines do not.
    """
    lines: dict[str, set[int]] = {}
    path: str | None = None
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            path = None if target == "/dev/null" else re.sub(r"^b/", "", target)
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            new_line = int(m.group(1)) if m else 0
            continue
        if path is None or new_line == 0:
            continue
        if raw.startswith("+"):
            lines.setdefault(path, set()).add(new_line)
            new_line += 1
        elif raw.startswith("-") or raw.startswith("\\"):
            continue
        else:  # context line
            lines.setdefault(path, set()).add(new_line)
            new_line += 1
    return lines


def parse_findings(result_text: str) -> dict:
    """Parse the droid's JSON, tolerating a stray markdown fence around it."""
    text = result_text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found in droid output")
        text = text[start : end + 1]
    doc = json.loads(text)
    if not isinstance(doc, dict):
        raise ValueError("droid output is not a JSON object")
    doc.setdefault("comments", [])
    doc.setdefault("summary", "")
    if not isinstance(doc["comments"], list):
        raise ValueError("`comments` is not a list")
    return doc


def build_body(finding: dict, droid: str) -> str:
    severity = str(finding.get("severity", "P2")).upper()
    if severity not in SEVERITY_ORDER:
        severity = "P2"
    title = str(finding.get("title", "")).strip()
    body = str(finding.get("body", "")).strip()
    parts = [f"**[{severity}] {title}**" if title else f"**[{severity}]**", "", body]
    suggestion = finding.get("suggestion")
    if isinstance(suggestion, str) and suggestion.strip():
        parts += ["", "```suggestion", suggestion.rstrip("\n"), "```"]
    parts += ["", f"<sub>specialist `{droid}`</sub>"]
    return "\n".join(parts).strip()


def dedupe_key(path: str, line: int, title: str) -> str:
    return f"{path}:{line}:{title.strip().lower()}"


def existing_keys(repo: str, pr: int, token: str, droid: str) -> set[str]:
    """Keys for inline comments this droid already posted on the PR."""
    keys: set[str] = set()
    marker = f"<sub>specialist `{droid}`</sub>"
    page = 1
    while page <= 10:
        batch = api("GET", f"/repos/{repo}/pulls/{pr}/comments?per_page=100&page={page}", token)
        if not batch:
            break
        for c in batch:
            body = c.get("body") or ""
            if marker not in body:
                continue
            m = re.search(r"\*\*\[P[123]\]\s*(.+?)\*\*", body)
            title = m.group(1) if m else ""
            line = c.get("line") or c.get("original_line") or 0
            keys.add(dedupe_key(c.get("path", ""), line, title))
        if len(batch) < 100:
            break
        page += 1
    return keys


def main() -> int:
    if len(sys.argv) != 3:
        fail("usage: post_specialist_review.py <droid-output.json> <scoped.diff>")

    env = os.environ
    for required in ("GH_TOKEN", "REPO", "PR_NUMBER", "HEAD_SHA", "DROID_NAME", "TITLE"):
        if not env.get(required):
            fail(f"missing required environment variable {required}")

    token = env["GH_TOKEN"]
    repo = env["REPO"]
    pr = int(env["PR_NUMBER"])
    head_sha = env["HEAD_SHA"]
    droid = env["DROID_NAME"]
    title = env["TITLE"]

    raw = json.load(open(sys.argv[1], encoding="utf-8"))
    result_text = raw.get("result") if isinstance(raw, dict) else None
    if not isinstance(result_text, str) or not result_text.strip():
        fail("droid output had no usable `result` field")

    try:
        doc = parse_findings(result_text)
    except (ValueError, json.JSONDecodeError) as exc:
        warn("Specialist output unparsable", f"{droid}: {exc}")
        print("status=unavailable")
        return 0

    findings = [f for f in doc["comments"] if isinstance(f, dict)]
    findings.sort(key=lambda f: SEVERITY_ORDER.get(str(f.get("severity", "P2")).upper(), 1))
    findings = findings[:MAX_COMMENTS]

    if not findings:
        print(f"{droid}: no findings; nothing to post.")
        print("status=clean")
        return 0

    with open(sys.argv[2], encoding="utf-8") as fh:
        anchorable = addressable_lines(fh.read())

    try:
        already = existing_keys(repo, pr, token, droid)
    except RuntimeError as exc:
        warn("Dedupe lookup failed", f"{droid}: {exc}")
        already = set()

    inline: list[dict] = []
    demoted: list[str] = []
    skipped = 0

    for f in findings:
        path = str(f.get("path", "")).strip()
        try:
            line = int(f.get("line"))
        except (TypeError, ValueError):
            line = 0
        body = build_body(f, droid)
        key = dedupe_key(path, line, str(f.get("title", "")))

        if key in already:
            skipped += 1
            continue
        if path and line in anchorable.get(path, set()):
            inline.append({"path": path, "line": line, "side": "RIGHT", "body": body})
        else:
            # Unaddressable anchors would 422 the entire review, so carry them in the
            # body with their location spelled out instead.
            reason = "path not in scoped diff" if path not in anchorable else "line not in a diff hunk"
            demoted.append(f"- `{path}:{line}` ({reason})\n\n{body}")

    if not inline and not demoted:
        print(f"{droid}: all {skipped} finding(s) already posted; nothing new.")
        print("status=clean")
        return 0

    summary = str(doc.get("summary", "")).strip()
    header = [f"### {title}", ""]
    if summary:
        header += [summary, ""]
    header.append(
        f"{len(inline)} inline comment(s)"
        + (f", {len(demoted)} not anchorable" if demoted else "")
        + (f", {skipped} already posted" if skipped else "")
        + f" &middot; `{head_sha[:7]}`"
    )
    if demoted:
        header += ["", "<details><summary>Findings that could not be anchored</summary>", ""]
        header += demoted
        header += ["", "</details>"]

    payload = {
        "commit_id": head_sha,
        "body": "\n".join(header),
        "event": "COMMENT",
        "comments": inline,
    }

    try:
        review = api("POST", f"/repos/{repo}/pulls/{pr}/reviews", token, payload)
    except RuntimeError as exc:
        # Retry without inline comments rather than losing the findings entirely: a
        # rejected anchor should not silence the reviewer.
        warn("Inline review rejected", f"{droid}: {exc}")
        fallback = dict(payload)
        fallback["comments"] = []
        fallback["body"] = "\n".join(
            header + ["", "Inline anchoring failed; findings follow.", ""]
            + [f"- `{c['path']}:{c['line']}`\n\n{c['body']}" for c in inline]
        )
        try:
            review = api("POST", f"/repos/{repo}/pulls/{pr}/reviews", token, fallback)
        except RuntimeError as exc2:
            warn("Review submission failed", f"{droid}: {exc2}")
            print("status=unavailable")
            return 0
        print(f"{droid}: submitted summary-only review {review.get('id')}")
        print("status=findings")
        return 0

    print(
        f"{droid}: submitted review {review.get('id')} with {len(inline)} inline "
        f"comment(s), {len(demoted)} demoted, {skipped} skipped as duplicates"
    )
    print("status=findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
