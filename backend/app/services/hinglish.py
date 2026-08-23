"""
Devanagari to romanised Hinglish, for matching only.

Superseded by `indic`, which does the same job for Odia, Marathi and the rest
of the Indian scripts rather than Hindi alone. Kept as a thin re-export so the
older name in the README diagrams and in any external script still resolves.

New code should import `indic` directly.
"""

from __future__ import annotations

from .indic import (  # noqa: F401
    DIGITS,
    VOCABULARY,
    has_devanagari,
    normalize,
    romanise,
)

__all__ = ["DIGITS", "VOCABULARY", "has_devanagari", "normalize", "romanise"]
