"""Job parser — normalises raw scraped text and detects experience level & location."""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_html(html: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(html)
    return re.sub(r"\s+", " ", stripper.get_text()).strip()


def normalise_text(text: str) -> str:
    """Strip HTML, collapse whitespace, lower-case for matching."""
    return strip_html(text).lower()


# Experience-level signal patterns (English + common Hebrew)
_ENTRY_PATTERNS = [
    r"entry[\s-]level",
    r"\bjunior\b",
    r"0[\s-]?[-–][\s-]?[12]\s*years?",
    r"new\s+grad(?:uate)?",
    r"fresh\s+grad(?:uate)?",
    r"recent\s+grad(?:uate)?",
    r"no\s+(?:prior\s+)?(?:work\s+)?experience\s+required",
    r"no\s+experience\s+needed",
    r"\bgraduate\b",
    r"בוגר(?:\s+טרי)?",    # Hebrew: "graduate" / "fresh graduate"
    r"ללא\s+ניסיון",       # Hebrew: "no experience"
    r"ניסיון\s+של\s+0",   # Hebrew: "0 years experience"
]

_ENTRY_RE = re.compile("|".join(_ENTRY_PATTERNS), re.IGNORECASE | re.UNICODE)

_MID_PATTERNS = [r"3[\s-]?[-–]\d+\s*years?", r"senior", r"\bstaff\b", r"\bprincipal\b", r"\blead\b"]
_MID_RE = re.compile("|".join(_MID_PATTERNS), re.IGNORECASE)


def detect_experience_level(text: str) -> str | None:
    """Return 'entry', 'mid', or None."""
    if _ENTRY_RE.search(text):
        return "entry"
    if _MID_RE.search(text):
        return "mid"
    return None


def make_external_id(url: str) -> str:
    """Generate a stable ID from a URL (for sources that don't expose a native job ID)."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]
