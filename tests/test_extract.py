from pathlib import Path

import pytest

from web2md import ExtractOptions, convert

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

PROSE = (
    "The committee met on Tuesday to discuss the proposal, which had been delayed twice, "
    "and agreed that the new timetable would begin in the spring after a public consultation."
)


def page(body: str) -> str:
    return f"<html><head><title>T</title></head><body>{body}</body></html>"


def para(i: int) -> str:
    return f"<p>Paragraph {i}. {PROSE}</p>"


def test_news_example_keeps_article_and_drops_every_boilerplate_block():
    out = convert((EXAMPLES / "news_article.html").read_text(encoding="utf-8")).markdown
    for kept in (
        "reopened to traffic",
        "1,248 suspension hangers",
        "## What changed",
        "| 2021 | 40,200 |",
        "> It feels like getting half the town back.",
        "Tolls will not be charged",
    ):
        assert kept in out
    for dropped in (
        "cookies",
        "Sport",
        "Sponsored",
        "Related stories",
        "Share on",
        "commute has been miserable",
        "All rights reserved",
        "Privacy",
    ):
        assert dropped not in out


def test_blogger_style_br_text_with_block_children_is_found():
    out = convert((EXAMPLES / "blogger_post.html").read_text(encoding="utf-8")).markdown
    assert "first frost arrived" in out
    assert "cover the brassicas" in out
    assert "Blog Archive" not in out and "Shropshire" not in out and "Email This" not in out


def test_split_article_chunks_with_the_same_class_are_joined():
    chunk = '<div class="body-chunk">{}</div>'
    body = (
        "<article><div class='grid'>"
        + chunk.format(para(1) + para(2) + para(3))
        + "</div>"
        + "<div class='grid'><div class='ad'>Advertisement</div></div>"
        + "<div class='grid'>"
        + chunk.format(para(4) + para(5) + para(6) + para(7))
        + "</div>"
        "</article><div class='sidebar'><a href='/x'>Most read</a></div>"
    )
    out = convert(page(body)).markdown
    assert all(f"Paragraph {i}." in out for i in range(1, 8))
    assert "Most read" not in out


def test_teaser_articles_nested_in_the_article_are_removed():
    teaser = (
        "<article class='teaser'><p>Teaser text that is long enough to be a paragraph "
        "of its own, with commas, too.</p></article>"
    )
    body = (
        f"<article class='post'>{para(1)}{para(2)}<h3>You may also like</h3>{teaser * 3}</article>"
    )
    out = convert(page(body)).markdown
    assert "Paragraph 2." in out
    assert "Teaser text" not in out


def test_link_heavy_list_inside_content_is_removed_but_prose_list_kept():
    links = "<ul>" + "".join(f"<li><a href='/{i}'>Story {i}</a></li>" for i in range(6)) + "</ul>"
    prose = "<ul><li>First point, stated plainly.</li><li>Second point, also plain.</li></ul>"
    out = convert(page(f"<div class='content'>{para(1)}{links}{para(2)}{prose}</div>")).markdown
    assert "Story 3" not in out
    assert "- First point, stated plainly." in out


def test_class_hint_fallback_recovers_an_article_the_hints_removed():
    # "sidebar-layout" matches the unlikely-candidate pattern; the whole article sits in it.
    body = "<div class='sidebar-layout'>" + "".join(para(i) for i in range(1, 6)) + "</div>"
    result = convert(page(body))
    assert result.fallback_used
    assert "Paragraph 5." in result.markdown
    no_fallback = convert(page(body), options=ExtractOptions(fallback=False))
    assert "Paragraph 5." not in no_fallback.markdown


def test_data_tables_and_code_survive_cleaning():
    table = (
        "<table><tr><th>k</th><th>v</th></tr><tr><td><a href='/a'>a</a></td><td>1</td></tr></table>"
    )
    code = "<pre><code class='language-sh'>ls -la</code></pre>"
    out = convert(page(f"<div class='post'>{para(1)}{table}{code}{para(2)}</div>")).markdown
    assert "| k | v |" in out
    assert "```sh\nls -la\n```" in out


def test_headline_repeating_the_title_is_dropped():
    html = (
        "<html><head><title>Big news today | Site</title></head><body><article>"
        "<h1>Big news today</h1>" + para(1) + para(2) + "</article></body></html>"
    )
    out = convert(html).markdown
    assert "Big news today" not in out
    assert "Paragraph 1." in out


@pytest.mark.parametrize("field", ["hints", "link_density", "siblings", "clean", "fallback"])
def test_every_ablation_still_extracts_the_example(field):
    html = (EXAMPLES / "news_article.html").read_text(encoding="utf-8")
    out = convert(html, options=ExtractOptions(**{field: False})).markdown
    assert "reopened to traffic" in out


@pytest.mark.parametrize(
    "body, expected",
    [
        # Every block is under the 25-character paragraph floor, so nothing
        # scores and cleaning removes the rest; the visible body is returned.
        ("<ul><li>Milk</li><li>Eggs</li><li>Bread</li></ul>", "- Milk\n- Eggs\n- Bread\n"),
        (
            "<table><tr><td>Name</td><td>Age</td></tr><tr><td>Ann</td><td>31</td></tr></table>",
            "|  |  |\n|---|---|\n| Name | Age |\n| Ann | 31 |\n",
        ),
        ("<div><b>Opening hours</b></div><ol><li>Mon 9-5</li><li>Tue 9-5</li></ol>", None),
    ],
    ids=["short-list", "small-table", "short-list-with-label"],
)
def test_short_page_of_lists_or_tables_is_not_empty(body, expected):
    result = convert(page(body + "<script>var hidden = 1;</script>"))
    assert result.markdown.strip()
    assert result.fallback_used
    assert "hidden" not in result.markdown
    if expected is not None:
        assert result.markdown == expected


def test_body_fallback_is_part_of_the_fallback_switch():
    html = page("<ul><li>Milk</li><li>Eggs</li></ul>")
    assert convert(html, options=ExtractOptions(fallback=False)).markdown == "\n"


def test_page_with_no_visible_text_stays_empty():
    result = convert(page("<script>var x = 1;</script><div hidden>secret</div>"))
    assert result.markdown == "\n"
    assert result.warnings == ["no text content found"]


def test_main_content_off_renders_everything():
    html = (EXAMPLES / "news_article.html").read_text(encoding="utf-8")
    everything = convert(html, main_content=False).markdown
    assert "Related stories" in everything and "reopened to traffic" in everything


@pytest.mark.parametrize("html", ["", "<html></html>", "<p>hi</p>", "<<<>>>", "\x00\x01garbage"])
def test_degenerate_inputs_do_not_crash(html):
    result = convert(html)
    assert isinstance(result.markdown, str)
    if not result.markdown.strip():
        assert result.warnings == ["no text content found"]


def test_conversion_reports_token_saving():
    html = (EXAMPLES / "news_article.html").read_text(encoding="utf-8")
    result = convert(html)
    assert 0 < result.tokens_markdown < result.tokens_html
    assert 0.5 < result.token_saving < 1
    assert result.as_dict()["tokens"]["saving"] == round(result.token_saving, 4)
