from __future__ import annotations


def truncate(text: str, max_len: int) -> str:
    """Truncate text to at most max_len characters, adding an ellipsis."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def average_length(items: list[str]) -> float:
    """Return the average character length across the given strings."""
    total = sum(len(item) for item in items)
    return total / len(items)
