"""Normalization helpers for names, schools, companies, URLs."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse


_WHITESPACE = re.compile(r"\s+")
_SLUG_SAFE = re.compile(r"[^a-z0-9]+")
_TITLE_SUFFIXES = {"inc", "inc.", "llc", "ltd", "ltd.", "corp", "corp.", "co", "co.", "gmbh"}
_SCHOOL_NORMALIZATIONS = {
    "mit": "Massachusetts Institute of Technology",
    "massachusetts institute of technology": "Massachusetts Institute of Technology",
    "stanford": "Stanford University",
    "stanford university": "Stanford University",
    "harvard": "Harvard University",
    "harvard university": "Harvard University",
    "uc berkeley": "UC Berkeley",
    "university of california, berkeley": "UC Berkeley",
    "berkeley": "UC Berkeley",
    "cmu": "Carnegie Mellon University",
    "carnegie mellon": "Carnegie Mellon University",
}
_FOUNDER_TITLE_RE = re.compile(
    r"\b(founder|co[-\s]?founder|founding (member|engineer|partner|team)|ceo|cto|cpo|coo|cmo|chief [a-z]+ officer)\b",
    re.IGNORECASE,
)


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = _SLUG_SAFE.sub("-", text.lower()).strip("-")
    return text[:max_len] or "company"


def normalize_name(name: str) -> str:
    if not name:
        return ""
    cleaned = unicodedata.normalize("NFKD", name)
    cleaned = cleaned.encode("ascii", "ignore").decode("ascii")
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    return cleaned.title()


def normalize_company(name: str) -> str:
    if not name:
        return ""
    tokens = [t for t in re.split(r"\s+", name.strip()) if t]
    if tokens and tokens[-1].lower().rstrip(",") in _TITLE_SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens).strip().lower()


def normalize_school(name: str) -> str:
    if not name:
        return ""
    key = _WHITESPACE.sub(" ", name).strip().lower()
    return _SCHOOL_NORMALIZATIONS.get(key, name.strip())


def is_founder_title(title: str | None) -> bool:
    if not title:
        return False
    return bool(_FOUNDER_TITLE_RE.search(title))


def detect_input_type(value: str) -> str:
    """Return one of: 'linkedin_company', 'url', 'name'."""
    if not value:
        return "name"
    candidate = value.strip()
    if candidate.startswith("http://") or candidate.startswith("https://"):
        parsed = urlparse(candidate)
        if "linkedin.com" in parsed.netloc and "/company/" in parsed.path:
            return "linkedin_company"
        return "url"
    if "://" not in candidate and "." in candidate and " " not in candidate:
        return "url"
    return "name"


def ensure_scheme(url: str) -> str:
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"https://{url}"


def year_ranges_overlap(
    a_start: int | None,
    a_end: int | None,
    b_start: int | None,
    b_end: int | None,
) -> str | None:
    """Return a 'YYYY-YYYY' overlap string if year ranges intersect, else None.

    Treats None on end as 'present' (current year sentinel: 9999).
    Treats None on start as unknown -> no overlap unless other side is fully unknown.
    """
    if a_start is None and a_end is None:
        return None
    if b_start is None and b_end is None:
        return None
    if a_start is None and b_start is None:
        return None
    a_s = a_start if a_start is not None else 0
    a_e = a_end if a_end is not None else 9999
    b_s = b_start if b_start is not None else 0
    b_e = b_end if b_end is not None else 9999
    start = max(a_s, b_s)
    end = min(a_e, b_e)
    if start > end:
        return None
    if start == 0 or end == 9999:
        return None
    return f"{start}-{end}"
