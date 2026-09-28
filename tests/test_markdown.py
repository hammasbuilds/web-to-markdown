import pytest

from web2md.dom import parse
from web2md.markdown import RenderOptions, code_language, to_markdown


def md(html: str, **opts) -> str:
    return to_markdown(parse(html), RenderOptions(**opts)).strip()


def test_headings_and_paragraphs():
    assert md("<h2>Title  here</h2><p>Body\n  text.</p>") == "## Title here\n\nBody text."


def test_empty_heading_is_dropped():
    assert md("<h3> </h3><p>x</p>") == "x"


def test_inline_text_next_to_a_block_becomes_its_own_paragraph():
    assert md("<div>intro<ul><li>a</li></ul>outro</div>") == "intro\n\n- a\n\noutro"


def test_single_br_is_a_line_break_double_br_a_paragraph():
    assert md("<div>one<br>two<br><br>three</div>") == "one\ntwo\n\nthree"


def test_nested_lists_indent_under_their_marker():
    html = "<ol start='3'><li>three<ul><li>a</li><li>b</li></ul></li><li>four</li></ol>"
    assert md(html) == "3. three\n   - a\n   - b\n4. four"


def test_list_nested_directly_in_list_attaches_to_previous_item():
    assert md("<ul><li>a</li><ul><li>a1</li></ul><li>b</li></ul>") == "- a\n  - a1\n- b"


def test_bad_ol_start_falls_back_to_one():
    assert md("<ol start='x'><li>a</li></ol>") == "1. a"


def test_table_with_header_row():
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>x|y</td></tr></table>"
    assert md(html) == "| A | B |\n|---|---|\n| 1 | x\\|y |"


def test_table_without_header_gets_an_empty_one_and_colspan_pads():
    html = "<table><tr><td colspan=2>wide</td></tr><tr><td>1</td><td>2</td></tr></table>"
    assert md(html) == "|  |  |\n|---|---|\n| wide |  |\n| 1 | 2 |"


def test_content_outside_cells_is_rendered_before_the_table():
    # Browsers foster-parent a <p> directly in <table> and a <div> in a <tr> to
    # just before the table; neither may be dropped.
    html = (
        "<table><p>Prices from May</p><tr><th>A</th><th>B</th></tr>"
        "<tr><div>note in a row</div><td>1</td><td>2</td></tr></table>"
    )
    assert md(html) == "Prices from May\n\nnote in a row\n\n| A | B |\n|---|---|\n| 1 | 2 |"


def test_stray_text_in_a_table_is_kept():
    html = "<table>loose words<tr><td>1</td><td>2</td></tr></table>"
    assert md(html).startswith("loose words\n\n|")


def test_rows_wrapped_in_a_form_are_table_rows():
    html = (
        "<table><form action='/buy'><tr><th>Item</th><th>Qty</th></tr>"
        "<tr><td>Tea</td><td>2</td></tr></form></table>"
    )
    assert md(html) == "| Item | Qty |\n|---|---|\n| Tea | 2 |"


def test_caption_and_colgroup_are_not_stray():
    html = (
        "<table><caption>Scores</caption><colgroup><col></colgroup>"
        "<tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    )
    assert md(html) == "Scores\n\n| A | B |\n|---|---|\n| 1 | 2 |"


def test_layout_tables_render_as_blocks():
    one_column = "<table><tr><td><p>just</p></td></tr><tr><td><p>text</p></td></tr></table>"
    assert md(one_column) == "just\n\ntext"
    nested = (
        "<table><tr><td><table><tr><td>a</td><td>b</td></tr></table></td><td>c</td></tr></table>"
    )
    assert "|" in md(nested) and md(nested).endswith("c")


def test_code_block_keeps_whitespace_and_language():
    html = '<pre><code class="language-python">def f():\n    return 1\n</code></pre>'
    assert md(html) == "```python\ndef f():\n    return 1\n```"


def test_code_fence_grows_past_backticks_in_the_code():
    assert md("<pre>use ``` here</pre>").startswith("````\nuse ``` here\n````")


@pytest.mark.parametrize(
    ("html", "lang"),
    [
        ('<div class="highlight-rust"><div class="highlight"><pre>x</pre></div></div>', "rust"),
        ('<pre class="brush: js">x</pre>', "js"),
        ('<pre data-lang="Go">x</pre>', "go"),
        ('<pre class="language-text">x</pre>', ""),
        ("<pre>x</pre>", ""),
    ],
)
def test_code_language_detection(html, lang):
    assert code_language(parse(html).find("pre")) == lang


def test_inline_code_and_emphasis():
    html = "<p>Call <code>f(`x`)</code> <strong> now </strong><em></em><del>old</del></p>"
    assert md(html) == "Call ``f(`x`)`` **now** ~~old~~"


def test_links_resolve_against_base_and_skip_script_links():
    html = (
        '<p><a href="/a b">rel</a> <a href="javascript:void(0)">js</a> '
        '<a href="#top">anchor</a> <a href="https://x.org/q?a=(1)">abs</a></p>'
    )
    out = md(html, base_url="https://site.example/dir/page")
    assert out == ("[rel](https://site.example/a%20b) js anchor [abs](https://x.org/q?a=(1%29)")


def test_no_links_option_keeps_text():
    assert md('<p><a href="/x">text</a></p>', links=False) == "text"


def test_images_alt_and_src_and_options():
    assert md('<p><img src="a.png" alt="A [cat]"></p>') == "![A (cat)](a.png)"
    assert md('<p><img src="a.png" alt="A cat"></p>', images=False) == "A cat"
    assert md('<p><img alt="no src"></p>') == "no src"
    assert md('<p><img src="data:image/png;base64,xx" alt="inline"></p>') == "inline"


def test_blockquote_nesting():
    html = "<blockquote><p>a</p><blockquote><p>b</p></blockquote></blockquote>"
    assert md(html) == "> a\n>\n> > b"


def test_markdown_lookalikes_at_line_start_are_escaped():
    assert md("<p># not a heading</p><p>1. not a list</p><p>- nor this</p>") == (
        "\\# not a heading\n\n\\1. not a list\n\n\\- nor this"
    )


def test_invisible_and_interactive_elements_are_skipped():
    html = "<p>a<script>x()</script><button>Click</button><select><option>o</option></select>b</p>"
    assert md(html) == "ab"


def test_hr_and_definition_lists():
    assert md("<p>a</p><hr><dl><dt>Term</dt><dd>Meaning</dd></dl>") == (
        "a\n\n---\n\n**Term**\n\nMeaning"
    )


def test_empty_document():
    assert md("") == ""
