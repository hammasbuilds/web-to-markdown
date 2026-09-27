"""A dependency-free token estimate.

The library ships no tokenizer: vocabularies are megabytes and model-specific.
Instead it splits text the way BPE pre-tokenizers do (words with their leading
space, digit groups, punctuation runs, newline runs) and charges long words and
CJK characters extra. ``bench/tokens.py`` measures this against tiktoken's
``cl100k_base`` on the benchmark pages; the README reports that error.
"""

from __future__ import annotations

import re

_CJK = r"぀-ヿ㐀-䶿一-鿿가-힯豈-﫿"
_PIECES = re.compile(
    rf"[{_CJK}]"  # one CJK character
    r"|'(?:[sdmt]|ll|ve|re)\b"  # English contractions
    rf"| ?[^\W\d_{_CJK}]+"  # a word with its leading space
    r"| ?\d{1,3}"  # digits come in groups of up to three
    r"| ?[^\s\w]+"  # a punctuation run
    r"|\n+|\s+",
    re.IGNORECASE,
)

# Letters per extra token beyond the first for long words, and characters per
# token for punctuation runs. Grid-searched against cl100k_base on the 80 pages
# of the benchmark's dev split only; results/tokens.json reports the error on
# every page.
WORD_CHARS = 10
PUNCT_CHARS = 4


def estimate_tokens(text: str) -> int:
    count = 0
    for match in _PIECES.finditer(text):
        piece = match.group()
        stripped = piece.lstrip(" ")
        if not stripped:
            count += 0 if piece == " " else 1
        elif stripped[0].isspace():
            count += 1
        elif stripped[0].isalpha() and len(stripped) > 1:
            count += 1 + (len(stripped) - 1) // WORD_CHARS
        elif not stripped[0].isalnum():
            count += (len(stripped) + PUNCT_CHARS - 1) // PUNCT_CHARS
        else:
            count += 1
    return count
