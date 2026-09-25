"""Text normalization, tokenization and sentence splitting for English, Persian and Arabic.

Persian text on the web mixes Arabic and Persian code points for the same letters
(ي/ی, ك/ک), uses several kinds of zero-width joiners, and three digit systems. Matching,
deduplication and gazetteer lookup all break unless these are unified first.
"""

from __future__ import annotations

import re
import unicodedata

ZWNJ = "\u200c"

_CHAR_MAP = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ئ": "ی",
        "ك": "ک",
        "ة": "ه",
        "ۀ": "ه",
        "أ": "ا",
        "إ": "ا",
        "ٱ": "ا",
        "ؤ": "و",
        "\u0640": "",  # tatweel
        "\u200d": "",  # zero-width joiner
        "\u200b": "",  # zero-width space
        "\u00a0": " ",
        "\u202a": "",
        "\u202b": "",
        "\u202c": "",
        "\u200e": "",
        "\u200f": "",
    }
)

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
# Arabic diacritics (harakat), superscript alef, etc.
_DIACRITICS = re.compile("[\u064b-\u065f\u0670\u06d6-\u06ed]")
_SPACES = re.compile(r"\s+")
_TOKEN = re.compile(r"[\w‌]+", re.UNICODE)
_SENTENCE_END = re.compile(r"(?<=[.!?؟۔])\s+|\n+")


def normalize(text: str) -> str:
    """Canonical form used for matching (not for display)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_CHAR_MAP)
    text = _DIACRITICS.sub("", text)
    text = text.translate(_DIGITS)
    return _SPACES.sub(" ", text).strip()


def tokens(text: str) -> list[str]:
    """Lowercased tokens of normalized text. ZWNJ-joined Persian words stay one token."""
    return [t.strip(ZWNJ).lower() for t in _TOKEN.findall(normalize(text)) if t.strip(ZWNJ)]


def sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = _SENTENCE_END.split(text.strip())
    return [p.strip() for p in parts if len(p.strip()) > 1]


def to_persian_digits(value: object) -> str:
    return str(value).translate(_PERSIAN_DIGITS)


def clean_display(text: str | None, limit: int | None = None) -> str:
    """Collapse whitespace for display, optionally truncating on a word boundary."""
    if not text:
        return ""
    text = _SPACES.sub(" ", text.replace("\u0640", "")).strip()
    if limit and len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        return cut + "…"
    return text
