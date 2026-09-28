"""Pathological page shapes: runtime must stay linear, recursion must stay bounded.

Each case once took seconds to minutes: nested layout tables rendered cells once per
enclosing level (exponential), and removing elements rebuilt the parent's child
list (quadratic). Ratios, not absolute times, carry the assertion, so a slow
machine does not fail them; the absolute bounds are generous backstops.
"""

import time

import pytest

from web2md import convert
from web2md.dom import MAX_DEPTH, parse
from web2md.markdown import to_markdown

PARA = "<p>" + "Real article sentence, with commas, and enough words to count. " * 4 + "</p>"


def seconds(html: str) -> float:
    start = time.perf_counter()
    convert(html)
    return time.perf_counter() - start


def test_nested_layout_tables_render_in_linear_time():
    closed = "<body>" + "<table><tr><td>nav</td><td>" * 40 + PARA * 5
    closed += "</td></tr></table>" * 40 + "</body>"
    unclosed = "<body>" + "<table><tr><td>" * 60 + PARA  # never closed
    for html in (closed, unclosed):
        start = time.perf_counter()
        md = to_markdown(parse(html))
        assert time.perf_counter() - start < 2.0
        assert "Real article sentence" in md
        assert seconds(html) < 5.0


def _siblings(n: int) -> str:
    return "<body>" + "<div class='share'>x</div>" * n + PARA * 20 + "</body>"


def _nested(n: int) -> str:
    return "<body>" + "<div>" * n + PARA + "</div>" * n + "</body>"


@pytest.mark.parametrize("build", [_siblings, _nested], ids=["siblings", "nested"])
def test_many_elements_scale_linearly(build):
    small, large = seconds(build(2000)), seconds(build(8000))
    # Four times the elements: linear is ~4x; the old quadratic removal was ~16x.
    assert large < 8 * max(small, 0.02)
    assert large < 20.0
    assert "Real article sentence" in convert(build(8000)).markdown


@pytest.mark.parametrize(
    "open_tag, close_tag",
    [
        ("<blockquote>", "</blockquote>"),
        ("<ul><li>", "</li></ul>"),
        ("<table><tr><td>", "</td></tr></table>"),
        ("<span>", "</span>"),
        ("<b><i>", "</i></b>"),
    ],
)
def test_maximum_depth_does_not_hit_the_recursion_limit(open_tag, close_tag):
    html = "<body>" + open_tag * MAX_DEPTH + "deep text" + close_tag * MAX_DEPTH + "</body>"
    assert "deep text" in convert(html, main_content=False).markdown
    assert "deep text" in convert(html).markdown
