r"""Turn any system's markdown into the plain text the ground truth is written in.

Applied identically to every system before scoring:

* images (``![alt](src)``) are dropped - the benchmarks' article text never
  includes alt text, so keeping it would charge markdown output for images;
* links keep their text and lose their target - URLs are not article words;
* code-fence info strings (the language tag) are dropped.

Markdown punctuation needs no stripping: the metric tokenises on ``\w+``.
"""

from __future__ import annotations

import re

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_FENCE_INFO = re.compile(r"^(\s*)(`{3,}|~{3,})[^\n`]*$", re.MULTILINE)


def markdown_to_text(md: str) -> str:
    text = _IMAGE.sub("", md)
    while True:  # "[[a](b)](c)" needs a second pass
        stripped = _LINK.sub(r"\1", text)
        if stripped == text:
            break
        text = stripped
    return _FENCE_INFO.sub(r"\1\2", text)
