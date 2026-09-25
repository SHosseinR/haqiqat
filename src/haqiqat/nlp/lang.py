"""Script-based language identification for the languages we ingest.

Each feed declares its language in the registry, so this is a sanity check that catches
mixed feeds (for example an English page on a Persian site). Distinguishing Persian
from Arabic relies on letters only Persian uses (پ چ ژ گ) and on Arabic-only letters.
"""

from __future__ import annotations

_PERSIAN_ONLY = set("پچژگ")
_ARABIC_ONLY = set("ةيكإأٱىؤ")


def detect(text: str, default: str | None = None) -> str | None:
    if not text:
        return default
    latin = arabic_script = persian_marks = arabic_marks = hebrew = 0
    for ch in text:
        o = ord(ch)
        if ch.isascii() and ch.isalpha():
            latin += 1
        elif 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0xFB50 <= o <= 0xFEFF:
            arabic_script += 1
            if ch in _PERSIAN_ONLY or ch == "ی" or ch == "ک":
                persian_marks += 1
            elif ch in _ARABIC_ONLY:
                arabic_marks += 1
        elif 0x0590 <= o <= 0x05FF:
            hebrew += 1
    total = latin + arabic_script + hebrew
    if total < 10:
        return default
    if arabic_script / total > 0.5:
        if persian_marks >= arabic_marks:
            return "fa"
        return "ar"
    if hebrew / total > 0.5:
        return "he"
    if latin / total > 0.5:
        # Latin-script languages other than English are not distinguished here;
        # the feed's declared language wins in that case.
        return default if default and default not in ("fa", "ar", "he") else "en"
    return default
