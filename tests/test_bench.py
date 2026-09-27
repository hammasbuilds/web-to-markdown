"""The benchmark harness is code too: its metric, structure matcher and loaders."""

import gzip
import json

import pytest

from bench import datasets
from bench.metrics import (
    bootstrap,
    corpus_score,
    page_counts,
    page_f1,
    paired_bootstrap_diff,
    shingles,
)
from bench.report import failure_category
from bench.structure import gold_structures, regions, survives
from bench.textview import markdown_to_text


def test_shingles_and_short_texts():
    assert list(shingles("a b c d e")) == [("a", "b", "c", "d"), ("b", "c", "d", "e")]
    assert list(shingles("a b")) == [("a", "b")]  # shorter than n: one short shingle
    assert shingles("") == {}


def test_page_counts_hand_computed():
    # truth shingles: (a b c d), (b c d e); prediction: (a b c d), (b c d x)
    tp, fp, fn = page_counts("a b c d e", "a b c d x")
    assert (tp, fp, fn) == pytest.approx((1 / 3, 1 / 3, 1 / 3))
    assert page_counts("same text here now", "same text here now") == (1.0, 0.0, 0.0)
    assert page_counts("", "") == (0.0, 0.0, 0.0)


def test_corpus_score_is_harmonic_mean_of_mean_precision_and_mean_recall():
    perfect = (1.0, 0.0, 0.0)
    half_prec = (0.5, 0.5, 0.0)  # precision 0.5, recall 1
    s = corpus_score([perfect, half_prec])
    assert s.precision == pytest.approx(0.75)
    assert s.recall == pytest.approx(1.0)
    assert s.f1 == pytest.approx(2 * 0.75 / 1.75)
    # A page with no shingles on either side is left out of both means, as in the benchmark.
    assert corpus_score([perfect, (0.0, 0.0, 0.0)]).f1 == 1.0
    # An empty prediction scores zero recall and is left out of precision.
    assert corpus_score([perfect, (0.0, 0.0, 1.0)]).recall == pytest.approx(0.5)
    assert page_f1((0.0, 1.0, 0.0)) == 0.0


def test_bootstrap_interval_brackets_the_point_estimate():
    counts = [
        page_counts("a b c d e f g", "a b c d e f g" if i % 3 else "x y z w v") for i in range(30)
    ]
    point = corpus_score(counts).f1
    lo, hi = bootstrap(counts, n_boot=300)["f1"]
    assert lo <= point <= hi and lo < hi


def test_paired_diff_of_a_system_with_itself_is_zero():
    counts = [page_counts("a b c d e", "a b c d x")] * 5
    assert paired_bootstrap_diff(counts, counts, n_boot=50) == (0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        paired_bootstrap_diff(counts, counts[:2])


def test_textview_drops_images_link_targets_and_fence_info():
    md = (
        "See [the docs](https://x.org/a_b) ![alt text](i.png) [![logo](l.png)](/home)"
        "\n```python\nx = 1\n```"
    )
    assert markdown_to_text(md) == "See the docs  \n```\nx = 1\n```"


def test_failure_categories():
    assert failure_category((0.0, 0.0, 1.0), "") == "empty output"
    assert failure_category((0.05, 0.0, 0.95), "x") == "wrong block (almost none of the article)"
    assert failure_category((0.5, 0.0, 0.5), "x") == "under-extraction (article partly missing)"
    assert failure_category((0.5, 0.5, 0.0), "x") == "over-extraction (boilerplate kept)"
    assert failure_category((0.4, 0.3, 0.3), "x") == "mixed (part of the article plus boilerplate)"
    assert failure_category((0.9, 0.05, 0.05), "x") == "ok"


HTML = """<div>
<h2>Setup steps</h2>
<ul><li>install the package</li><li>run the command</li><li>check output</li></ul>
<table><tr><th>name</th><th>value</th></tr><tr><td>alpha</td><td>one</td></tr></table>
<pre>for i in range(3):
    print(i)</pre>
<ul><li><a href="/nav">Home page</a></li><li><a href="/x">Other page</a></li></ul>
</div>"""
TRUTH = (
    "Setup steps install the package run the command check output name value alpha one "
    "for i in range(3): print(i)"
)


def test_gold_structures_only_count_what_the_truth_contains():
    kinds = sorted(g.kind for g in gold_structures(HTML, TRUTH))
    assert kinds == ["code", "heading", "list", "table"]  # the nav list is not in the truth


def test_structure_survives_in_markdown_but_not_in_flat_text():
    golds = gold_structures(HTML, TRUTH)
    good = regions(
        "## Setup steps\n\n- install the package\n- run the command\n- check output\n\n"
        "| name | value |\n|---|---|\n| alpha | one |\n\n```\nfor i in range(3):\n    print(i)\n```"
    )
    assert all(survives(g, good) for g in golds)
    flat = regions(TRUTH)
    assert not any(survives(g, flat) for g in golds)


def test_structure_accepts_html2text_style_tables_and_indented_code():
    golds = {g.kind: g for g in gold_structures(HTML, TRUTH)}
    reg = regions(
        "name | value\n---|---\nalpha | one\n\n    for i in range(3):\n        print(i)\n"
    )
    assert survives(golds["table"], reg)
    assert survives(golds["code"], reg)


def test_code_collapsed_onto_one_line_does_not_survive():
    golds = {g.kind: g for g in gold_structures(HTML, TRUTH)}
    assert not survives(golds["code"], regions("```\nfor i in range(3): print(i)\n```"))


def test_site_and_split_are_deterministic():
    assert datasets.site_of("https://www.bbc.co.uk/news/x") == "bbc.co.uk"
    assert datasets.site_of("http://blog.example.com/p") == "example.com"
    assert datasets.split_of("example.com") == datasets.split_of("example.com")
    assert {datasets.split_of(f"site{i}.com") for i in range(20)} == {"dev", "heldout"}


def test_loaders_read_a_fixture_tree(tmp_path, monkeypatch):
    aeb = tmp_path / "aeb"
    (aeb / "html").mkdir(parents=True)
    (aeb / "ground-truth.json").write_text(
        json.dumps({"p1": {"articleBody": "Body.", "url": "https://a.org/x"}}), encoding="utf-8"
    )
    (aeb / "html" / "p1.html.gz").write_bytes(gzip.compress(b"<p>Body.</p>"))
    wceb = tmp_path / "wceb" / "combined"
    (wceb / "ground-truth").mkdir(parents=True)
    (wceb / "html" / "cleaneval").mkdir(parents=True)
    rows = [{"page_id": "w1", "plaintext": "Text."}, {"page_id": "w2", "plaintext": " "}]
    (wceb / "ground-truth" / "cleaneval.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )
    (wceb / "html" / "cleaneval" / "w1.html").write_bytes(
        b"<link rel='canonical' href='https://c.org/p'><p>Text.</p>"
    )
    pages = datasets.load_aeb(tmp_path)
    assert [(p.page_id, p.site, p.truth) for p in pages] == [("p1", "a.org", "Body.")]
    wpages = datasets.load_wceb(tmp_path)
    assert [(p.dataset, p.page_id, p.url) for p in wpages] == [
        ("wceb/cleaneval", "w1", "https://c.org/p")  # the empty-truth page is skipped
    ]
    with pytest.raises(FileNotFoundError, match="fetch_data"):
        datasets.load_aeb(tmp_path / "nowhere")
