from web2md.dom import MAX_DEPTH, parse


def tags(el):
    return [c.tag for c in el.elements]


def test_implied_paragraph_end():
    body = parse("<body><p>one<p>two<div>three</div></body>").find("body")
    assert tags(body) == ["p", "p", "div"]
    assert [p.text() for p in body.elements] == ["one", "two", "three"]


def test_implied_list_item_and_cell_ends():
    root = parse("<ul><li>a<li>b<ul><li>b1<li>b2</ul><li>c</ul>")
    outer = root.find("ul")
    assert [li.text() for li in outer.elements] == ["a", "bb1b2", "c"]
    table = parse("<table><tr><td>1<td>2<tr><td>3<td>4</table>").find("table")
    rows = list(table.iter("tr"))
    assert [[c.text() for c in r.elements] for r in rows] == [["1", "2"], ["3", "4"]]


def test_stray_end_tags_are_ignored():
    root = parse("<div>a</span></p><b>b</div>c")
    div = root.find("div")
    assert div.text() == "ab"
    assert root.text().endswith("c")


def test_void_elements_have_no_children():
    root = parse("<p>a<br>b<img src=x.png>c</p>")
    p = root.find("p")
    assert tags(p) == ["br", "img"]
    assert p.text() == "abc"


def test_entities_are_decoded_and_script_is_not_text():
    root = parse("<p>fish &amp; chips&nbsp;&pound;5</p><script>var x = '<p>no</p>';</script>")
    assert root.find("p").text() == "fish & chips\xa0\xa35"
    assert "var x" not in root.text()
    assert "var x" in "".join(c for c in root.find("script").children if isinstance(c, str))


def test_unclosed_inline_tags_cannot_exceed_max_depth():
    root = parse("<font>" * (MAX_DEPTH * 5) + "deep text")
    depth = max(len(list(el.ancestors())) for el in root.iter())
    assert depth <= MAX_DEPTH
    assert "deep text" in root.text()


def test_remove_detaches_node():
    root = parse("<div><p>keep</p><p>drop</p></div>")
    drop = list(root.iter("p"))[1]
    drop.remove()
    assert drop.parent is None
    assert root.text() == "keep"


def test_body_inside_noscript_does_not_become_the_body():
    html = (
        "<html><head><title>t</title></head><script>x</script>"
        "<noscript><body class='nojs'></noscript><div><p>The real article.</p></div></html>"
    )
    root = parse(html)
    bodies = list(root.iter("body"))
    assert bodies == [] or "The real article." in bodies[0].text()
    assert "The real article." in root.text()


def test_second_body_and_html_tags_are_ignored():
    root = parse("<html><body><p>a</p><body><html><p>b</p></body></html>")
    assert len(list(root.iter("body"))) == 1 and len(list(root.iter("html"))) == 1
    assert root.find("body").text() == "ab"


def test_body_start_tag_closes_an_open_head():
    root = parse("<html><head><title>t</title><body><p>x</p>")
    assert root.find("head").find("p") is None
    assert root.find("body").text() == "x"


def test_self_closing_syntax_on_normal_elements():
    root = parse("<div/><p>after</p>")
    assert root.find("div").children == []
    assert root.find("p").parent is root


def test_body_content_closes_head_even_when_a_broken_quote_ate_the_body_tag():
    html = '<html><head><title>t</title><meta content="broken></head><body x="y">\n<div>Story</div>'
    root = parse(html)
    head = root.find("head")
    assert "Story" not in head.text()
    assert "Story" in root.text()


def test_stray_text_in_head_moves_out_of_it():
    root = parse("<html><head><title>t</title>Visible</head><body></body></html>")
    assert "Visible" not in root.find("head").text()
