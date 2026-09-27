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
